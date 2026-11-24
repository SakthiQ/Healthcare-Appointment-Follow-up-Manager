from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.exceptions import ForbiddenError, NotFoundError
from models.patient_profile import PatientProfile
from models.user import User, UserRole
from repositories.appointment_repository import appointment_repository
from schemas.patient_profile import PatientHealthForDoctor, PatientProfileResponse, PatientProfileUpdate


def age_on(born: Optional[date], today: date) -> Optional[int]:
    if born is None:
        return None
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


class PatientProfileService:
    def get_own(self, db: Session, user: User) -> PatientProfileResponse:
        profile = db.query(PatientProfile).filter(PatientProfile.user_id == user.id).first()
        return PatientProfileResponse.model_validate(profile) if profile else PatientProfileResponse()

    def update_own(self, db: Session, user: User, req: PatientProfileUpdate) -> PatientProfileResponse:
        profile = db.query(PatientProfile).filter(PatientProfile.user_id == user.id).first()
        if profile is None:
            profile = PatientProfile(user_id=user.id)
            db.add(profile)
        profile.date_of_birth = req.date_of_birth
        profile.phone = req.phone
        profile.allergies = req.allergies
        db.commit()
        db.refresh(profile)
        return PatientProfileResponse.model_validate(profile)

    def health_for_appointment(self, db: Session, appointment_id: str, user: User) -> tuple[PatientHealthForDoctor, str]:
        """Age and allergies of an appointment's patient, for that appointment's doctor or an
        admin only. Returns the patient id too, for the audit entry."""
        appt = appointment_repository.get_by_id(db, appointment_id)
        if not appt:
            raise NotFoundError("Appointment not found.")
        if user.role == UserRole.DOCTOR and appt.doctor_id != user.id:
            raise ForbiddenError("Only the doctor of this appointment can see the patient's health details.")
        if user.role not in (UserRole.DOCTOR, UserRole.ADMIN):
            raise ForbiddenError("Not authorized.")
        profile = db.query(PatientProfile).filter(PatientProfile.user_id == appt.patient_id).first()
        health = PatientHealthForDoctor(
            age=age_on(profile.date_of_birth, date.today()) if profile else None,
            allergies=profile.allergies if profile else None,
        )
        return health, appt.patient_id


patient_profile_service = PatientProfileService()
