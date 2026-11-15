"""
Simple polling worker for calendar synchronisation (Phase 10).

Mirrors NotificationWorker: no broker, fully synchronous and testable via
run_once(), runnable standalone as its own OS process:

    python -m workers.calendar_worker
"""
import logging
import time
from typing import Dict, Optional
from sqlalchemy.orm import Session

from app.config import settings

from models.calendar import CalendarSyncStatus, CalendarOperation
from repositories.calendar_repository import calendar_repository
from services.calendar_service import calendar_service
from workers.runner import batch_was_full

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 30.0


class CalendarWorker:
    def __init__(self, batch_size: Optional[int] = None):
        self.batch_size = batch_size or settings.CALENDAR_BATCH_SIZE

    def run_once(self, db: Session) -> Dict[str, int]:
        """Process one batch of pending calendar syncs. Never raises for an
        individual row — CalendarService.process_pending_row converts provider
        failures into a persisted row state (PENDING_SYNC-for-retry or FAILED);
        a row that could not even be persisted (a database error) stays
        PENDING_SYNC for the next run, and the rest of the batch still runs."""
        rows = calendar_repository.get_due_syncs(db, limit=self.batch_size)
        stats = {"claimed": len(rows), "synced": 0, "failed": 0, "retrying": 0, "errored": 0}

        for row in rows:
            row_id = row.id
            try:
                processed = calendar_service.process_pending_row(db, row)
            except Exception:
                db.rollback()
                logger.exception("CalendarWorker: could not process row %s", row_id)
                stats["errored"] += 1
                continue
            if processed.status == CalendarSyncStatus.SYNCED:
                stats["synced"] += 1
            elif processed.status == CalendarSyncStatus.FAILED:
                stats["failed"] += 1
            else:
                stats["retrying"] += 1

        return stats


calendar_worker = CalendarWorker()


def run_forever(poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS) -> None:
    from app.database import SessionLocal

    logger.info("CalendarWorker starting (poll_interval=%ss)", poll_interval_seconds)
    while True:
        db = SessionLocal()
        stats = None
        try:
            stats = calendar_worker.run_once(db)
            if stats["claimed"]:
                logger.info("CalendarWorker batch: %s", stats)
        except Exception:
            logger.exception("CalendarWorker: unexpected error processing batch")
        finally:
            db.close()
        # A full batch means more is probably waiting: go again at once.
        if not batch_was_full(calendar_worker, stats):
            time.sleep(poll_interval_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_forever()
