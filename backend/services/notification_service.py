import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session

from app.config import settings
from models.notification import NotificationJob, NotificationType, NotificationStatus
from repositories.notification_repository import notification_repository
from repositories.appointment_repository import appointment_repository
from repositories.user_repository import user_repository
from providers.email_provider import (
    EmailProvider,
    EmailProviderPermanentError,
    get_email_provider,
)

logger = logging.getLogger(__name__)

# Bounded, simple exponential backoff (minutes), capped at 60.
_RETRY_BACKOFF_CAP_MINUTES = 60


class NotificationService:
    """Queues notification jobs and processes them against an EmailProvider.

    Queueing (queue_notification / queue_notification_no_commit) is called by
    other services (AppointmentService, DoctorLeaveService, ReminderService)
    and never raises for the caller to worry about beyond normal DB errors —
    appointment success never depends on this succeeding at send time.

    Processing (process_job) is called by NotificationWorker. It is the only
    place that talks to an EmailProvider, so email delivery is fully isolated
    from appointment/AI/leave business logic.
    """

    def __init__(self, provider: Optional[EmailProvider] = None):
        self._injected_provider = provider

    def _provider(self) -> EmailProvider:
        return self._injected_provider if self._injected_provider is not None else get_email_provider()

    # --- Queueing ---
    def queue_notification(
        self,
        db: Session,
        appointment_id: Optional[str],
        recipient_id: str,
        notification_type: NotificationType,
        payload: Optional[dict] = None,
        scheduled_for: Optional[datetime] = None,
    ) -> NotificationJob:
        return notification_repository.create_job(
            db, appointment_id, recipient_id, notification_type,
            payload=json.dumps(payload) if payload else None,
            scheduled_for=scheduled_for,
        )

    def queue_notification_no_commit(
        self,
        db: Session,
        appointment_id: Optional[str],
        recipient_id: str,
        notification_type: NotificationType,
        payload: Optional[dict] = None,
        scheduled_for: Optional[datetime] = None,
    ) -> NotificationJob:
        """Like queue_notification but only flushes — for callers (e.g.
        DoctorLeaveService) that own a larger atomic transaction."""
        return notification_repository.create_job_no_commit(
            db, appointment_id, recipient_id, notification_type,
            payload=json.dumps(payload) if payload else None,
            scheduled_for=scheduled_for,
        )

    def supersede_pending_notifications(
        self,
        db: Session,
        appointment_id: str,
        notification_type: NotificationType,
        reason: str,
    ) -> int:
        """Retire queued-but-unsent jobs that a later change has made obsolete
        (e.g. reminders for a time the appointment has moved away from)."""
        return notification_repository.supersede_pending(db, appointment_id, notification_type, reason)

    # --- Processing ---
    def process_job(self, db: Session, job: NotificationJob) -> NotificationJob:
        recipient = user_repository.get_by_id(db, job.recipient_id)
        if not recipient:
            return notification_repository.mark_failed_permanent(db, job, "Recipient user no longer exists.")

        try:
            subject, body = self._build_content(db, job)
        except Exception as exc:  # noqa: BLE001 - content-building failure is not retryable
            return notification_repository.mark_failed_permanent(
                db, job, f"Failed to build notification content: {exc}"
            )

        try:
            self._provider().send(to_email=recipient.email, subject=subject, body=body)
        except EmailProviderPermanentError as exc:
            return notification_repository.mark_failed_permanent(db, job, str(exc))
        except Exception as exc:  # noqa: BLE001 - transient provider failure (timeout, unavailable, etc.)
            next_attempt_number = job.attempts + 1
            if next_attempt_number >= settings.NOTIFICATION_MAX_ATTEMPTS:
                return notification_repository.mark_failed_permanent(db, job, str(exc))
            backoff_minutes = min(2 ** next_attempt_number, _RETRY_BACKOFF_CAP_MINUTES)
            next_retry_at = datetime.now(timezone.utc) + timedelta(minutes=backoff_minutes)
            return notification_repository.mark_failed_retryable(db, job, str(exc), next_retry_at)

        return notification_repository.mark_sent(db, job)

    def _build_content(self, db: Session, job: NotificationJob) -> tuple:
        payload = json.loads(job.payload) if job.payload else {}
        appointment = appointment_repository.get_by_id(db, job.appointment_id) if job.appointment_id else None

        if job.notification_type == NotificationType.BOOKING_CONFIRMATION:
            if not appointment:
                raise ValueError("Appointment not found for booking confirmation.")
            when = appointment.start_time.strftime("%Y-%m-%d %H:%M UTC")
            return "Appointment Confirmed", f"Your appointment on {when} has been confirmed."

        if job.notification_type == NotificationType.APPOINTMENT_REMINDER:
            if not appointment:
                raise ValueError("Appointment not found for appointment reminder.")
            when = appointment.start_time.strftime("%Y-%m-%d %H:%M UTC")
            return "Appointment Reminder", f"Reminder: you have an appointment on {when}."

        if job.notification_type == NotificationType.CANCELLATION:
            when = (
                appointment.start_time.strftime("%Y-%m-%d %H:%M UTC")
                if appointment else payload.get("original_start_time", "the scheduled time")
            )
            return "Appointment Cancelled", f"Your appointment on {when} has been cancelled."

        if job.notification_type == NotificationType.DOCTOR_LEAVE_CONFLICT:
            leave_date = payload.get("leave_date", "the requested date")
            original_start = payload.get("original_start_time", "the scheduled time")
            return (
                "Appointment Cancelled Due to Doctor Unavailability",
                f"Your appointment originally scheduled for {original_start} could not be kept because "
                f"the doctor is unavailable on {leave_date}. Please book a new appointment."
            )

        if job.notification_type == NotificationType.MEDICATION_REMINDER:
            med_name = payload.get("medication_name", "your medication")
            dosage = payload.get("dosage", "")
            frequency = payload.get("frequency", "")
            return (
                "Medication Reminder",
                f"Reminder: take {med_name} ({dosage}). Frequency: {frequency}."
            )

        raise ValueError(f"Unknown notification type: {job.notification_type}")


notification_service = NotificationService()
