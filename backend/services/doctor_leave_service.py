import logging
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.datetime_utils import get_zone, local_day_bounds_utc
from app.exceptions import NotFoundError, ConflictError
from models.appointment import AppointmentStatus
from models.notification import NotificationType
from repositories.doctor_repository import doctor_repository
from repositories.appointment_repository import appointment_repository
from services.calendar_service import calendar_service
from services.notification_service import notification_service
from schemas.doctor import DoctorLeaveRequest, DoctorLeaveResponse

logger = logging.getLogger(__name__)


class DoctorLeaveService:
    """Creates a doctor leave date and, in the same transaction, detects and
    resolves any appointments that conflict with it.

    Conflict handling (see docs/system-design.md):
    1. Validate the leave (doctor exists, no duplicate leave date).
    2. Find every active (HELD/CONFIRMED/RESCHEDULED) appointment for that
       doctor whose start_time falls on the leave date.
    3. Mark each as CONFLICTED — the original appointment row (patient,
       time, history) is preserved, never deleted.
    4. Retire reminders still queued for each appointment, and queue a
       DOCTOR_LEAVE_CONFLICT notification job for each affected patient
       (delivery itself is Phase 9's notification subsystem).
    All of the above commits atomically: if any step fails, nothing is
    persisted — not the leave, not the conflict markers, not the jobs.
    """

    def create_leave(self, db: Session, doctor_id: str, req: DoctorLeaveRequest) -> DoctorLeaveResponse:
        # Lock the doctor row first (same order as booking): a booking that is
        # mid-flight finishes before we look for appointments to conflict, and one
        # that starts later waits for this commit and then sees the leave. Also
        # serialises two admins adding the same leave date.
        doctor = doctor_repository.get_by_id(db, doctor_id, with_for_update=True)
        if not doctor:
            raise NotFoundError("Doctor not found.")

        existing_leave = doctor_repository.get_leave_by_date(db, doctor_id, req.leave_date)
        if existing_leave:
            raise ConflictError(f"Doctor is already marked on leave for date {req.leave_date}")

        try:
            leave = doctor_repository.add_leave_no_commit(db, doctor_id, req.leave_date, req.reason)

            # The leave date is a calendar date in the doctor's own timezone.
            day_start, day_end = local_day_bounds_utc(req.leave_date, get_zone(doctor.timezone))

            affected_appointments = appointment_repository.get_active_appointments_for_doctor_on_date(
                db, doctor_id, day_start, day_end, with_for_update=True
            )
            affected_ids = [appointment.id for appointment in affected_appointments]

            for appointment in affected_appointments:
                original_start_time = appointment.start_time.isoformat()
                appointment_repository.update_status_no_commit(db, appointment, AppointmentStatus.CONFLICTED)
                # A confirmation that hasn't been sent yet would tell the patient
                # the appointment is confirmed right before the conflict notice.
                for obsolete_type in (NotificationType.APPOINTMENT_REMINDER, NotificationType.BOOKING_CONFIRMATION):
                    notification_service.supersede_pending_notifications_no_commit(
                        db, appointment.id, obsolete_type,
                        reason="Superseded: doctor leave conflict.",
                    )
                notification_service.queue_notification_no_commit(
                    db,
                    appointment_id=appointment.id,
                    recipient_id=appointment.patient_id,
                    notification_type=NotificationType.DOCTOR_LEAVE_CONFLICT,
                    payload={
                        "appointment_id": appointment.id,
                        "leave_date": req.leave_date.isoformat(),
                        "leave_reason": req.reason,
                        "original_start_time": original_start_time,
                    },
                )

            db.commit()
        except IntegrityError:
            # uq_doctor_leave_date: the same date was added concurrently (only
            # reachable without row locks, e.g. SQLite). A clean 409, not a 500.
            db.rollback()
            raise ConflictError(f"Doctor is already marked on leave for date {req.leave_date}")
        except Exception:
            db.rollback()
            raise

        db.refresh(leave)
        response = DoctorLeaveResponse.model_validate(leave)
        self._safe_cancel_calendar_events(db, affected_ids)
        return response

    def _safe_cancel_calendar_events(self, db: Session, appointment_ids) -> None:
        """A conflicted appointment is as good as cancelled (the patient is told to
        book again), so its calendar events must go too. Runs after the commit and
        never inside the leave transaction, like every other calendar step: a
        calendar problem is logged and swallowed, never undoing the leave."""
        for appointment_id in appointment_ids:
            try:
                appointment = appointment_repository.get_by_id(db, appointment_id)
                if appointment is not None:
                    calendar_service.sync_appointment_cancelled(db, appointment)
            except Exception:
                db.rollback()
                logger.exception("Failed to arm calendar cancellation for conflicted appointment %s", appointment_id)


doctor_leave_service = DoctorLeaveService()
