import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session

from app.config import settings
from models.appointment import Appointment
from models.calendar import CalendarEvent, CalendarOperation, CalendarSyncStatus
from repositories.calendar_repository import calendar_repository
from repositories.appointment_repository import appointment_repository
from repositories.user_repository import user_repository
from providers.calendar_provider import (
    CalendarProvider,
    CalendarProviderPermanentError,
    CalendarEventNotFoundError,
    get_calendar_provider,
)

logger = logging.getLogger(__name__)

PATIENT = "PATIENT"
DOCTOR = "DOCTOR"
_RETRY_BACKOFF_CAP_MINUTES = 60


class CalendarService:
    """Owns all calendar synchronisation.

    Two distinct halves, deliberately separated:

    * `sync_*` methods are called by AppointmentService *after* the appointment
      transaction has already committed. They only write local CalendarEvent
      rows marking work as pending — they never call the provider inline, so a
      Google outage cannot slow down or fail a booking.
    * `process_pending_row` is called by CalendarWorker and is the only place
      that talks to a CalendarProvider. Failures there are persisted on the
      CalendarEvent row (retryable or terminal); the appointment is never touched.
    """

    def __init__(self, provider: Optional[CalendarProvider] = None):
        self._injected_provider = provider

    def _provider(self) -> CalendarProvider:
        return self._injected_provider if self._injected_provider is not None else get_calendar_provider()

    # --- Queueing (called post-commit by AppointmentService) ---
    def sync_appointment_created(self, db: Session, appointment: Appointment) -> None:
        """Arm a CREATE for both the patient's and the doctor's calendar."""
        for recipient_type in (PATIENT, DOCTOR):
            calendar_repository.upsert_pending(
                db, appointment.id, recipient_type, CalendarOperation.CREATE
            )

    def sync_appointment_rescheduled(self, db: Session, appointment: Appointment) -> None:
        """Arm an UPDATE for rows that already have an external event, or a
        CREATE for any side that was never successfully created."""
        for recipient_type in (PATIENT, DOCTOR):
            existing = calendar_repository.get_for_appointment_recipient(db, appointment.id, recipient_type)
            operation = (
                CalendarOperation.UPDATE
                if existing and existing.external_event_id
                else CalendarOperation.CREATE
            )
            calendar_repository.upsert_pending(db, appointment.id, recipient_type, operation)

    def sync_appointment_cancelled(self, db: Session, appointment: Appointment) -> None:
        """Arm a DELETE for any side that has an external event. A side that
        was never created has nothing to delete — mark it settled instead of
        queueing a delete that would always 404."""
        for recipient_type in (PATIENT, DOCTOR):
            existing = calendar_repository.get_for_appointment_recipient(db, appointment.id, recipient_type)
            if existing is None:
                continue
            if not existing.external_event_id:
                calendar_repository.mark_synced(db, existing, external_event_id=None)
                continue
            calendar_repository.upsert_pending(db, appointment.id, recipient_type, CalendarOperation.DELETE)

    # --- Processing (called by CalendarWorker) ---
    def process_pending_row(self, db: Session, row: CalendarEvent) -> CalendarEvent:
        appointment = appointment_repository.get_by_id(db, row.appointment_id)
        if not appointment:
            return calendar_repository.mark_failed(db, row, "Appointment no longer exists.")

        operation = row.pending_operation
        try:
            if operation == CalendarOperation.CREATE:
                external_id = self._do_create(db, row, appointment)
                return calendar_repository.mark_synced(db, row, external_event_id=external_id)

            if operation == CalendarOperation.UPDATE:
                self._do_update(db, row, appointment)
                return calendar_repository.mark_synced(db, row, external_event_id=row.external_event_id)

            if operation == CalendarOperation.DELETE:
                self._do_delete(row)
                # Event is gone; drop the external id so a later create can't
                # accidentally target a deleted event.
                return calendar_repository.mark_synced(db, row, external_event_id=None)

            return calendar_repository.mark_synced(db, row, external_event_id=row.external_event_id)

        except CalendarProviderPermanentError as exc:
            return calendar_repository.mark_failed(db, row, str(exc))
        except Exception as exc:  # noqa: BLE001 - transient provider failure
            next_attempt_number = row.attempts + 1
            if next_attempt_number >= settings.CALENDAR_MAX_ATTEMPTS:
                return calendar_repository.mark_failed(db, row, str(exc))
            backoff_minutes = min(2 ** next_attempt_number, _RETRY_BACKOFF_CAP_MINUTES)
            next_retry_at = datetime.now(timezone.utc) + timedelta(minutes=backoff_minutes)
            return calendar_repository.mark_retryable(db, row, str(exc), next_retry_at)

    def _do_create(self, db: Session, row: CalendarEvent, appointment: Appointment) -> str:
        summary, description = self._build_content(db, appointment, row.recipient_type)
        attendee_email = self._recipient_email(db, appointment, row.recipient_type)
        # row.idempotency_key is stable for the life of the row, so a retried
        # create is recognised by the provider as the same event rather than
        # producing a duplicate.
        return self._provider().create_event(
            event_id=row.idempotency_key,
            summary=summary,
            description=description,
            start_time=appointment.start_time,
            end_time=appointment.end_time,
            attendee_email=attendee_email,
        )

    def _do_update(self, db: Session, row: CalendarEvent, appointment: Appointment) -> None:
        summary, description = self._build_content(db, appointment, row.recipient_type)
        try:
            self._provider().update_event(
                external_event_id=row.external_event_id,
                summary=summary,
                description=description,
                start_time=appointment.start_time,
                end_time=appointment.end_time,
            )
        except CalendarEventNotFoundError:
            # Reconciliation: the event vanished externally — recreate it
            # rather than leaving the appointment unrepresented on the calendar.
            logger.warning(
                "CalendarEvent %s: external event missing on update, recreating", row.id
            )
            row.external_event_id = self._do_create(db, row, appointment)

    def _do_delete(self, row: CalendarEvent) -> None:
        try:
            self._provider().delete_event(external_event_id=row.external_event_id)
        except CalendarEventNotFoundError:
            # Already gone — a repeated delete is a no-op success, not an error.
            logger.info("CalendarEvent %s: external event already absent on delete", row.id)

    def _build_content(self, db: Session, appointment: Appointment, recipient_type: str) -> tuple:
        patient = user_repository.get_by_id(db, appointment.patient_id)
        doctor_user = user_repository.get_by_id(db, appointment.doctor_id)
        patient_name = patient.full_name if patient else "Patient"
        doctor_name = doctor_user.full_name if doctor_user else "Doctor"

        if recipient_type == DOCTOR:
            return f"Appointment with {patient_name}", f"Consultation with patient {patient_name}."
        return f"Appointment with {doctor_name}", f"Consultation with {doctor_name}."

    def _recipient_email(self, db: Session, appointment: Appointment, recipient_type: str) -> Optional[str]:
        user_id = appointment.doctor_id if recipient_type == DOCTOR else appointment.patient_id
        user = user_repository.get_by_id(db, user_id)
        return user.email if user else None


calendar_service = CalendarService()
