from typing import List, Optional
from datetime import datetime, timezone
import logging
import threading
from sqlalchemy.orm import Session
from app.exceptions import NotFoundError, ConflictError, ValidationError, ForbiddenError
from app.core.datetime_utils import ensure_utc
from models.user import User, UserRole
from models.appointment import Appointment, AppointmentStatus, AppointmentHold
from models.notification import NotificationType
from repositories.appointment_repository import appointment_repository
from repositories.doctor_repository import doctor_repository
from repositories.hold_repository import hold_repository
from services.slot_service import slot_service
from services.hold_service import hold_service
from services.notification_service import notification_service
from services.reminder_service import reminder_service
from services.calendar_service import calendar_service
from schemas.appointment import (
    AppointmentCreateRequest,
    AppointmentRescheduleRequest,
    AppointmentCancelRequest,
    AppointmentResponse
)

logger = logging.getLogger(__name__)

# Application-level lock for SQLite environments (tests).
# PostgreSQL uses SELECT FOR UPDATE for row-level locking; SQLite cannot.
_booking_lock = threading.Lock()


class AppointmentService:
    def create_appointment(
        self, db: Session, patient_id: str, req: AppointmentCreateRequest
    ) -> AppointmentResponse:
        """Transactionally create/confirm an appointment. Database is the final authority."""
        # 1. Option A: Create from active Hold
        if req.hold_id:
            # Validate hold confirmation under lock/validation
            hold = hold_service.confirm_hold(db, req.hold_id, patient_id=patient_id)
            doctor_profile_id = hold.doctor_id
            start_time = ensure_utc(hold.start_time)
            end_time = ensure_utc(hold.end_time)

            doctor = doctor_repository.get_by_id(db, doctor_profile_id)
            if not doctor:
                raise NotFoundError("Doctor profile not found.")

            # Acquire the same app-level lock as the direct-booking path so
            # the hold-confirmation critical section (overlap check -> hold
            # deactivation -> appointment insert) is also serialized. The
            # uq_doctor_profile_start_time_active DB constraint remains the
            # final authority; this lock only reduces conflict churn.
            with _booking_lock:
                # Transactional overlap check under for_update
                overlapping = appointment_repository.get_active_overlapping(
                    db, doctor_profile_id, start_time, end_time, with_for_update=True
                )
                if overlapping:
                    raise ConflictError("Slot has already been booked by another user.")

                # Deactivate hold atomically
                hold_repository.deactivate(db, hold)

                # Create confirmed appointment
                appt = appointment_repository.create(
                    db=db,
                    patient_id=patient_id,
                    doctor_user_id=doctor.user_id,
                    doctor_profile_id=doctor.id,
                    start_time=start_time,
                    end_time=end_time,
                    status=AppointmentStatus.CONFIRMED
                )
            self._safe_queue_booking_notifications(db, appt)
            self._safe_sync_calendar(db, appt, "created")
            return AppointmentResponse.model_validate(appt)

        # 2. Option B: Direct slot booking
        if not req.start_time or not req.end_time:
            raise ValidationError("Either hold_id or start_time and end_time must be provided.")

        doctor_profile_id = req.doctor_id
        start_time = ensure_utc(req.start_time)
        end_time = ensure_utc(req.end_time)

        now = datetime.now(timezone.utc)
        if start_time <= now:
            raise ValidationError("Cannot book an appointment in the past.")

        doctor = doctor_repository.get_by_id(db, doctor_profile_id)
        if not doctor:
            raise NotFoundError("Doctor profile not found.")

        # Validate slot boundaries
        is_valid = slot_service.validate_slot_boundary(db, doctor_profile_id, start_time, end_time)
        if not is_valid:
            raise ValidationError("Invalid slot boundary or slot falls outside doctor working hours/leave.")

        # Check active hold
        existing_hold = hold_repository.get_active_hold_for_slot(db, doctor_profile_id, start_time, end_time)
        if existing_hold:
            raise ConflictError("Slot is currently held by another patient.")

        # Acquire app-level lock to serialize the check-then-insert critical section.
        # For PostgreSQL this is supplemented by SELECT FOR UPDATE; for SQLite (tests)
        # this is the sole concurrency guard.
        with _booking_lock:
            # Re-check overlapping inside the lock to prevent TOCTOU race
            overlapping = appointment_repository.get_active_overlapping(
                db, doctor_profile_id, start_time, end_time, with_for_update=True
            )
            if overlapping:
                raise ConflictError("Slot is already booked.")

            appt = appointment_repository.create(
                db=db,
                patient_id=patient_id,
                doctor_user_id=doctor.user_id,
                doctor_profile_id=doctor.id,
                start_time=start_time,
                end_time=end_time,
                status=AppointmentStatus.CONFIRMED
            )
        self._safe_queue_booking_notifications(db, appt)
        self._safe_sync_calendar(db, appt, "created")
        return AppointmentResponse.model_validate(appt)

    def _safe_queue_booking_notifications(self, db: Session, appt: Appointment) -> None:
        """Queue BOOKING_CONFIRMATION for patient+doctor and an
        APPOINTMENT_REMINDER for both. The appointment is already committed
        at this point — any failure here is logged and swallowed so it can
        never turn a successful booking into a failed request (requirement:
        appointment success must not depend on email/notification success)."""
        try:
            payload = {"appointment_id": appt.id, "start_time": appt.start_time.isoformat()}
            for recipient_id in (appt.patient_id, appt.doctor_id):
                notification_service.queue_notification(
                    db, appointment_id=appt.id, recipient_id=recipient_id,
                    notification_type=NotificationType.BOOKING_CONFIRMATION,
                    payload=payload,
                )
            reminder_service.schedule_appointment_reminder(db, appt)
        except Exception:
            logger.exception("Failed to queue booking notifications for appointment %s", appt.id)

    def _safe_sync_calendar(self, db: Session, appt: Appointment, operation: str) -> None:
        """Arm calendar work for an already-committed appointment. Runs strictly
        outside the appointment transaction and never calls the calendar
        provider inline — CalendarWorker does that later. Any failure here is
        logged and swallowed so calendar problems can never invalidate a
        committed appointment."""
        try:
            if operation == "created":
                calendar_service.sync_appointment_created(db, appt)
            elif operation == "rescheduled":
                calendar_service.sync_appointment_rescheduled(db, appt)
            elif operation == "cancelled":
                calendar_service.sync_appointment_cancelled(db, appt)
        except Exception:
            logger.exception("Failed to arm calendar %s sync for appointment %s", operation, appt.id)

    def _safe_queue_reschedule_notifications(self, db: Session, appt: Appointment) -> None:
        """Announce the new time to both parties and re-arm the reminder.

        Reminders already queued for the OLD time are superseded first —
        otherwise the patient is reminded about a time the appointment has
        moved away from. Best-effort, like every other post-commit side
        effect: a notification failure must not undo a committed reschedule.
        """
        try:
            notification_service.supersede_pending_notifications(
                db, appt.id, NotificationType.APPOINTMENT_REMINDER,
                reason="Superseded: appointment rescheduled.",
            )
            payload = {"appointment_id": appt.id, "start_time": appt.start_time.isoformat()}
            for recipient_id in (appt.patient_id, appt.doctor_id):
                notification_service.queue_notification(
                    db, appointment_id=appt.id, recipient_id=recipient_id,
                    notification_type=NotificationType.BOOKING_CONFIRMATION,
                    payload=payload,
                )
            reminder_service.schedule_appointment_reminder(db, appt)
        except Exception:
            logger.exception("Failed to queue reschedule notifications for appointment %s", appt.id)

    def _safe_queue_cancellation_notifications(self, db: Session, appt: Appointment) -> None:
        try:
            notification_service.supersede_pending_notifications(
                db, appt.id, NotificationType.APPOINTMENT_REMINDER,
                reason="Superseded: appointment cancelled.",
            )
            payload = {"appointment_id": appt.id, "original_start_time": appt.start_time.isoformat()}
            for recipient_id in (appt.patient_id, appt.doctor_id):
                notification_service.queue_notification(
                    db, appointment_id=appt.id, recipient_id=recipient_id,
                    notification_type=NotificationType.CANCELLATION,
                    payload=payload,
                )
        except Exception:
            logger.exception("Failed to queue cancellation notifications for appointment %s", appt.id)

    def reschedule_appointment(
        self, db: Session, appointment_id: str, user: User, req: AppointmentRescheduleRequest
    ) -> AppointmentResponse:
        appt = appointment_repository.get_by_id(db, appointment_id, with_for_update=True)
        if not appt:
            raise NotFoundError("Appointment not found.")

        # Authorization: Patient owner, Doctor owner, or Admin
        if user.role == UserRole.PATIENT and appt.patient_id != user.id:
            raise ForbiddenError("Not authorized to reschedule this appointment.")
        if user.role == UserRole.DOCTOR and appt.doctor_id != user.id:
            raise ForbiddenError("Not authorized to reschedule this appointment.")

        if appt.status == AppointmentStatus.CANCELLED:
            raise ValidationError("Cannot reschedule a cancelled appointment.")
        if appt.status == AppointmentStatus.COMPLETED:
            raise ValidationError("Cannot reschedule a completed appointment.")

        new_start_time = ensure_utc(req.new_start_time)
        new_end_time = ensure_utc(req.new_end_time)

        now = datetime.now(timezone.utc)
        if new_start_time <= now:
            raise ValidationError("Cannot reschedule to a time in the past.")

        doctor_profile_id = appt.doctor_profile_id
        if not doctor_profile_id:
            raise ValidationError("Appointment lacks doctor profile association.")

        # Validate boundary for new slot
        is_valid = slot_service.validate_slot_boundary(db, doctor_profile_id, new_start_time, new_end_time)
        if not is_valid:
            raise ValidationError("New slot boundary is invalid or falls outside working hours/leave.")

        # Check active hold for new slot
        existing_hold = hold_repository.get_active_hold_for_slot(db, doctor_profile_id, new_start_time, new_end_time)
        if existing_hold:
            raise ConflictError("Target slot is currently held by another patient.")

        # Check active overlapping appointment for new slot (excluding current appt)
        overlapping = appointment_repository.get_active_overlapping(
            db, doctor_profile_id, new_start_time, new_end_time, exclude_id=appt.id, with_for_update=True
        )
        if overlapping:
            raise ConflictError("Target slot is already booked.")

        updated_appt = appointment_repository.reschedule(
            db=db, appointment=appt, new_start_time=new_start_time, new_end_time=new_end_time
        )
        self._safe_queue_reschedule_notifications(db, updated_appt)
        self._safe_sync_calendar(db, updated_appt, "rescheduled")
        return AppointmentResponse.model_validate(updated_appt)

    def cancel_appointment(
        self, db: Session, appointment_id: str, user: User, req: Optional[AppointmentCancelRequest] = None
    ) -> AppointmentResponse:
        appt = appointment_repository.get_by_id(db, appointment_id, with_for_update=True)
        if not appt:
            raise NotFoundError("Appointment not found.")

        # Authorization check
        if user.role == UserRole.PATIENT and appt.patient_id != user.id:
            raise ForbiddenError("Not authorized to cancel this appointment.")
        if user.role == UserRole.DOCTOR and appt.doctor_id != user.id:
            raise ForbiddenError("Not authorized to cancel this appointment.")

        if appt.status == AppointmentStatus.CANCELLED:
            raise ValidationError("Appointment is already cancelled.")
        if appt.status == AppointmentStatus.COMPLETED:
            raise ValidationError("Cannot cancel a completed appointment.")

        cancelled_appt = appointment_repository.update_status(db, appt, AppointmentStatus.CANCELLED)
        self._safe_queue_cancellation_notifications(db, cancelled_appt)
        self._safe_sync_calendar(db, cancelled_appt, "cancelled")
        return AppointmentResponse.model_validate(cancelled_appt)

    def get_appointment(self, db: Session, appointment_id: str, user: User) -> AppointmentResponse:
        appt = appointment_repository.get_by_id(db, appointment_id)
        if not appt:
            raise NotFoundError("Appointment not found.")

        if user.role == UserRole.PATIENT and appt.patient_id != user.id:
            raise ForbiddenError("Not authorized to access this appointment.")
        if user.role == UserRole.DOCTOR and appt.doctor_id != user.id:
            raise ForbiddenError("Not authorized to access this appointment.")

        return AppointmentResponse.model_validate(appt)

    def list_appointments(
        self,
        db: Session,
        user: User,
        doctor_id: Optional[str] = None,
        patient_id: Optional[str] = None,
        status_filter: Optional[AppointmentStatus] = None
    ) -> List[AppointmentResponse]:
        if user.role == UserRole.PATIENT:
            appts = appointment_repository.list_for_patient(db, user.id, status_filter=status_filter)
        elif user.role == UserRole.DOCTOR:
            appts = appointment_repository.list_for_doctor(db, user.id, status_filter=status_filter)
        else: # ADMIN
            if patient_id:
                appts = appointment_repository.list_for_patient(db, patient_id, status_filter=status_filter)
            elif doctor_id:
                appts = appointment_repository.list_for_doctor(db, doctor_id, status_filter=status_filter)
            else:
                appts = appointment_repository.list_all(db, status_filter=status_filter)

        return [AppointmentResponse.model_validate(a) for a in appts]


appointment_service = AppointmentService()
