import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Date, Time, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database import Base


class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    specialization = Column(String(255), nullable=False, index=True)
    slot_duration_minutes = Column(Integer, nullable=False, default=30)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship("User", back_populates="doctor_profile")
    working_hours = relationship("DoctorWorkingHours", back_populates="doctor", cascade="all, delete-orphan")
    leaves = relationship("DoctorLeave", back_populates="doctor", cascade="all, delete-orphan")
    appointments = relationship("Appointment", foreign_keys="Appointment.doctor_profile_id", back_populates="doctor")
    holds = relationship("AppointmentHold", back_populates="doctor")

    def __repr__(self):
        return f"<Doctor id={self.id} specialization={self.specialization}>"


class DoctorWorkingHours(Base):
    __tablename__ = "doctor_working_hours"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    doctor_id = Column(String(36), ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False, index=True)
    day_of_week = Column(Integer, nullable=False)  # 0=Monday, 6=Sunday
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint('doctor_id', 'day_of_week', name='uq_doctor_day_working_hours'),
    )

    # Relationships
    doctor = relationship("Doctor", back_populates="working_hours")

    def __repr__(self):
        return f"<DoctorWorkingHours doctor_id={self.doctor_id} day={self.day_of_week}>"


class DoctorLeave(Base):
    __tablename__ = "doctor_leaves"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    doctor_id = Column(String(36), ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False, index=True)
    leave_date = Column(Date, nullable=False, index=True)
    reason = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint('doctor_id', 'leave_date', name='uq_doctor_leave_date'),
    )

    # Relationships
    doctor = relationship("Doctor", back_populates="leaves")

    def __repr__(self):
        return f"<DoctorLeave doctor_id={self.doctor_id} date={self.leave_date}>"
