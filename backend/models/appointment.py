import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum, Index, text
from sqlalchemy.orm import relationship
from app.database import Base


class AppointmentStatus(str, enum.Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    RESCHEDULED = "RESCHEDULED"
    CANCELLED = "CANCELLED"
    CONFLICTED = "CONFLICTED"
    COMPLETED = "COMPLETED"


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # NOTE: doctor_id references the doctor's USER account (users.id).
    # This differs from AppointmentHold.doctor_id, which references the doctor
    # PROFILE (doctors.id). Use doctor_profile_id below when a doctor profile
    # id is needed for appointments.
    doctor_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    doctor_profile_id = Column(String(36), ForeignKey("doctors.id", ondelete="CASCADE"), nullable=True, index=True)
    start_time = Column(DateTime(timezone=True), nullable=False, index=True)
    end_time = Column(DateTime(timezone=True), nullable=False)
    status = Column(SQLEnum(AppointmentStatus), nullable=False, default=AppointmentStatus.CONFIRMED, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index('idx_doctor_start_time_status', 'doctor_id', 'start_time', 'status'),
        # Database-level double-booking guard: at most one active (HELD /
        # CONFIRMED / RESCHEDULED) appointment may exist for a given doctor
        # profile and start_time. This is the final authority — enforced by
        # the DB regardless of application-level locking.
        Index(
            'uq_doctor_profile_start_time_active',
            'doctor_profile_id', 'start_time',
            unique=True,
            sqlite_where=text("status IN ('HELD', 'CONFIRMED', 'RESCHEDULED')"),
            postgresql_where=text("status IN ('HELD', 'CONFIRMED', 'RESCHEDULED')"),
        ),
    )

    # Relationships
    patient = relationship("User", foreign_keys=[patient_id], back_populates="patient_appointments")
    doctor_user = relationship("User", foreign_keys=[doctor_id], back_populates="doctor_appointments")
    doctor = relationship("Doctor", foreign_keys=[doctor_profile_id], back_populates="appointments")
    
    symptom_report = relationship("SymptomReport", back_populates="appointment", uselist=False, cascade="all, delete-orphan")
    ai_summaries = relationship("AISummary", back_populates="appointment", cascade="all, delete-orphan")
    consultation = relationship("Consultation", back_populates="appointment", uselist=False, cascade="all, delete-orphan")
    notification_jobs = relationship("NotificationJob", back_populates="appointment", cascade="all, delete-orphan")
    calendar_events = relationship("CalendarEvent", back_populates="appointment", cascade="all, delete-orphan")

    # Display names for API responses, so portals can show who an
    # appointment is with instead of bare ids.
    @property
    def patient_name(self):
        return self.patient.full_name if self.patient else None

    @property
    def doctor_name(self):
        return self.doctor_user.full_name if self.doctor_user else None

    @property
    def doctor_specialization(self):
        return self.doctor.specialization if self.doctor else None

    def __repr__(self):
        return f"<Appointment id={self.id} status={self.status} start={self.start_time}>"


class AppointmentHold(Base):
    __tablename__ = "appointment_holds"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # NOTE: doctor_id here references the doctor PROFILE (doctors.id), unlike
    # Appointment.doctor_id above which references the doctor's USER account
    # (users.id). Do not mix the two across models.
    doctor_id = Column(String(36), ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False, index=True)
    patient_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    start_time = Column(DateTime(timezone=True), nullable=False, index=True)
    end_time = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships
    doctor = relationship("Doctor", back_populates="holds")
    patient = relationship("User", back_populates="holds")

    def __repr__(self):
        return f"<AppointmentHold id={self.id} active={self.is_active} expires_at={self.expires_at}>"
