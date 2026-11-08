"""
Purges expired rate-limit counters, login-throttle counters and email tokens.

Housekeeping only: every read already checks expiry, so this can be slow and
infrequent. Same shape as the other workers: `run_once` is synchronous and testable,
and the module runs standalone as its own process:

    python -m workers.maintenance_worker
"""
import logging
import time
from typing import Dict
from sqlalchemy.orm import Session

from services.maintenance_service import maintenance_service

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 3600.0


class MaintenanceWorker:
    def run_once(self, db: Session) -> Dict[str, int]:
        counts = maintenance_service.purge_expired(db)
        # "claimed" is what WorkerRunner logs on: only worth a line when work was done.
        return {"claimed": sum(counts.values()), **counts}


maintenance_worker = MaintenanceWorker()


def run_forever(poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS) -> None:
    from app.database import SessionLocal

    logger.info("MaintenanceWorker starting (poll_interval=%ss)", poll_interval_seconds)
    while True:
        db = SessionLocal()
        try:
            stats = maintenance_worker.run_once(db)
            if stats["claimed"]:
                logger.info("MaintenanceWorker purged: %s", stats)
        except Exception:
            logger.exception("MaintenanceWorker: unexpected error")
        finally:
            db.close()
        time.sleep(poll_interval_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_forever()
