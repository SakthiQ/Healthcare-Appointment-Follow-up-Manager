"""A patient's own health history: completed visits with prescriptions and follow-up steps."""
from typing import List, Tuple

from sqlalchemy.orm import Session, selectinload

from models.appointment import Appointment, AppointmentStatus
from models.clinical import AISummary, AISummaryStatus, AISummaryType, Consultation, Prescription
from schemas.history import HistoryItem, HistoryMedication


class HistoryService:
    def patient_history(self, db: Session, patient_id: str, limit: int, offset: int) -> Tuple[List[HistoryItem], int]:
        """Completed appointments, newest first. A fixed number of queries per page, whatever
        its size: one count, one page, one IN query per relationship, one for summaries."""
        base = db.query(Appointment).filter(
            Appointment.patient_id == patient_id, Appointment.status == AppointmentStatus.COMPLETED
        )
        total = base.order_by(None).count()
        page = base.options(
            selectinload(Appointment.doctor),
            selectinload(Appointment.doctor_user),
            selectinload(Appointment.consultation)
            .selectinload(Consultation.prescription)
            .selectinload(Prescription.medications),
        ).order_by(Appointment.start_time.desc(), Appointment.id.desc()).offset(offset).limit(limit).all()

        follow_up = {}
        if page:
            summaries = db.query(AISummary).filter(
                AISummary.appointment_id.in_([a.id for a in page]),
                AISummary.type == AISummaryType.POST_VISIT,
                AISummary.status == AISummaryStatus.SUCCESS,
            ).order_by(AISummary.created_at.asc()).all()
            for s in summaries:  # ascending, so the newest summary per appointment wins
                follow_up[s.appointment_id] = (s.payload or {}).get("follow_up_steps")

        items = []
        for appt in page:
            prescription = appt.consultation.prescription if appt.consultation else None
            items.append(HistoryItem(
                appointment_id=appt.id,
                start_time=appt.start_time,
                doctor_name=appt.doctor_user.full_name if appt.doctor_user else None,
                doctor_specialization=appt.doctor.specialization if appt.doctor else None,
                doctor_timezone=appt.doctor.timezone if appt.doctor else None,
                medications=[HistoryMedication(name=m.name, dosage=m.dosage, frequency=m.frequency,
                                               duration_days=m.duration_days)
                             for m in (prescription.medications if prescription else [])],
                instructions=prescription.instructions if prescription else None,
                follow_up_steps=follow_up.get(appt.id),
            ))
        return items, total


history_service = HistoryService()
