"""
Simple polling worker for calendar synchronisation (Phase 10).

Mirrors NotificationWorker: no broker, fully synchronous and testable via
run_once(), runnable standalone as its own OS process:

    python -m workers.calendar_worker
"""
import logging
import time
from typing import Dict
from sqlalchemy.orm import Session

from models.calendar import CalendarSyncStatus, CalendarOperation
from repositories.calendar_repository import calendar_repository
from services.calendar_service import calendar_service

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 30.0


class CalendarWorker:
    def __init__(self, batch_size: int = 20):
        self.batch_size = batch_size

    def run_once(self, db: Session) -> Dict[str, int]:
        """Process one batch of pending calendar syncs. Never raises for an
        individual row — CalendarService.process_pending_row already converts
        failures into a persisted row state (PENDING_SYNC-for-retry or FAILED)."""
        rows = calendar_repository.get_due_syncs(db, limit=self.batch_size)
        stats = {"claimed": len(rows), "synced": 0, "failed": 0, "retrying": 0}

        for row in rows:
            processed = calendar_service.process_pending_row(db, row)
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
        try:
            stats = calendar_worker.run_once(db)
            if stats["claimed"]:
                logger.info("CalendarWorker batch: %s", stats)
        except Exception:
            logger.exception("CalendarWorker: unexpected error processing batch")
        finally:
            db.close()
        time.sleep(poll_interval_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_forever()
