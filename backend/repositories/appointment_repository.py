from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from models.appointment import Appointment, AppointmentStatus
from app.core.datetime_utils import ensure_utc
from app.exceptions import ConflictError


class AppointmentRepository:
    def get_by_id(
        self, db: Session, appointment_id: str, with_for_update: bool = False
    ) -> Optional[Appointment]:
        query = db.query(Appointment).filter(Appointment.id == appointment_id)
        if with_for_update and db.bind and db.bind.dialect.name != "sqlite":
            query = query.with_for_update()
        return query.first()

    def get_active_overlapping(
        self,
        db: Session,
        doctor_profile_id: str,
        start_time: datetime,
        end_time: datetime,
        exclude_id: Optional[str] = None,
        with_for_update: bool = False
    ) -> List[Appointment]:
        start_time = ensure_utc(start_time)
        end_time = ensure_utc(end_time)

        query = db.query(Appointment).filter(
            Appointment.doctor_profile_id == doctor_profile_id,
            Appointment.status.in_([
                AppointmentStatus.HELD,
                AppointmentStatus.CONFIRMED,
                AppointmentStatus.RESCHEDULED
            ]),
            Appointment.start_time < end_time,
            Appointment.end_time > start_time
        )
        if exclude_id:
            query = query.filter(Appointment.id != exclude_id)
        if with_for_update and db.bind and db.bind.dialect.name != "sqlite":
            query = query.with_for_update()
        return query.all()

    def create(
        self,
        db: Session,
        patient_id: str,
        doctor_user_id: str,
        doctor_profile_id: str,
        start_time: datetime,
        end_time: datetime,
        status: AppointmentStatus = AppointmentStatus.CONFIRMED
    ) -> Appointment:
        start_time = ensure_utc(start_time)
        end_time = ensure_utc(end_time)

        appointment = Appointment(
            patient_id=patient_id,
            doctor_id=doctor_user_id,
            doctor_profile_id=doctor_profile_id,
            start_time=start_time,
            end_time=end_time,
            status=status
        )
        db.add(appointment)
        try:
            db.commit()
        except IntegrityError:
            # DB-level unique constraint (uq_doctor_profile_start_time_active)
            # is the final authority against double-booking; translate a
            # constraint violation into a domain conflict instead of a 500.
            db.rollback()
            raise ConflictError("Slot is already booked.")
        db.refresh(appointment)
        return appointment

    def update_status(self, db: Session, appointment: Appointment, new_status: AppointmentStatus) -> Appointment:
        appointment.status = new_status
        appointment.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(appointment)
        return appointment

    def update_status_no_commit(self, db: Session, appointment: Appointment, new_status: AppointmentStatus) -> Appointment:
        """Like update_status but only flushes — caller controls the transaction boundary."""
        appointment.status = new_status
        appointment.updated_at = datetime.now(timezone.utc)
        db.flush()
        return appointment

    def get_active_appointments_for_doctor_on_date(
        self,
        db: Session,
        doctor_profile_id: str,
        day_start: datetime,
        day_end: datetime,
        with_for_update: bool = False
    ) -> List[Appointment]:
        """Active (HELD/CONFIRMED/RESCHEDULED) appointments for a doctor profile
        whose start_time falls within [day_start, day_end). Used to detect
        appointments conflicting with a newly created doctor leave date."""
        day_start = ensure_utc(day_start)
        day_end = ensure_utc(day_end)

        query = db.query(Appointment).filter(
            Appointment.doctor_profile_id == doctor_profile_id,
            Appointment.start_time >= day_start,
            Appointment.start_time < day_end,
            Appointment.status.in_([
                AppointmentStatus.HELD,
                AppointmentStatus.CONFIRMED,
                AppointmentStatus.RESCHEDULED
            ])
        )
        if with_for_update and db.bind and db.bind.dialect.name != "sqlite":
            query = query.with_for_update()
        return query.all()

    def reschedule(
        self, db: Session, appointment: Appointment, new_start_time: datetime, new_end_time: datetime
    ) -> Appointment:
        appointment.start_time = ensure_utc(new_start_time)
        appointment.end_time = ensure_utc(new_end_time)
        appointment.status = AppointmentStatus.RESCHEDULED
        appointment.updated_at = datetime.now(timezone.utc)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise ConflictError("Target slot is already booked.")
        db.refresh(appointment)
        return appointment

    def list_for_patient(
        self, db: Session, patient_id: str, status_filter: Optional[AppointmentStatus] = None
    ) -> List[Appointment]:
        query = db.query(Appointment).filter(Appointment.patient_id == patient_id)
        if status_filter:
            query = query.filter(Appointment.status == status_filter)
        return query.order_by(Appointment.start_time.asc()).all()

    def list_for_doctor(
        self, db: Session, doctor_user_id: str, status_filter: Optional[AppointmentStatus] = None
    ) -> List[Appointment]:
        query = db.query(Appointment).filter(Appointment.doctor_id == doctor_user_id)
        if status_filter:
            query = query.filter(Appointment.status == status_filter)
        return query.order_by(Appointment.start_time.asc()).all()

    def list_all(
        self, db: Session, status_filter: Optional[AppointmentStatus] = None
    ) -> List[Appointment]:
        query = db.query(Appointment)
        if status_filter:
            query = query.filter(Appointment.status == status_filter)
        return query.order_by(Appointment.start_time.asc()).all()


appointment_repository = AppointmentRepository()
