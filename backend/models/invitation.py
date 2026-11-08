import uuid
from datetime import datetime, timezone as dt_timezone
from app.core.datetime_utils import UTCDateTime
from sqlalchemy import Column, ForeignKey, Integer, String
from app.database import Base


class Invitation(Base):
    """An admin's invitation for someone to join as a doctor or an administrator.

    The invitee opens the emailed link on the normal signup page. The role, and for a doctor
    the profile, come from this row, never from the signup form, so a person cannot choose
    their own privileges. Only a SHA-256 of the token is stored. Single use, and it expires.
    """
    __tablename__ = "invitations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), nullable=False, index=True)
    # "DOCTOR" or "ADMIN". Patients sign themselves up.
    role = Column(String(16), nullable=False)
    full_name = Column(String(255), nullable=True)
    # The doctor profile the admin chose; null for an admin invitation.
    specialization = Column(String(255), nullable=True)
    slot_duration_minutes = Column(Integer, nullable=True)
    timezone = Column(String(64), nullable=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    invited_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    expires_at = Column(UTCDateTime(), nullable=False)
    used_at = Column(UTCDateTime(), nullable=True)
    revoked_at = Column(UTCDateTime(), nullable=True)
    created_at = Column(UTCDateTime(), nullable=False, default=lambda: datetime.now(dt_timezone.utc))
