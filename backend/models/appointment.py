import enum
import uuid
from datetime import datetime, timezone
from app.core.datetime_utils import UTCDateTime
from sqlalchemy import Column, String, Boolean, ForeignKey, Enum as SQLEnum, Index, DDL, event, func, literal_column, text
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import relationship
from app.database import Base

_ACTIVE_STATUSES_SQL = "status IN ('HELD', 'CONFIRMED', 'RESCHEDULED')"
_OVERLAP_ERROR = "appointment overlaps an existing active appointment"

# SQLite has no exclusion constraints, so the same "no two active appointments
# for one doctor may overlap" rule is enforced with triggers (tests / local dev).
# RAISE(ABORT) surfaces as an IntegrityError, exactly like the PostgreSQL
# constraint, so the repositories' IntegrityError -> 409 translation covers both.
SQLITE_NO_OVERLAP_TRIGGERS = {
    "trg_appointments_no_active_overlap_insert": f"""
CREATE TRIGGER trg_appointments_no_active_overlap_insert
BEFORE INSERT ON appointments
WHEN NEW.doctor_profile_id IS NOT NULL AND NEW.{_ACTIVE_STATUSES_SQL}
BEGIN
    SELECT RAISE(ABORT, '{_OVERLAP_ERROR}')
    WHERE EXISTS (
        SELECT 1 FROM appointments a
        WHERE a.doctor_profile_id = NEW.doctor_profile_id
          AND a.id != NEW.id
          AND a.{_ACTIVE_STATUSES_SQL}
          AND a.start_time < NEW.end_time
          AND a.end_time > NEW.start_time
    );
END""",
    "trg_appointments_no_active_overlap_update": f"""
CREATE TRIGGER trg_appointments_no_active_overlap_update
BEFORE UPDATE OF doctor_profile_id, start_time, end_time, status ON appointments
WHEN NEW.doctor_profile_id IS NOT NULL AND NEW.{_ACTIVE_STATUSES_SQL}
BEGIN
    SELECT RAISE(ABORT, '{_OVERLAP_ERROR}')
    WHERE EXISTS (
        SELECT 1 FROM appointments a
        WHERE a.doctor_profile_id = NEW.doctor_profile_id
          AND a.id != NEW.id
          AND a.{_ACTIVE_STATUSES_SQL}
          AND a.start_time < NEW.end_time
          AND a.end_time > NEW.start_time
    );
END""",
}


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
    start_time = Column(UTCDateTime(), nullable=False, index=True)
    end_time = Column(UTCDateTime(), nullable=False)
    status = Column(SQLEnum(AppointmentStatus), nullable=False, default=AppointmentStatus.CONFIRMED, index=True)
    created_at = Column(UTCDateTime(), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(UTCDateTime(), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

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
        # The unique index above only stops *identical* start times. This
        # exclusion constraint stops any two active appointments for one doctor
        # from overlapping in time, whatever their start times. Back-to-back
        # slots are fine: tstzrange is half-open, [start, end). PostgreSQL only
        # (needs the btree_gist extension); SQLite gets triggers instead.
        ExcludeConstraint(
            ("doctor_profile_id", "="),
            (func.tstzrange(literal_column("start_time"), literal_column("end_time")), "&&"),
            using="gist",
            where=text(_ACTIVE_STATUSES_SQL),
            name="ex_doctor_profile_no_overlap_active",
        ).ddl_if(dialect="postgresql"),
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
    def doctor_timezone(self):
        return self.doctor.timezone if self.doctor else None

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
    start_time = Column(UTCDateTime(), nullable=False, index=True)
    end_time = Column(UTCDateTime(), nullable=False)
    expires_at = Column(UTCDateTime(), nullable=False, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(UTCDateTime(), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        # At most one active hold per doctor slot. HoldService checks first, but
        # two requests can both pass that check; this makes the database decide,
        # so the loser gets a 409 immediately instead of a hold that can never
        # be confirmed. Stale holds are deactivated before a new one is inserted.
        Index(
            'uq_active_hold_doctor_start_time',
            'doctor_id', 'start_time',
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active IS TRUE"),
        ),
    )

    # Relationships
    doctor = relationship("Doctor", back_populates="holds")
    patient = relationship("User", back_populates="holds")

    def __repr__(self):
        return f"<AppointmentHold id={self.id} active={self.is_active} expires_at={self.expires_at}>"


# Schema-level pieces that Base.metadata.create_all() must also emit so a
# database built without Alembic (the test suite) has the same guarantees as a
# migrated one. See alembic revision a3c5d7e9f1b2 for the migrated equivalent.
event.listen(
    Appointment.__table__, "before_create",
    DDL("CREATE EXTENSION IF NOT EXISTS btree_gist").execute_if(dialect="postgresql"),
)
for _trigger_sql in SQLITE_NO_OVERLAP_TRIGGERS.values():
    event.listen(
        Appointment.__table__, "after_create",
        DDL(_trigger_sql).execute_if(dialect="sqlite"),
    )
