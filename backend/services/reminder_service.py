from datetime import datetime, timedelta, timezone
from typing import List
from sqlalchemy.orm import Session

from models.appointment import Appointment
from models.clinical import Medication
from models.notification import NotificationType
from services.notification_service import notification_service

APPOINTMENT_REMINDER_LEAD_TIME = timedelta(hours=24)
MAX_MEDICATION_REMINDERS_PER_MEDICATION = 30


class ReminderService:
    """Schedules future notification jobs (appointment reminders, medication
    reminders) on top of NotificationService. These are just NotificationJob
    rows with a future next_retry_at ("scheduled_for") — NotificationWorker
    picks them up once due, same as any retried job."""

    def schedule_appointment_reminder(self, db: Session, appointment: Appointment) -> None:
        """One reminder job per participant (patient + doctor), scheduled
        APPOINTMENT_REMINDER_LEAD_TIME before the appointment start time.
        If that time has already passed (short-notice booking), the job is
        simply due immediately once queued."""
        scheduled_for = appointment.start_time - APPOINTMENT_REMINDER_LEAD_TIME
        payload = {"appointment_id": appointment.id, "start_time": appointment.start_time.isoformat()}
        for recipient_id in (appointment.patient_id, appointment.doctor_id):
            notification_service.queue_notification(
                db,
                appointment_id=appointment.id,
                recipient_id=recipient_id,
                notification_type=NotificationType.APPOINTMENT_REMINDER,
                payload=payload,
                scheduled_for=scheduled_for,
            )

    def schedule_medication_reminders(
        self, db: Session, appointment_id: str, patient_id: str, medications: List[Medication]
    ) -> None:
        """One MEDICATION_REMINDER job per medication per day of its
        prescribed duration (bounded to MAX_MEDICATION_REMINDERS_PER_MEDICATION),
        scheduled a day apart starting tomorrow.

        `frequency` (e.g. "twice daily") is free text on the Medication model
        and is carried into each job's payload for the notification content —
        this schedules one daily check-in reminder per medication rather than
        parsing frequency into exact per-dose times, which AGENT_SPEC.md does
        not require and which free-text frequency can't reliably support.
        """
        now = datetime.now(timezone.utc)
        for medication in medications:
            reminder_days = min(medication.duration_days or 1, MAX_MEDICATION_REMINDERS_PER_MEDICATION)
            for day_offset in range(1, reminder_days + 1):
                notification_service.queue_notification(
                    db,
                    appointment_id=appointment_id,
                    recipient_id=patient_id,
                    notification_type=NotificationType.MEDICATION_REMINDER,
                    payload={
                        "medication_name": medication.name,
                        "dosage": medication.dosage,
                        "frequency": medication.frequency,
                        "day": day_offset,
                    },
                    scheduled_for=now + timedelta(days=day_offset),
                )


reminder_service = ReminderService()
