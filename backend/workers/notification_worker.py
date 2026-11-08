"""
Simple polling worker for the notification subsystem (Phase 9).

No external queue/broker — this is deliberately the "simple Python
worker/scheduler" called for in the project brief's tech stack, not Celery/Kafka/
Redis. NotificationWorker.run_once() is fully synchronous and testable; the
module can also be run standalone as a separate OS process:

    python -m workers.notification_worker
"""
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict
from sqlalchemy.orm import Session

from app.config import settings
from models.notification import NotificationStatus
from repositories.notification_repository import notification_repository
from services.notification_service import notification_service

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 30.0


class NotificationWorker:
    def __init__(self, batch_size: int = 20):
        self.batch_size = batch_size

    def run_once(self, db: Session) -> Dict[str, int]:
        """Claim one batch of due jobs and attempt to process each. Returns
        counts for observability — never raises for an individual job failure.
        NotificationService.process_job converts provider failures into a
        persisted job state (PENDING-for-retry or FAILED); a job that could not
        even be persisted (a database error) stays PROCESSING, and
        requeue_stale_processing recovers it on a later run, along with any
        batch abandoned by a crashed worker."""
        stale_before = datetime.now(timezone.utc) - timedelta(minutes=settings.NOTIFICATION_PROCESSING_TIMEOUT_MINUTES)
        recovered = notification_repository.requeue_stale_processing(
            db, stale_before, settings.NOTIFICATION_MAX_ATTEMPTS
        )
        if recovered:
            logger.warning("NotificationWorker: recovered %s job(s) left PROCESSING by a previous run", recovered)

        jobs = notification_repository.get_due_jobs(db, limit=self.batch_size)
        stats = {"claimed": len(jobs), "sent": 0, "failed": 0, "retrying": 0, "errored": 0}

        for job in jobs:
            job_id = job.id
            try:
                processed = notification_service.process_job(db, job)
            except Exception:
                db.rollback()
                logger.exception("NotificationWorker: could not process job %s", job_id)
                stats["errored"] += 1
                continue
            if processed.status == NotificationStatus.SENT:
                stats["sent"] += 1
            elif processed.status == NotificationStatus.FAILED:
                stats["failed"] += 1
            else:
                stats["retrying"] += 1

        return stats


notification_worker = NotificationWorker()


def run_forever(poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS) -> None:
    """Standalone entrypoint loop. Opens its own DB session per iteration so
    a long-lived connection doesn't go stale between polls."""
    from app.database import SessionLocal

    logger.info("NotificationWorker starting (poll_interval=%ss)", poll_interval_seconds)
    while True:
        db = SessionLocal()
        try:
            stats = notification_worker.run_once(db)
            if stats["claimed"]:
                logger.info("NotificationWorker batch: %s", stats)
        except Exception:
            logger.exception("NotificationWorker: unexpected error processing batch")
        finally:
            db.close()
        time.sleep(poll_interval_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_forever()
