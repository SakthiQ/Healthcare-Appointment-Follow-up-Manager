"""Let an admin see failed email and calendar jobs and put them back in the queue.

A job that used up its retries (NOTIFICATION_MAX_ATTEMPTS / CALENDAR_MAX_ATTEMPTS) is FAILED
for good. A retry sets it back to the state a brand-new job has, so the worker picks it up
on its next poll with nothing else to change.

Some FAILED rows must not be retried, because sending them now would be wrong:
  * a notification retired on purpose ("Superseded: ..."), such as a reminder for a time the
    appointment moved away from;
  * a password-reset, verification or invitation email: its single-use link is wiped from
    the stored job once the job finishes, so there is nothing left to send;
  * an appointment email or reminder for an appointment that has since been cancelled;
  * a calendar row with no operation left to do.
The list shows these with `retryable: false` and the reason, and retrying them returns 409.
"""
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.exceptions import ConflictError, NotFoundError
from models.appointment import Appointment, AppointmentStatus
from models.calendar import CalendarEvent, CalendarOperation, CalendarSyncStatus
from models.notification import NotificationJob, NotificationStatus, NotificationType
from schemas.admin import FailedJobKind, FailedJobResponse

_SECRET_TYPES = (
    NotificationType.PASSWORD_RESET, NotificationType.EMAIL_VERIFICATION, NotificationType.INVITATION,
)
# Emails that are still worth sending after the appointment was cancelled.
_SENT_EVEN_IF_CANCELLED = (NotificationType.CANCELLATION, NotificationType.DOCTOR_LEAVE_CONFLICT)


class JobRetryService:
    # ------------------------------------------------------------------ list
    def list_failed(
        self, db: Session, kind: FailedJobKind, limit: int, offset: int
    ) -> Tuple[List[FailedJobResponse], int]:
        if kind == FailedJobKind.NOTIFICATION:
            query = db.query(NotificationJob).filter(NotificationJob.status == NotificationStatus.FAILED)
            total = query.count()
            rows = query.order_by(NotificationJob.updated_at.desc(), NotificationJob.id).offset(offset).limit(limit).all()
            return [self._notification_item(db, r) for r in rows], total

        query = db.query(CalendarEvent).filter(CalendarEvent.status == CalendarSyncStatus.FAILED)
        total = query.count()
        rows = query.order_by(CalendarEvent.updated_at.desc(), CalendarEvent.id).offset(offset).limit(limit).all()
        return [self._calendar_item(db, r) for r in rows], total

    # ------------------------------------------------------------------ retry
    def retry_notification(self, db: Session, job_id: str) -> FailedJobResponse:
        job = db.query(NotificationJob).filter(NotificationJob.id == job_id).with_for_update().first()
        if job is None:
            raise NotFoundError("Notification job not found.")
        if job.status != NotificationStatus.FAILED:
            raise ConflictError(f"Only a FAILED job can be retried; this one is {job.status.value}.")
        reason = self._notification_blocker(db, job)
        if reason:
            raise ConflictError(reason)
        job.status = NotificationStatus.PENDING
        job.attempts = 0
        job.last_error = None
        job.next_retry_at = datetime.now(timezone.utc)
        job.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)
        return self._notification_item(db, job)

    def retry_calendar(self, db: Session, row_id: str) -> FailedJobResponse:
        row = db.query(CalendarEvent).filter(CalendarEvent.id == row_id).with_for_update().first()
        if row is None:
            raise NotFoundError("Calendar sync not found.")
        if row.status != CalendarSyncStatus.FAILED:
            raise ConflictError(f"Only a FAILED calendar sync can be retried; this one is {row.status.value}.")
        reason = self._calendar_blocker(row)
        if reason:
            raise ConflictError(reason)
        row.status = CalendarSyncStatus.PENDING_SYNC
        row.attempts = 0
        row.last_error = None
        row.next_retry_at = datetime.now(timezone.utc)
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)
        return self._calendar_item(db, row)

    # ------------------------------------------------------------------ rules
    @staticmethod
    def _notification_blocker(db: Session, job: NotificationJob) -> Optional[str]:
        if (job.last_error or "").startswith("Superseded"):
            return "This job was retired on purpose (" + job.last_error + "), so it must not be sent."
        if job.notification_type in _SECRET_TYPES:
            return ("Its single-use link was removed once the job finished. Ask the person to request "
                    "a new link (or send a new invitation) instead.")
        if job.appointment_id and job.notification_type not in _SENT_EVEN_IF_CANCELLED:
            appt = db.get(Appointment, job.appointment_id)
            if appt is not None and appt.status == AppointmentStatus.CANCELLED:
                return "The appointment has been cancelled since, so this email would be out of date."
        return None

    @staticmethod
    def _calendar_blocker(row: CalendarEvent) -> Optional[str]:
        if row.pending_operation == CalendarOperation.NONE:
            return "This calendar row has no operation left to do."
        return None

    # ------------------------------------------------------------------ shape
    def _notification_item(self, db: Session, job: NotificationJob) -> FailedJobResponse:
        blocker = self._notification_blocker(db, job) if job.status == NotificationStatus.FAILED else None
        return FailedJobResponse(
            id=job.id, kind=FailedJobKind.NOTIFICATION, type=job.notification_type.value,
            status=job.status.value, appointment_id=job.appointment_id, attempts=job.attempts,
            last_error=job.last_error, updated_at=job.updated_at,
            retryable=job.status == NotificationStatus.FAILED and blocker is None, not_retryable_reason=blocker,
        )

    def _calendar_item(self, db: Session, row: CalendarEvent) -> FailedJobResponse:
        blocker = self._calendar_blocker(row) if row.status == CalendarSyncStatus.FAILED else None
        return FailedJobResponse(
            id=row.id, kind=FailedJobKind.CALENDAR,
            type=f"{row.pending_operation.value} ({row.recipient_type})",
            status=row.status.value, appointment_id=row.appointment_id, attempts=row.attempts,
            last_error=row.last_error, updated_at=row.updated_at,
            retryable=row.status == CalendarSyncStatus.FAILED and blocker is None, not_retryable_reason=blocker,
        )


job_retry_service = JobRetryService()
