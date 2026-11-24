from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_role
from models.user import User, UserRole
from schemas.patient_profile import PatientHealthForDoctor, PatientProfileResponse, PatientProfileUpdate
from services.audit_service import audit_service
from services.patient_profile_service import patient_profile_service

router = APIRouter(tags=["Patient health profile"])


@router.get("/patients/me/profile", response_model=PatientProfileResponse, status_code=status.HTTP_200_OK)
def get_my_profile(current_user: User = Depends(require_role(UserRole.PATIENT)), db: Session = Depends(get_db)):
    """The signed-in patient's own health details (empty if never filled in)."""
    return patient_profile_service.get_own(db, current_user)


@router.put("/patients/me/profile", response_model=PatientProfileResponse, status_code=status.HTTP_200_OK)
def update_my_profile(
    req: PatientProfileUpdate,
    current_user: User = Depends(require_role(UserRole.PATIENT)),
    db: Session = Depends(get_db),
):
    """Replace the signed-in patient's health details. Every field is optional; a date of birth
    in the future is a 422."""
    result = patient_profile_service.update_own(db, current_user, req)
    audit_service.record(db, "patient.profile.update", actor=current_user, resource_type="patient",
                         resource_id=current_user.id, patient_id=current_user.id)
    return result


@router.get("/appointments/{appointment_id}/patient-health", response_model=PatientHealthForDoctor,
            status_code=status.HTTP_200_OK)
def get_patient_health(
    appointment_id: str,
    current_user: User = Depends(require_role(UserRole.DOCTOR, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """The patient's age and allergies, for the doctor of this appointment or an admin. Another
    doctor gets 403. Every read is audited with the patient's id."""
    health, patient_id = patient_profile_service.health_for_appointment(db, appointment_id, current_user)
    audit_service.record(db, "patient.health.view", actor=current_user, resource_type="appointment",
                         resource_id=appointment_id, patient_id=patient_id)
    return health
