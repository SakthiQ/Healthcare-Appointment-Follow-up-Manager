import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session

from app.config import settings
from app.core.datetime_utils import ensure_utc, get_zone
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

# Jobs whose payload carries a secret link, scrubbed from the database once finished.
_SECRET_TYPES = (NotificationType.PASSWORD_RESET, NotificationType.EMAIL_VERIFICATION)


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

    def supersede_pending_notifications_no_commit(
        self,
        db: Session,
        appointment_id: str,
        notification_type: NotificationType,
        reason: str,
    ) -> int:
        """Like supersede_pending_notifications but only flushes — for callers
        (e.g. DoctorLeaveService) that own a larger atomic transaction."""
        return notification_repository.supersede_pending_no_commit(db, appointment_id, notification_type, reason)

    # --- Processing ---
    def process_job(self, db: Session, job: NotificationJob) -> NotificationJob:
        result = self._process(db, job)
        if result.status in (NotificationStatus.SENT, NotificationStatus.FAILED):
            self._scrub_secret(db, result)
        return result

    @staticmethod
    def _scrub_secret(db: Session, job: NotificationJob) -> None:
        """Once a job is finished, drop the secret link from its stored payload so a
        password-reset or verification token does not sit in the jobs table afterwards."""
        if job.notification_type in _SECRET_TYPES and job.payload:
            job.payload = json.dumps({"redacted": True})
            db.commit()
            db.refresh(job)

    def _process(self, db: Session, job: NotificationJob) -> NotificationJob:
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
            when = self._local_when(appointment)
            return "Appointment Confirmed", f"Your appointment on {when} has been confirmed."

        if job.notification_type == NotificationType.APPOINTMENT_REMINDER:
            if not appointment:
                raise ValueError("Appointment not found for appointment reminder.")
            when = self._local_when(appointment)
            return "Appointment Reminder", f"Reminder: you have an appointment on {when}."

        if job.notification_type == NotificationType.CANCELLATION:
            when = (
                self._local_when(appointment)
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
            # Deliberately no drug name, dose or frequency: email is not a private
            # channel, and what someone takes reveals what they are being treated
            # for. The details stay in the app behind the patient's login.
            return (
                "Medication Reminder",
                "Reminder: it is time to take your prescribed medication. "
                "Sign in to the app to see your prescription and schedule."
            )

        if job.notification_type == NotificationType.PASSWORD_RESET:
            link = payload.get("link")
            if not link:
                raise ValueError("Password reset notification has no link.")
            minutes = payload.get("expires_minutes", 30)
            return (
                "Reset your password",
                "Someone (hopefully you) asked to reset the password for your account." + "\n\n"
                + f"Open this link within {minutes} minutes to choose a new one:" + "\n" + link + "\n\n"
                + "If you did not ask for this, ignore this email. Your password will not change.",
            )

        if job.notification_type == NotificationType.EMAIL_VERIFICATION:
            link = payload.get("link")
            if not link:
                raise ValueError("Email verification notification has no link.")
            hours = payload.get("expires_hours", 24)
            return (
                "Confirm your email address",
                f"Please confirm your email address by opening this link within {hours} hours:" + "\n" + link
                + "\n\nIf you did not create an account, ignore this email.",
            )

        raise ValueError(f"Unknown notification type: {job.notification_type}")

    @staticmethod
    def _local_when(appointment) -> str:
        """The appointment start in the doctor's own timezone, e.g.
        "2030-01-07 14:30 IST" ("... UTC" for a UTC doctor)."""
        zone = get_zone(appointment.doctor.timezone if appointment.doctor else None)
        local = ensure_utc(appointment.start_time).astimezone(zone)
        return f"{local:%Y-%m-%d %H:%M} {local.tzname()}"


notification_service = NotificationService()
