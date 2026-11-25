import logging
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy.orm import Session
from app.core.security import hash_password
from app.exceptions import NotFoundError, ConflictError
from repositories.appointment_repository import appointment_repository
from repositories.user_repository import user_repository
from repositories.doctor_repository import doctor_repository
from schemas.doctor import DoctorCreateRequest, DoctorUpdateRequest, DoctorResponse
from services.calendar_service import calendar_service
from services.notification_service import notification_service
from models.appointment import AppointmentStatus
from models.notification import NotificationType
from models.user import UserRole
from models.doctor import Doctor
from services.department_service import department_service

logger = logging.getLogger(__name__)


class DoctorService:
    def _to_response(self, doctor: Doctor, include_private: bool = True) -> DoctorResponse:
        """`include_private=False` leaves out the doctor's login email and account id,
        which only admins should see (the doctor endpoints are public)."""
        return DoctorResponse(
            id=doctor.id,
            user_id=doctor.user_id if include_private else None,
            email=doctor.user.email if include_private else None,
            full_name=doctor.user.full_name,
            specialization=doctor.specialization,
            slot_duration_minutes=doctor.slot_duration_minutes,
            timezone=doctor.timezone or "UTC",
            is_active=doctor.is_active,
            created_at=doctor.created_at,
            department_id=doctor.department_id,
            department_name=doctor.department.name if doctor.department else None,
        )

    def create_doctor(self, db: Session, req: DoctorCreateRequest) -> DoctorResponse:
        existing = user_repository.get_by_email(db, req.email)
        if existing:
            raise ConflictError("A user with this email already exists.")
        department_service.check_assignable(db, req.department_id)

        hashed_pw = hash_password(req.password)
        user = user_repository.create(
            db=db,
            email=req.email,
            password_hash=hashed_pw,
            full_name=req.full_name,
            role=UserRole.DOCTOR,
            email_verified=True,  # the admin vouches for the address
        )

        doctor = doctor_repository.create_doctor(
            db=db,
            user_id=user.id,
            specialization=req.specialization,
            slot_duration=req.slot_duration_minutes,
            timezone=req.timezone,
        )
        if req.department_id:
            doctor.department_id = req.department_id
            db.commit()
            db.refresh(doctor)

        return self._to_response(doctor)

    def update_doctor(self, db: Session, doctor_id: str, req: DoctorUpdateRequest) -> DoctorResponse:
        changing_status = req.is_active is not None
        # A status change takes the doctor row lock first, like booking and leave creation.
        doctor = doctor_repository.get_by_id(db, doctor_id, with_for_update=changing_status)
        if not doctor:
            raise NotFoundError("Doctor not found.")
        changing_department = "department_id" in req.model_fields_set
        if changing_department:
            department_service.check_assignable(db, req.department_id)

        try:
            conflicted_ids = (
                self._apply_active_status_no_commit(db, doctor, req.is_active) if changing_status else []
            )
            if changing_department:
                doctor.department_id = req.department_id
            # Commits the status change (and everything it touched) with the other fields.
            updated_doctor = doctor_repository.update_doctor(
                db=db,
                doctor=doctor,
                specialization=req.specialization,
                slot_duration=req.slot_duration_minutes,
                timezone=req.timezone,
            )
        except Exception:
            db.rollback()
            raise
        response = self._to_response(updated_doctor)
        self._cancel_calendar_events_safely(db, conflicted_ids)
        return response

    def set_active_status(self, db: Session, doctor_id: str, is_active: bool) -> DoctorResponse:
        doctor = doctor_repository.get_by_id(db, doctor_id, with_for_update=True)
        if not doctor:
            raise NotFoundError("Doctor not found.")

        try:
            conflicted_ids = self._apply_active_status_no_commit(db, doctor, is_active)
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(doctor)
        response = self._to_response(doctor)
        self._cancel_calendar_events_safely(db, conflicted_ids)
        return response

    def _apply_active_status_no_commit(self, db: Session, doctor: Doctor, is_active: bool) -> List[str]:
        """Activate or deactivate a doctor. The caller commits, so all of it happens or none.

        Deactivating is more than hiding the doctor from search:
        * the doctor's account can no longer sign in, and its open sessions end;
        * every appointment that has not started yet is marked CONFLICTED and the patient
          is told to book again, exactly as when a leave date lands on an appointment.
          Otherwise patients would keep a confirmed appointment nobody will attend.
        Reactivating restores sign-in. Conflicted appointments stay conflicted (the
        patients have already been told), as they do when a leave date is removed.

        Returns the ids of the appointments it conflicted, for the calendar clean-up.
        """
        doctor.is_active = is_active
        user = doctor.user
        if user is not None:
            user.is_active = is_active
        if is_active:
            return []

        if user is not None:
            user.token_version = (user.token_version or 0) + 1

        upcoming = appointment_repository.get_active_appointments_for_doctor_from(
            db, doctor.id, datetime.now(timezone.utc), with_for_update=True
        )
        conflicted_ids = [appointment.id for appointment in upcoming]
        for appointment in upcoming:
            original_start_time = appointment.start_time.isoformat()
            appointment_repository.update_status_no_commit(db, appointment, AppointmentStatus.CONFLICTED)
            for obsolete_type in (NotificationType.APPOINTMENT_REMINDER, NotificationType.BOOKING_CONFIRMATION):
                notification_service.supersede_pending_notifications_no_commit(
                    db, appointment.id, obsolete_type,
                    reason="Superseded: doctor deactivated.",
                )
            notification_service.queue_notification_no_commit(
                db,
                appointment_id=appointment.id,
                recipient_id=appointment.patient_id,
                notification_type=NotificationType.DOCTOR_LEAVE_CONFLICT,
                payload={
                    "appointment_id": appointment.id,
                    "reason": "doctor_deactivated",
                    "original_start_time": original_start_time,
                },
            )
        return conflicted_ids

    def _cancel_calendar_events_safely(self, db: Session, appointment_ids: List[str]) -> None:
        """Runs after the commit, like every other calendar step: a calendar problem is
        logged and swallowed, never undoing the status change."""
        for appointment_id in appointment_ids:
            try:
                appointment = appointment_repository.get_by_id(db, appointment_id)
                if appointment is not None:
                    calendar_service.sync_appointment_cancelled(db, appointment)
            except Exception:
                db.rollback()
                logger.exception("Failed to arm calendar cancellation for conflicted appointment %s", appointment_id)

    def get_doctor(self, db: Session, doctor_id: str, include_private: bool = False) -> DoctorResponse:
        doctor = doctor_repository.get_by_id(db, doctor_id)
        if not doctor:
            raise NotFoundError("Doctor not found.")
        return self._to_response(doctor, include_private=include_private)

    def search_doctors(
        self, db: Session, specialization: Optional[str] = None, active_only: bool = True,
        include_private: bool = False, name: Optional[str] = None, department_id: Optional[str] = None,
    ) -> List[DoctorResponse]:
        doctors = doctor_repository.search(db, specialization=specialization, active_only=active_only, name=name,
                                           department_id=department_id)
        return [self._to_response(d, include_private=include_private) for d in doctors]


doctor_service = DoctorService()
