import enum
import uuid
from datetime import datetime, timezone
from app.core.datetime_utils import UTCDateTime
from sqlalchemy import Column, String, Boolean, Integer, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class UserRole(str, enum.Enum):
    PATIENT = "PATIENT"
    DOCTOR = "DOCTOR"
    ADMIN = "ADMIN"


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(SQLEnum(UserRole), nullable=False, default=UserRole.PATIENT, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    # Bumped on logout. Every access token carries the value it was issued under
    # ("tv" claim) and is rejected once that no longer matches, so signing out
    # invalidates a token that was copied or stolen, not just the browser's copy.
    token_version = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(UTCDateTime(), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(UTCDateTime(), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    doctor_profile = relationship("Doctor", back_populates="user", uselist=False, cascade="all, delete-orphan")
    patient_appointments = relationship("Appointment", foreign_keys="Appointment.patient_id", back_populates="patient")
    doctor_appointments = relationship("Appointment", foreign_keys="Appointment.doctor_id", back_populates="doctor_user")
    holds = relationship("AppointmentHold", back_populates="patient")

    def __repr__(self):
        return f"<User id={self.id} email={self.email} role={self.role}>"
