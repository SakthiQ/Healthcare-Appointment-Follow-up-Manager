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
from datetime import datetime, timezone
from models.appointment import AppointmentHold
from services.waitlist_service import local_date, waitlist_service

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 60.0


class HoldExpiryWorker:
    @staticmethod
    def _days_with_expired_holds(db: Session) -> set:
        """(doctor, local date) of holds that have expired but are still marked active: a
        slot on each of those days may now be free for someone on the waitlist."""
        now = datetime.now(timezone.utc)
        holds = db.query(AppointmentHold).filter(
            AppointmentHold.is_active.is_(True), AppointmentHold.expires_at <= now
        ).all()
        return {(h.doctor_id, local_date(h.doctor, h.start_time)) for h in holds if h.doctor is not None}

    def run_once(self, db: Session) -> Dict[str, int]:
        freed_days = self._days_with_expired_holds(db)
        expired = hold_service.expire_holds(db)
        for doctor_id, day in freed_days:
            waitlist_service.safe_notify(db, doctor_id, day)
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
