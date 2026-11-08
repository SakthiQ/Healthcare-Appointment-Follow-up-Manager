import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional, List, Sequence
from sqlalchemy.orm import Session
from pydantic import ValidationError as PydanticValidationError

from app.config import settings
from app.core.datetime_utils import ensure_utc
from app.exceptions import NotFoundError, ForbiddenError, ValidationError, ConflictError, TooManyRequestsError
from models.user import User, UserRole
from models.appointment import AppointmentStatus
from models.clinical import AISummary, AISummaryType, AISummaryStatus
from models.notification import NotificationType
from repositories.appointment_repository import appointment_repository
from repositories.clinical_repository import clinical_repository
from providers.ai_provider import AIProvider, AIProviderError, PrescribedMedication, get_ai_provider
from services.notification_service import notification_service
from services.reminder_service import reminder_service
from schemas.ai import (
    PreVisitAIOutput,
    PostVisitAIOutput,
    SymptomReportResponse,
    AISummaryResponse,
    ConsultationResponse,
    MedicationResponse,
)

logger = logging.getLogger(__name__)

# A consultation (and the medication reminders it schedules) only makes sense
# for an appointment that is actually going ahead or has taken place.
CONSULTABLE_STATUSES = {
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.RESCHEDULED,
    AppointmentStatus.COMPLETED,
}


def _authorize_appointment_participant(appointment, user: User) -> None:
    """A patient/doctor may only touch their own appointment; admin may touch any."""
    if user.role == UserRole.ADMIN:
        return
    if user.role == UserRole.PATIENT and appointment.patient_id == user.id:
        return
    if user.role == UserRole.DOCTOR and appointment.doctor_id == user.id:
        return
    raise ForbiddenError("Not authorized to access this appointment.")


def _summary_response(summary: AISummary, user: User) -> AISummaryResponse:
    """A failure's error_message is technical detail for clinic staff (it stays on
    the row either way); patients just see that the summary failed."""
    response = AISummaryResponse.model_validate(summary)
    if user.role == UserRole.PATIENT:
        response.error_message = None
    return response


def _flexible(text: str) -> str:
    """Regex source matching `text` ignoring case (via re.I) and whitespace, so "500 mg"
    matches "500mg"."""
    return r"\s*".join(re.escape(c) for c in text if not c.isspace())


def _schedule_mismatch(schedule: str, medications: Sequence[PrescribedMedication]) -> Optional[str]:
    """The prompt tells the LLM to copy each prescribed medication verbatim, but nothing
    enforces it. Reject a schedule in which any prescribed medication is absent, or is not
    followed by its own dosage, rather than show the patient a wrong one.

    A dosage only counts if it follows the medication's name and precedes the next
    prescribed name, so doses swapped between two medications fail. Digit boundaries stop
    "500mg" matching inside "1500mg", "2.5mg" or "500.5mg", and alphanumeric boundaries on
    names stop "Vitamin B1" matching inside "Vitamin B12". Case and whitespace are ignored.
    (Patterns are built from re.escape'd characters joined by `\\s*`, with no nested
    quantifiers, so doctor-entered names and doses cannot cause catastrophic backtracking.)"""
    name_res = [re.compile(r"(?<![A-Za-z0-9])" + _flexible(m.name) + r"(?![A-Za-z0-9])", re.I)
                for m in medications]
    dose_res = [re.compile(r"(?<!\d)(?<!\d[.,])" + _flexible(m.dosage) + r"(?!\d|[.,]\d)", re.I)
                for m in medications]

    occurrences = sorted(
        (match.start(), match.end(), index)
        for index, name_re in enumerate(name_res)
        for match in name_re.finditer(schedule)
    )

    mismatched = []
    for index, med in enumerate(medications):
        matched = False
        for start, end, found in occurrences:
            if found != index:
                continue
            segment_end = next((s for s, _, _ in occurrences if s >= end), len(schedule))
            if dose_res[index].search(schedule, end, segment_end):
                matched = True
                break
        if not matched:
            mismatched.append(med.name)

    if mismatched:
        return "AI medication schedule does not match the prescription (mismatched: " + ", ".join(mismatched) + ")."
    return None


class AIService:
    """Orchestrates AI summary generation. Never mutates appointment state —
    AI failure is recorded on its own AISummary row and the appointment
    workflow continues unaffected either way."""

    def __init__(self, provider: Optional[AIProvider] = None):
        self._injected_provider = provider

    def _provider(self) -> AIProvider:
        return self._injected_provider if self._injected_provider is not None else get_ai_provider()

    # --- Symptom Report (input to pre-visit AI) ---
    def submit_symptom_report(
        self, db: Session, appointment_id: str, patient: User, symptoms: str
    ) -> SymptomReportResponse:
        appointment = appointment_repository.get_by_id(db, appointment_id)
        if not appointment:
            raise NotFoundError("Appointment not found.")
        if appointment.patient_id != patient.id:
            raise ForbiddenError("Not authorized to submit symptoms for this appointment.")

        report = clinical_repository.upsert_symptom_report(db, appointment_id, symptoms)
        return SymptomReportResponse.model_validate(report)

    # --- Pre-visit AI summary ---
    def generate_pre_visit_summary(
        self, db: Session, appointment_id: str, patient: User
    ) -> AISummaryResponse:
        appointment = appointment_repository.get_by_id(db, appointment_id)
        if not appointment:
            raise NotFoundError("Appointment not found.")
        if appointment.patient_id != patient.id:
            raise ForbiddenError("Not authorized to generate a summary for this appointment.")

        report = clinical_repository.get_symptom_report(db, appointment_id)
        if not report:
            raise ValidationError("Submit a symptom report before generating a pre-visit summary.")

        # Read what the provider needs now: _run_generation ends the transaction
        # before the slow call, which expires ORM objects.
        symptoms = report.symptoms
        summary = self._run_generation(
            db=db,
            appointment_id=appointment_id,
            summary_type=AISummaryType.PRE_VISIT,
            output_model=PreVisitAIOutput,
            call=lambda provider: provider.generate_pre_visit_summary(symptoms),
        )
        return _summary_response(summary, patient)

    def get_pre_visit_summary(self, db: Session, appointment_id: str, user: User) -> AISummaryResponse:
        appointment = appointment_repository.get_by_id(db, appointment_id)
        if not appointment:
            raise NotFoundError("Appointment not found.")
        _authorize_appointment_participant(appointment, user)

        summary = clinical_repository.get_latest_ai_summary(db, appointment_id, AISummaryType.PRE_VISIT)
        if not summary:
            raise NotFoundError("No pre-visit summary has been generated for this appointment yet.")
        return _summary_response(summary, user)

    # --- Consultation + Prescription (input to post-visit AI) ---
    def submit_consultation(
        self,
        db: Session,
        appointment_id: str,
        doctor: User,
        notes: str,
        prescription_instructions: Optional[str],
        medications: List[dict],
    ) -> ConsultationResponse:
        appointment = appointment_repository.get_by_id(db, appointment_id)
        if not appointment:
            raise NotFoundError("Appointment not found.")
        if appointment.doctor_id != doctor.id:
            raise ForbiddenError("Not authorized to submit a consultation for this appointment.")
        if appointment.status not in CONSULTABLE_STATUSES:
            raise ConflictError(
                f"Cannot record a consultation for a {appointment.status.value.lower()} appointment."
            )

        early_window = settings.CONSULTATION_EARLY_SUBMIT_MINUTES
        if early_window is not None and ensure_utc(appointment.start_time) - datetime.now(timezone.utc) > timedelta(minutes=early_window):
            raise ConflictError(
                f"This appointment has not started yet. A consultation can be recorded from "
                f"{early_window} minutes before it begins."
            )

        existing = clinical_repository.get_consultation(db, appointment_id)
        if existing:
            raise ConflictError("A consultation has already been submitted for this appointment.")

        # The consultation is what marks the visit as having taken place; this
        # status change commits together with the consultation below.
        appointment_repository.update_status_no_commit(db, appointment, AppointmentStatus.COMPLETED)
        consultation = clinical_repository.create_consultation_with_prescription(
            db, appointment_id, notes, prescription_instructions, medications
        )
        patient_id = appointment.patient_id
        medication_items = consultation.prescription.medications if consultation.prescription else []
        response = ConsultationResponse(
            id=consultation.id,
            appointment_id=consultation.appointment_id,
            notes=consultation.notes,
            created_at=consultation.created_at,
            medications=[MedicationResponse.model_validate(m) for m in medication_items],
        )

        # Both steps below are best-effort — the consultation/prescription is
        # already committed and must not fail because either of them did. Rollback
        # clears the session, which a failed flush would otherwise leave unusable.
        if medication_items:
            try:
                reminder_service.schedule_medication_reminders(
                    db, appointment_id=appointment_id, patient_id=patient_id,
                    medications=medication_items
                )
            except Exception:
                db.rollback()
                logger.exception("Failed to schedule medication reminders for appointment %s", appointment_id)

        try:
            notification_service.supersede_pending_notifications(
                db, appointment_id, NotificationType.APPOINTMENT_REMINDER,
                reason="Superseded: consultation completed.",
            )
        except Exception:
            db.rollback()
            logger.exception("Failed to retire appointment reminders for appointment %s", appointment_id)

        return response

    def get_consultation(self, db: Session, appointment_id: str, user: User) -> ConsultationResponse:
        appointment = appointment_repository.get_by_id(db, appointment_id)
        if not appointment:
            raise NotFoundError("Appointment not found.")
        _authorize_appointment_participant(appointment, user)

        consultation = clinical_repository.get_consultation(db, appointment_id)
        if not consultation:
            raise NotFoundError("No consultation has been submitted for this appointment yet.")
        medication_items = consultation.prescription.medications if consultation.prescription else []
        return ConsultationResponse(
            id=consultation.id,
            appointment_id=consultation.appointment_id,
            notes=consultation.notes,
            created_at=consultation.created_at,
            medications=[MedicationResponse.model_validate(m) for m in medication_items],
        )

    # --- Post-visit AI summary ---
    def generate_post_visit_summary(
        self, db: Session, appointment_id: str, doctor: User
    ) -> AISummaryResponse:
        appointment = appointment_repository.get_by_id(db, appointment_id)
        if not appointment:
            raise NotFoundError("Appointment not found.")
        if appointment.doctor_id != doctor.id:
            raise ForbiddenError("Not authorized to generate a summary for this appointment.")

        consultation = clinical_repository.get_consultation(db, appointment_id)
        if not consultation:
            raise ValidationError("Submit a consultation before generating a post-visit summary.")

        prescription = consultation.prescription
        medications = [
            PrescribedMedication(
                name=m.name, dosage=m.dosage, frequency=m.frequency, duration_days=m.duration_days
            )
            for m in (prescription.medications if prescription else [])
        ]
        instructions = prescription.instructions if prescription else None
        notes = consultation.notes  # see generate_pre_visit_summary

        summary = self._run_generation(
            db=db,
            appointment_id=appointment_id,
            summary_type=AISummaryType.POST_VISIT,
            output_model=PostVisitAIOutput,
            call=lambda provider: provider.generate_post_visit_summary(
                notes,
                medications=medications,
                prescription_instructions=instructions,
            ),
            verify=lambda output: _schedule_mismatch(output.medication_schedule, medications),
        )
        return AISummaryResponse.model_validate(summary)

    def get_post_visit_summary(self, db: Session, appointment_id: str, user: User) -> AISummaryResponse:
        appointment = appointment_repository.get_by_id(db, appointment_id)
        if not appointment:
            raise NotFoundError("Appointment not found.")
        _authorize_appointment_participant(appointment, user)

        summary = clinical_repository.get_latest_ai_summary(db, appointment_id, AISummaryType.POST_VISIT)
        if not summary:
            raise NotFoundError("No post-visit summary has been generated for this appointment yet.")
        return _summary_response(summary, user)

    # --- Shared generation + graceful-failure pipeline ---
    def _run_generation(
        self, db: Session, appointment_id: str, summary_type: AISummaryType, output_model, call,
        verify: Optional[Callable[[Any], Optional[str]]] = None,
    ):
        """`verify`, when given, receives the schema-valid output and returns an error
        message if its content is unacceptable (recorded as FAILED), else None."""
        if clinical_repository.count_ai_summaries(db, appointment_id, summary_type) >= settings.AI_MAX_SUMMARIES_PER_APPOINTMENT:
            raise TooManyRequestsError(
                "The limit of AI summaries for this appointment has been reached. "
                "Use the existing summary or contact the clinic."
            )

        provider = self._provider()
        # End the read transaction before the slow network call. Otherwise this
        # request holds a pooled database connection for the whole LLM round trip
        # (up to the provider timeout), and a handful of slow calls would exhaust
        # the pool and stall every other request.
        db.commit()
        try:
            raw_output = call(provider)
        except AIProviderError as exc:
            return clinical_repository.create_ai_summary(
                db, appointment_id, summary_type, AISummaryStatus.FAILED,
                error_message=str(exc)
            )
        except Exception as exc:  # noqa: BLE001 - any unexpected provider failure must not break the appointment
            return clinical_repository.create_ai_summary(
                db, appointment_id, summary_type, AISummaryStatus.FAILED,
                error_message=f"Unexpected AI provider error: {exc}"
            )

        try:
            validated = output_model.model_validate(raw_output)
        except PydanticValidationError as exc:
            return clinical_repository.create_ai_summary(
                db, appointment_id, summary_type, AISummaryStatus.FAILED,
                error_message=f"Invalid AI response schema: {exc}"
            )

        problem = verify(validated) if verify else None
        if problem:
            return clinical_repository.create_ai_summary(
                db, appointment_id, summary_type, AISummaryStatus.FAILED,
                error_message=problem
            )

        return clinical_repository.create_ai_summary(
            db, appointment_id, summary_type, AISummaryStatus.SUCCESS,
            payload=validated.model_dump()
        )


ai_service = AIService()
