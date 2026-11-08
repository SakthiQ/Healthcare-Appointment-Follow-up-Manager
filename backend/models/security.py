import enum
import uuid
from datetime import datetime, timezone
from app.core.datetime_utils import UTCDateTime
from sqlalchemy import Column, ForeignKey, Integer, String
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


class RateLimit(Base):
    """One fixed-window request counter. `key` is a SHA-256 of "bucket|identity", so the
    table holds no plain IPs or email addresses. Stored in the database, not in process
    memory, so limits hold across web instances and restarts."""
    __tablename__ = "rate_limits"

    key = Column(String(64), primary_key=True)
    count = Column(Integer, nullable=False, default=0)
    window_started_at = Column(UTCDateTime(), nullable=False, default=lambda: datetime.now(timezone.utc))


class AuthTokenPurpose(str, enum.Enum):
    PASSWORD_RESET = "PASSWORD_RESET"
    EMAIL_VERIFICATION = "EMAIL_VERIFICATION"


class AuthToken(Base):
    """A single-use, expiring token emailed to a user (password reset, email verification).
    Only a SHA-256 of the token is stored, so a database leak does not yield usable links."""
    __tablename__ = "auth_tokens"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    purpose = Column(String(32), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(UTCDateTime(), nullable=False)
    used_at = Column(UTCDateTime(), nullable=True)
    created_at = Column(UTCDateTime(), nullable=False, default=lambda: datetime.now(timezone.utc))
