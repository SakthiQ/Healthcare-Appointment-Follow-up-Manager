from typing import Optional, List
from sqlalchemy.orm import Session
from models.clinical import (
    SymptomReport,
    AISummary,
    AISummaryType,
    AISummaryStatus,
    Consultation,
    Prescription,
    Medication,
)


class ClinicalRepository:
    # --- Symptom Reports ---
    def get_symptom_report(self, db: Session, appointment_id: str) -> Optional[SymptomReport]:
        return db.query(SymptomReport).filter(SymptomReport.appointment_id == appointment_id).first()

    def upsert_symptom_report(self, db: Session, appointment_id: str, symptoms: str) -> SymptomReport:
        report = self.get_symptom_report(db, appointment_id)
        if report:
            report.symptoms = symptoms
        else:
            report = SymptomReport(appointment_id=appointment_id, symptoms=symptoms)
            db.add(report)
        db.commit()
        db.refresh(report)
        return report

    # --- AI Summaries ---
    def create_ai_summary(
        self,
        db: Session,
        appointment_id: str,
        summary_type: AISummaryType,
        status: AISummaryStatus,
        payload: Optional[dict] = None,
        error_message: Optional[str] = None,
    ) -> AISummary:
        summary = AISummary(
            appointment_id=appointment_id,
            type=summary_type,
            status=status,
            payload=payload,
            error_message=error_message,
        )
        db.add(summary)
        db.commit()
        db.refresh(summary)
        return summary

    def get_latest_ai_summary(
        self, db: Session, appointment_id: str, summary_type: AISummaryType
    ) -> Optional[AISummary]:
        return (
            db.query(AISummary)
            .filter(AISummary.appointment_id == appointment_id, AISummary.type == summary_type)
            .order_by(AISummary.created_at.desc())
            .first()
        )

    # --- Consultations / Prescriptions / Medications ---
    def get_consultation(self, db: Session, appointment_id: str) -> Optional[Consultation]:
        return db.query(Consultation).filter(Consultation.appointment_id == appointment_id).first()

    def create_consultation_with_prescription(
        self,
        db: Session,
        appointment_id: str,
        notes: str,
        prescription_instructions: Optional[str],
        medications: List[dict],
    ) -> Consultation:
        consultation = Consultation(appointment_id=appointment_id, notes=notes)
        db.add(consultation)
        db.flush()  # assign consultation.id without committing yet

        prescription = Prescription(consultation_id=consultation.id, instructions=prescription_instructions)
        db.add(prescription)
        db.flush()

        for med in medications:
            db.add(Medication(
                prescription_id=prescription.id,
                name=med["name"],
                dosage=med["dosage"],
                frequency=med["frequency"],
                duration_days=med.get("duration_days"),
            ))

        db.commit()
        db.refresh(consultation)
        return consultation


clinical_repository = ClinicalRepository()
