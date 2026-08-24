from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from app.exceptions import NotFoundError, ConflictError
from models.appointment import AppointmentStatus
from models.notification import NotificationType
from repositories.doctor_repository import doctor_repository
from repositories.appointment_repository import appointment_repository
from services.notification_service import notification_service
from schemas.doctor import DoctorLeaveRequest, DoctorLeaveResponse


class DoctorLeaveService:
    """Creates a doctor leave date and, in the same transaction, detects and
    resolves any appointments that conflict with it.

    Conflict handling (see docs/system-design.md):
    1. Validate the leave (doctor exists, no duplicate leave date).
    2. Find every active (HELD/CONFIRMED/RESCHEDULED) appointment for that
       doctor whose start_time falls on the leave date.
    3. Mark each as CONFLICTED — the original appointment row (patient,
       time, history) is preserved, never deleted.
    4. Queue a DOCTOR_LEAVE_CONFLICT notification job for each affected
       patient (delivery itself is Phase 9's notification subsystem).
    All of the above commits atomically: if any step fails, nothing is
    persisted — not the leave, not the conflict markers, not the jobs.
    """

    def create_leave(self, db: Session, doctor_id: str, req: DoctorLeaveRequest) -> DoctorLeaveResponse:
        doctor = doctor_repository.get_by_id(db, doctor_id)
        if not doctor:
            raise NotFoundError("Doctor not found.")

        existing_leave = doctor_repository.get_leave_by_date(db, doctor_id, req.leave_date)
        if existing_leave:
            raise ConflictError(f"Doctor is already marked on leave for date {req.leave_date}")

        try:
            leave = doctor_repository.add_leave_no_commit(db, doctor_id, req.leave_date, req.reason)

            day_start = datetime.combine(req.leave_date, datetime.min.time(), tzinfo=timezone.utc)
            day_end = day_start + timedelta(days=1)

            affected_appointments = appointment_repository.get_active_appointments_for_doctor_on_date(
                db, doctor_id, day_start, day_end, with_for_update=True
            )

            for appointment in affected_appointments:
                original_start_time = appointment.start_time.isoformat()
                appointment_repository.update_status_no_commit(db, appointment, AppointmentStatus.CONFLICTED)
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
        except Exception:
            db.rollback()
            raise

        db.refresh(leave)
        return DoctorLeaveResponse.model_validate(leave)


doctor_leave_service = DoctorLeaveService()
