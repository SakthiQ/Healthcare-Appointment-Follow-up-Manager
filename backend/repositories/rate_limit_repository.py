from datetime import datetime, timedelta
from typing import Tuple
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.datetime_utils import ensure_utc
from models.security import RateLimit


class RateLimitRepository:
    def hit(self, db: Session, key: str, now: datetime, window: timedelta) -> Tuple[int, datetime]:
        """Count one request against `key`. Returns (count in the current window, when that
        window ends). The window starts at the first request and resets once it has run out."""
        for _ in range(3):
            query = db.query(RateLimit).filter(RateLimit.key == key)
            if db.bind and db.bind.dialect.name != "sqlite":
                query = query.with_for_update()
            row = query.first()
            if row is None:
                row = RateLimit(key=key, count=1, window_started_at=now)
                db.add(row)
            elif now - ensure_utc(row.window_started_at) >= window:
                row.count = 1
                row.window_started_at = now
            else:
                row.count += 1
            count, started = row.count, ensure_utc(row.window_started_at)
            try:
                db.commit()
            except IntegrityError:
                # Two first requests raced to create the row; the other won. Count again.
                db.rollback()
                continue
            return count, started + window
        raise RuntimeError("could not record a rate-limit hit")

    def purge_older_than(self, db: Session, cutoff: datetime) -> int:
        deleted = db.query(RateLimit).filter(RateLimit.window_started_at < cutoff).delete(synchronize_session=False)
        db.commit()
        return deleted


rate_limit_repository = RateLimitRepository()
