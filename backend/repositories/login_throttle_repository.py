from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.datetime_utils import ensure_utc
from models.security import LoginThrottle


class LoginThrottleRepository:
    def get(self, db: Session, key: str) -> Optional[LoginThrottle]:
        return db.query(LoginThrottle).filter(LoginThrottle.key == key).first()

    def record_failure(
        self, db: Session, key: str, now: datetime, max_attempts: int, window: timedelta
    ) -> LoginThrottle:
        """Count one failed login. Failures only add up inside one `window`; once it
        (or a lockout) has run out, the count starts again at 1. Reaching
        `max_attempts` locks the key for `window`."""
        row = self.get(db, key)
        if row is None:
            row = LoginThrottle(key=key, failed_count=1, window_started_at=now)
            db.add(row)
        else:
            locked_until = ensure_utc(row.locked_until) if row.locked_until else None
            if now - ensure_utc(row.window_started_at) > window or (locked_until and locked_until <= now):
                row.failed_count = 1
                row.window_started_at = now
                row.locked_until = None
            else:
                row.failed_count += 1
        if row.failed_count >= max_attempts:
            row.locked_until = now + window
        try:
            db.commit()
        except IntegrityError:
            # A concurrent first failure created the row; that attempt was counted.
            db.rollback()
        return row

    def clear(self, db: Session, key: str) -> None:
        if db.query(LoginThrottle).filter(LoginThrottle.key == key).delete():
            db.commit()


login_throttle_repository = LoginThrottleRepository()
