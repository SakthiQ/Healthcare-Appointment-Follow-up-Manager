from datetime import datetime, timezone, time, date, timedelta
import pytest
from sqlalchemy.exc import IntegrityError

from models.user import User, UserRole
from models.doctor import Doctor, DoctorWorkingHours, DoctorLeave
from models.appointment import Appointment, AppointmentStatus, AppointmentHold
from models.clinical import (
    SymptomReport,
    AISummary,
    AISummaryType,
    AISummaryStatus,
    Consultation,
    Prescription,
    Medication
)
from models.notification import NotificationJob, NotificationType, NotificationStatus
from models.calendar import CalendarEvent, CalendarSyncStatus


def test_user_creation_and_uniqueness(db_session):
    """Test User creation, default values, and email uniqueness constraint."""
    patient = User(
        email="patient@example.com",
        password_hash="hashed_pw_123",
        full_name="Jane Doe",
        role=UserRole.PATIENT
    )
    db_session.add(patient)
    db_session.commit()

    assert patient.id is not None
    assert patient.role == UserRole.PATIENT
    assert patient.is_active is True
    assert patient.created_at is not None

    # Test Duplicate Email Exception
    dup_patient = User(
        email="patient@example.com",
        password_hash="another_pw",
        full_name="Duplicate Jane",
        role=UserRole.PATIENT
    )
    db_session.add(dup_patient)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_doctor_profile_working_hours_and_leave(db_session):
    """Test Doctor entity, working hours, and leave relationships."""
    doc_user = User(
        email="doctor@example.com",
        password_hash="doc_hash",
        full_name="Dr. Smith",
        role=UserRole.DOCTOR
    )
    db_session.add(doc_user)
    db_session.commit()

    doctor = Doctor(
        user_id=doc_user.id,
        specialization="Cardiology",
        slot_duration_minutes=30
    )
    db_session.add(doctor)
    db_session.commit()

    # Working Hours
    wh = DoctorWorkingHours(
        doctor_id=doctor.id,
        day_of_week=0,  # Monday
        start_time=time(9, 0),
        end_time=time(17, 0)
    )
    # Leave
    leave = DoctorLeave(
        doctor_id=doctor.id,
        leave_date=date(2026, 9, 1),
        reason="Vacation"
    )
    db_session.add_all([wh, leave])
    db_session.commit()

    db_session.refresh(doctor)
    assert len(doctor.working_hours) == 1
    assert doctor.working_hours[0].start_time == time(9, 0)
    assert len(doctor.leaves) == 1
    assert doctor.leaves[0].leave_date == date(2026, 9, 1)


def test_appointment_and_hold_lifecycle(db_session):
    """Test Appointment status states and AppointmentHold persistence."""
    patient = User(email="pat1@example.com", password_hash="p", full_name="Pat One", role=UserRole.PATIENT)
    doc_user = User(email="doc1@example.com", password_hash="d", full_name="Doc One", role=UserRole.DOCTOR)
    db_session.add_all([patient, doc_user])
    db_session.commit()

    doctor = Doctor(user_id=doc_user.id, specialization="Dermatology")
    db_session.add(doctor)
    db_session.commit()

    now = datetime.now(timezone.utc)
    hold = AppointmentHold(
        doctor_id=doctor.id,
        patient_id=patient.id,
        start_time=now + timedelta(days=1),
        end_time=now + timedelta(days=1, minutes=30),
        expires_at=now + timedelta(minutes=10),
        is_active=True
    )
    db_session.add(hold)
    db_session.commit()

    assert hold.id is not None
    assert hold.is_active is True

    # Confirm Appointment
    appt = Appointment(
        patient_id=patient.id,
        doctor_id=doc_user.id,
        doctor_profile_id=doctor.id,
        start_time=hold.start_time,
        end_time=hold.end_time,
        status=AppointmentStatus.CONFIRMED
    )
    db_session.add(appt)
    db_session.commit()

    assert appt.id is not None
    assert appt.status == AppointmentStatus.CONFIRMED
    assert appt.patient.email == "pat1@example.com"
    assert appt.doctor_user.email == "doc1@example.com"


def test_appointment_double_booking_db_constraint(db_session):
    """
    Regression test: the DB must reject a second active appointment for the
    same doctor profile and start_time even when application-level locking
    is bypassed entirely (e.g. two separate processes/workers). This is the
    database-level double-booking guard (uq_doctor_profile_start_time_active).
    """
    patient1 = User(email="dbpat1@example.com", password_hash="p", full_name="DB Pat One", role=UserRole.PATIENT)
    patient2 = User(email="dbpat2@example.com", password_hash="p", full_name="DB Pat Two", role=UserRole.PATIENT)
    doc_user = User(email="dbdoc@example.com", password_hash="d", full_name="DB Doc", role=UserRole.DOCTOR)
    db_session.add_all([patient1, patient2, doc_user])
    db_session.commit()

    doctor = Doctor(user_id=doc_user.id, specialization="Oncology")
    db_session.add(doctor)
    db_session.commit()

    start_time = datetime.now(timezone.utc) + timedelta(days=2)
    end_time = start_time + timedelta(minutes=30)

    appt1 = Appointment(
        patient_id=patient1.id,
        doctor_id=doc_user.id,
        doctor_profile_id=doctor.id,
        start_time=start_time,
        end_time=end_time,
        status=AppointmentStatus.CONFIRMED
    )
    db_session.add(appt1)
    db_session.commit()

    # Second appointment for the SAME doctor profile and start_time, inserted
    # directly (bypassing AppointmentService and its application-level lock).
    appt2 = Appointment(
        patient_id=patient2.id,
        doctor_id=doc_user.id,
        doctor_profile_id=doctor.id,
        start_time=start_time,
        end_time=end_time,
        status=AppointmentStatus.CONFIRMED
    )
    db_session.add(appt2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_cancelled_appointment_does_not_block_same_slot(db_session):
    """
    A CANCELLED appointment for a slot must NOT be blocked by the DB-level
    double-booking constraint (only HELD/CONFIRMED/RESCHEDULED are "active").
    """
    patient1 = User(email="cxpat1@example.com", password_hash="p", full_name="Cx Pat One", role=UserRole.PATIENT)
    patient2 = User(email="cxpat2@example.com", password_hash="p", full_name="Cx Pat Two", role=UserRole.PATIENT)
    doc_user = User(email="cxdoc@example.com", password_hash="d", full_name="Cx Doc", role=UserRole.DOCTOR)
    db_session.add_all([patient1, patient2, doc_user])
    db_session.commit()

    doctor = Doctor(user_id=doc_user.id, specialization="Radiology")
    db_session.add(doctor)
    db_session.commit()

    start_time = datetime.now(timezone.utc) + timedelta(days=3)
    end_time = start_time + timedelta(minutes=30)

    appt1 = Appointment(
        patient_id=patient1.id,
        doctor_id=doc_user.id,
        doctor_profile_id=doctor.id,
        start_time=start_time,
        end_time=end_time,
        status=AppointmentStatus.CANCELLED
    )
    db_session.add(appt1)
    db_session.commit()

    appt2 = Appointment(
        patient_id=patient2.id,
        doctor_id=doc_user.id,
        doctor_profile_id=doctor.id,
        start_time=start_time,
        end_time=end_time,
        status=AppointmentStatus.CONFIRMED
    )
    db_session.add(appt2)
    db_session.commit()
    assert appt2.id is not None


def test_clinical_pipeline_models(db_session):
    """Test SymptomReport, AISummary, Consultation, Prescription, Medication models."""
    patient = User(email="pat2@example.com", password_hash="p", full_name="Pat Two")
    doc_user = User(email="doc2@example.com", password_hash="d", full_name="Doc Two", role=UserRole.DOCTOR)
    db_session.add_all([patient, doc_user])
    db_session.commit()

    now = datetime.now(timezone.utc)
    appt = Appointment(
        patient_id=patient.id,
        doctor_id=doc_user.id,
        start_time=now + timedelta(hours=2),
        end_time=now + timedelta(hours=2, minutes=30),
        status=AppointmentStatus.CONFIRMED
    )
    db_session.add(appt)
    db_session.commit()

    # 1. Symptom Report
    symptom = SymptomReport(appointment_id=appt.id, symptoms="Chest pain, shortness of breath")
    # 2. AI Pre-visit Summary
    ai_pre = AISummary(
        appointment_id=appt.id,
        type=AISummaryType.PRE_VISIT,
        status=AISummaryStatus.SUCCESS,
        payload={"urgency": "High", "chief_complaint": "Chest pain", "suggested_questions": ["Q1", "Q2", "Q3"]}
    )
    # 3. Consultation
    consult = Consultation(appointment_id=appt.id, notes="Patient has angina symptoms.")
    db_session.add_all([symptom, ai_pre, consult])
    db_session.commit()

    # 4. Prescription & Medication
    presc = Prescription(consultation_id=consult.id, instructions="Take after food")
    db_session.add(presc)
    db_session.commit()

    med1 = Medication(prescription_id=presc.id, name="Aspirin", dosage="100mg", frequency="Once daily", duration_days=30)
    med2 = Medication(prescription_id=presc.id, name="Atorvastatin", dosage="20mg", frequency="At bedtime", duration_days=30)
    db_session.add_all([med1, med2])
    db_session.commit()

    db_session.refresh(appt)
    assert appt.symptom_report.symptoms == "Chest pain, shortness of breath"
    assert len(appt.ai_summaries) == 1
    assert appt.ai_summaries[0].payload["urgency"] == "High"
    assert appt.consultation.notes == "Patient has angina symptoms."
    assert len(appt.consultation.prescription.medications) == 2


def test_notification_and_calendar_models(db_session):
    """Test NotificationJob and CalendarEvent persistence."""
    patient = User(email="pat3@example.com", password_hash="p", full_name="Pat Three")
    doc_user = User(email="doc3@example.com", password_hash="d", full_name="Doc Three", role=UserRole.DOCTOR)
    db_session.add_all([patient, doc_user])
    db_session.commit()

    now = datetime.now(timezone.utc)
    appt = Appointment(
        patient_id=patient.id,
        doctor_id=doc_user.id,
        start_time=now + timedelta(days=2),
        end_time=now + timedelta(days=2, minutes=30),
        status=AppointmentStatus.CONFIRMED
    )
    db_session.add(appt)
    db_session.commit()

    job = NotificationJob(
        appointment_id=appt.id,
        recipient_id=patient.id,
        notification_type=NotificationType.BOOKING_CONFIRMATION,
        status=NotificationStatus.PENDING,
        attempts=0,
        next_retry_at=now
    )

    cal_event = CalendarEvent(
        appointment_id=appt.id,
        recipient_type="PATIENT",
        external_event_id="gcal_event_123456",
        status=CalendarSyncStatus.SYNCED
    )
    db_session.add_all([job, cal_event])
    db_session.commit()

    assert job.id is not None
    assert job.status == NotificationStatus.PENDING
    assert cal_event.external_event_id == "gcal_event_123456"
    assert cal_event.status == CalendarSyncStatus.SYNCED
