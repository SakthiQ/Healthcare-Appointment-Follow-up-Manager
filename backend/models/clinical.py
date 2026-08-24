import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, Enum as SQLEnum, JSON
from sqlalchemy.orm import relationship
from app.database import Base


class AISummaryType(str, enum.Enum):
    PRE_VISIT = "PRE_VISIT"
    POST_VISIT = "POST_VISIT"


class AISummaryStatus(str, enum.Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class SymptomReport(Base):
    __tablename__ = "symptom_reports"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    appointment_id = Column(String(36), ForeignKey("appointments.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    symptoms = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships
    appointment = relationship("Appointment", back_populates="symptom_report")

    def __repr__(self):
        return f"<SymptomReport appointment_id={self.appointment_id}>"


class AISummary(Base):
    __tablename__ = "ai_summaries"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    appointment_id = Column(String(36), ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(SQLEnum(AISummaryType), nullable=False, index=True)
    status = Column(SQLEnum(AISummaryStatus), nullable=False, default=AISummaryStatus.PENDING, index=True)
    payload = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships
    appointment = relationship("Appointment", back_populates="ai_summaries")

    def __repr__(self):
        return f"<AISummary type={self.type} status={self.status}>"


class Consultation(Base):
    __tablename__ = "consultations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    appointment_id = Column(String(36), ForeignKey("appointments.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    notes = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships
    appointment = relationship("Appointment", back_populates="consultation")
    prescription = relationship("Prescription", back_populates="consultation", uselist=False, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Consultation id={self.id} appointment_id={self.appointment_id}>"


class Prescription(Base):
    __tablename__ = "prescriptions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    consultation_id = Column(String(36), ForeignKey("consultations.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    instructions = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships
    consultation = relationship("Consultation", back_populates="prescription")
    medications = relationship("Medication", back_populates="prescription", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Prescription id={self.id} consultation_id={self.consultation_id}>"


class Medication(Base):
    __tablename__ = "medications"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    prescription_id = Column(String(36), ForeignKey("prescriptions.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    dosage = Column(String(255), nullable=False)
    frequency = Column(String(255), nullable=False)
    duration_days = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships
    prescription = relationship("Prescription", back_populates="medications")

    def __repr__(self):
        return f"<Medication name={self.name} dosage={self.dosage} frequency={self.frequency}>"
