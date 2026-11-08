import hashlib
import math
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from app.config import settings
from app.exceptions import TooManyRequestsError
from repositories.rate_limit_repository import rate_limit_repository

ONE_HOUR_SECONDS = 3600


class RateLimitService:
    """Fixed-window request limits, kept in the database so they hold across instances.

    `identity` is whatever the limit is per: a client IP, a user id, a target email.
    Only a hash of "bucket|identity" is stored.
    """

    def check(self, db: Session, bucket: str, identity: str, limit: int, window_seconds: int = ONE_HOUR_SECONDS) -> None:
        """Count one request; raise TooManyRequestsError (HTTP 429 + Retry-After) over `limit`."""
        if not settings.RATE_LIMITING_ENABLED:
            return
        key = hashlib.sha256(f"{bucket}|{identity.strip().lower()}".encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)
        count, window_end = rate_limit_repository.hit(db, key, now, timedelta(seconds=window_seconds))
        if count > limit:
            retry_after = max(1, math.ceil((window_end - now).total_seconds()))
            raise TooManyRequestsError(
                f"Too many requests. Please try again in about {max(1, math.ceil(retry_after / 60))} minute(s).",
                retry_after_seconds=retry_after,
            )


rate_limit_service = RateLimitService()
