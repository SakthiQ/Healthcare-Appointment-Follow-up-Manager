"""
Sweeps expired slot holds.

Nothing depends on this for correctness: every read ignores holds past their
`expires_at`, and a new hold on a slot clears that slot's stale row itself. The
sweep only stops expired rows piling up flagged active, so it can be slow and
infrequent. Same shape as the other workers: `run_once` is synchronous and
testable, and the module runs standalone as its own process:

    python -m workers.hold_worker
"""
import logging
import time
from typing import Dict
from sqlalchemy.orm import Session

from services.hold_service import hold_service

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 60.0


class HoldExpiryWorker:
    def run_once(self, db: Session) -> Dict[str, int]:
        expired = hold_service.expire_holds(db)
        # "claimed" is what WorkerRunner logs on: only worth a line when work was done.
        return {"claimed": expired, "expired": expired}


hold_expiry_worker = HoldExpiryWorker()


def run_forever(poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS) -> None:
    from app.database import SessionLocal

    logger.info("HoldExpiryWorker starting (poll_interval=%ss)", poll_interval_seconds)
    while True:
        db = SessionLocal()
        try:
            stats = hold_expiry_worker.run_once(db)
            if stats["expired"]:
                logger.info("HoldExpiryWorker swept %s expired hold(s)", stats["expired"])
        except Exception:
            logger.exception("HoldExpiryWorker: unexpected error processing batch")
        finally:
            db.close()
        time.sleep(poll_interval_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_forever()
