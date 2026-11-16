from typing import Optional, List, Tuple
from datetime import datetime, timezone
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload
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
            # populate_existing: a locked read must return the row as it is now,
            # even if this session loaded it earlier, before the lock was taken.
            query = query.with_for_update().populate_existing()
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
        status: AppointmentStatus = AppointmentStatus.CONFIRMED,
        notes: Optional[str] = None,
    ) -> Appointment:
        start_time = ensure_utc(start_time)
        end_time = ensure_utc(end_time)

        appointment = Appointment(
            patient_id=patient_id,
            doctor_id=doctor_user_id,
            doctor_profile_id=doctor_profile_id,
            start_time=start_time,
            end_time=end_time,
            status=status,
            notes=notes,
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

    def cancel(self, db: Session, appointment: Appointment, reason: Optional[str] = None) -> Appointment:
        """Mark CANCELLED and record why, in one commit."""
        appointment.cancellation_reason = reason
        return self.update_status(db, appointment, AppointmentStatus.CANCELLED)

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

    def get_active_appointments_for_doctor_from(
        self,
        db: Session,
        doctor_profile_id: str,
        from_time: datetime,
        with_for_update: bool = False
    ) -> List[Appointment]:
        """Active (HELD/CONFIRMED/RESCHEDULED) appointments for a doctor profile that
        have not started yet at `from_time`. Used when a doctor is deactivated."""
        query = db.query(Appointment).filter(
            Appointment.doctor_profile_id == doctor_profile_id,
            Appointment.start_time > ensure_utc(from_time),
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

    def list_page(
        self,
        db: Session,
        *,
        patient_id: Optional[str] = None,
        doctor_user_id: Optional[str] = None,
        doctor_any_id: Optional[str] = None,
        status_filter: Optional[AppointmentStatus] = None,
        from_time: Optional[datetime] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> Tuple[List[Appointment], int]:
        """Appointments matching the filters, earliest first, and how many match in total.

        `doctor_any_id` is for the admin filter. Everywhere else in the API "doctor_id" is
        the doctor's PROFILE id (doctors.id), so that is what an admin will pass; the
        doctor's user id is accepted too, because appointment responses call that
        "doctor_id".

        The patient, doctor user and doctor profile every response shows are loaded up
        front in three IN queries, not one query per row and relationship, so a page
        costs four queries whatever its length."""
        query = db.query(Appointment)
        if patient_id is not None:
            query = query.filter(Appointment.patient_id == patient_id)
        if doctor_user_id is not None:
            query = query.filter(Appointment.doctor_id == doctor_user_id)
        if doctor_any_id is not None:
            query = query.filter(
                or_(Appointment.doctor_profile_id == doctor_any_id, Appointment.doctor_id == doctor_any_id)
            )
        if status_filter:
            query = query.filter(Appointment.status == status_filter)
        if from_time is not None:
            query = query.filter(Appointment.start_time >= ensure_utc(from_time))

        total = query.order_by(None).count() if (limit is not None or offset) else None
        page = query.options(
            selectinload(Appointment.patient),
            selectinload(Appointment.doctor_user),
            selectinload(Appointment.doctor),
        ).order_by(Appointment.start_time.asc(), Appointment.id.asc())
        if offset:
            page = page.offset(offset)
        if limit is not None:
            page = page.limit(limit)
        items = page.all()
        return items, (total if total is not None else len(items))

    def count_by_status(self, db: Session) -> dict:
        """{status: count} over every appointment, for the admin dashboard."""
        rows = db.query(Appointment.status, func.count(Appointment.id)).group_by(Appointment.status).all()
        return {status: count for status, count in rows}


appointment_repository = AppointmentRepository()
