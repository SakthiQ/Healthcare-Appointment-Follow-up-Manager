import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, Enum as SQLEnum, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database import Base


class CalendarSyncStatus(str, enum.Enum):
    SYNCED = "SYNCED"
    PENDING_SYNC = "PENDING_SYNC"
    FAILED = "FAILED"


class CalendarOperation(str, enum.Enum):
    """The operation that still needs to be pushed to the external calendar.
    NONE means the row is in sync and the worker should skip it."""
    NONE = "NONE"
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    appointment_id = Column(String(36), ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False, index=True)
    recipient_type = Column(String(50), nullable=False, default="PATIENT")  # PATIENT or DOCTOR
    external_event_id = Column(String(255), nullable=True, index=True)
    status = Column(SQLEnum(CalendarSyncStatus), nullable=False, default=CalendarSyncStatus.PENDING_SYNC, index=True)
    pending_operation = Column(SQLEnum(CalendarOperation), nullable=False, default=CalendarOperation.CREATE, index=True)
    # Stable id sent to the provider on create so a retried create is recognised
    # as the same event instead of producing a duplicate (see CalendarService).
    idempotency_key = Column(String(255), nullable=False, default=lambda: uuid.uuid4().hex)
    attempts = Column(Integer, nullable=False, default=0)
    next_retry_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        # One calendar event row per appointment per side (patient / doctor).
        # This is the DB-level guard against duplicate event rows when a
        # create is retried or a sync is triggered twice.
        UniqueConstraint('appointment_id', 'recipient_type', name='uq_calendar_event_appointment_recipient'),
    )

    # Relationships
    appointment = relationship("Appointment", back_populates="calendar_events")

    def __repr__(self):
        return f"<CalendarEvent external_id={self.external_event_id} status={self.status} op={self.pending_operation}>"
