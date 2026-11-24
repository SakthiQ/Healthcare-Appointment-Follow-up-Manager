import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, Date, ForeignKey, String, Text

from app.core.datetime_utils import UTCDateTime
from app.database import Base


class PatientProfile(Base):
    """Optional health details a patient keeps about themself. Health data: readable only by
    the patient, the doctor of one of their appointments, and admins, and audited."""
    __tablename__ = "patient_profiles"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    date_of_birth = Column(Date, nullable=True)
    phone = Column(String(32), nullable=True)
    allergies = Column(Text, nullable=True)
    updated_at = Column(UTCDateTime(), nullable=False, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
