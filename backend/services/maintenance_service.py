from datetime import datetime, timedelta, timezone
from typing import Dict
from sqlalchemy.orm import Session
from repositories.auth_token_repository import auth_token_repository
from repositories.login_throttle_repository import login_throttle_repository
from repositories.rate_limit_repository import rate_limit_repository


class MaintenanceService:
    """Housekeeping for tables that only ever grow: rate-limit counters, login-throttle
    counters and spent or expired email tokens. Nothing depends on this for correctness
    (every read checks expiry itself); it only stops the tables growing without bound.
    The audit log is NOT touched: its retention is a policy decision, not housekeeping."""

    def purge_expired(self, db: Session) -> Dict[str, int]:
        now = datetime.now(timezone.utc)
        one_day_ago = now - timedelta(days=1)
        counts = {
            "rate_limits": rate_limit_repository.purge_older_than(db, one_day_ago),
            "login_throttles": login_throttle_repository.purge_stale(db, one_day_ago),
            "auth_tokens": auth_token_repository.purge_expired(db, now - timedelta(days=7)),
        }
        return counts


maintenance_service = MaintenanceService()
