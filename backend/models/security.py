from datetime import datetime, timezone
from app.core.datetime_utils import UTCDateTime
from sqlalchemy import Column, Integer, String
from app.database import Base


class LoginThrottle(Base):
    """Failed-login bookkeeping for one (email, client IP) pair.

    Stored in the database, not in process memory, so the limit holds across web
    instances and restarts. `key` is a SHA-256 of the pair, so the table holds no
    plain email addresses or IPs.
    """
    __tablename__ = "login_throttles"

    key = Column(String(64), primary_key=True)
    failed_count = Column(Integer, nullable=False, default=0)
    window_started_at = Column(UTCDateTime(), nullable=False, default=lambda: datetime.now(timezone.utc))
    locked_until = Column(UTCDateTime(), nullable=True)
