import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.datetime_utils import UTCDateTime
from app.database import Base


class WaitlistEntry(Base):
    """A patient waiting for a slot with one doctor on one (doctor-local) date. An entry is
    active until notified_at is set; joining the same day again re-arms it."""
    __tablename__ = "waitlist_entries"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    doctor_id = Column(String(36), ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    created_at = Column(UTCDateTime(), nullable=False, default=lambda: datetime.now(timezone.utc))
    notified_at = Column(UTCDateTime(), nullable=True)

    doctor = relationship("Doctor")

    __table_args__ = (
        UniqueConstraint("patient_id", "doctor_id", "date", name="uq_waitlist_patient_doctor_date"),
    )
