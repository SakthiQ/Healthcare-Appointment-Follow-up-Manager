import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from app.database import Base


class NotificationType(str, enum.Enum):
    BOOKING_CONFIRMATION = "BOOKING_CONFIRMATION"
    APPOINTMENT_REMINDER = "APPOINTMENT_REMINDER"
    CANCELLATION = "CANCELLATION"
    DOCTOR_LEAVE_CONFLICT = "DOCTOR_LEAVE_CONFLICT"
    MEDICATION_REMINDER = "MEDICATION_REMINDER"


class NotificationStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SENT = "SENT"
    FAILED = "FAILED"


class NotificationJob(Base):
    __tablename__ = "notification_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    appointment_id = Column(String(36), ForeignKey("appointments.id", ondelete="CASCADE"), nullable=True, index=True)
    recipient_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    notification_type = Column(SQLEnum(NotificationType), nullable=False, index=True)
    status = Column(SQLEnum(NotificationStatus), nullable=False, default=NotificationStatus.PENDING, index=True)
    attempts = Column(Integer, nullable=False, default=0)
    next_retry_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_error = Column(Text, nullable=True)
    payload = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    appointment = relationship("Appointment", back_populates="notification_jobs")
    recipient = relationship("User", foreign_keys=[recipient_id])

    def __repr__(self):
        return f"<NotificationJob id={self.id} type={self.notification_type} status={self.status} attempts={self.attempts}>"
