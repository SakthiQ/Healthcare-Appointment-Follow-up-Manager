from typing import List, Optional
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user, require_role
from models.user import User, UserRole
from models.appointment import AppointmentStatus
from services.appointment_service import appointment_service
from schemas.appointment import (
    AppointmentCreateRequest,
    AppointmentRescheduleRequest,
    AppointmentCancelRequest,
    AppointmentResponse
)

router = APIRouter(prefix="/appointments", tags=["Appointments"])


@router.post("", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED)
def create_appointment(
    req: AppointmentCreateRequest,
    current_user: User = Depends(require_role(UserRole.PATIENT)),
    db: Session = Depends(get_db)
):
    """Patient creates or confirms an appointment."""
    return appointment_service.create_appointment(db, patient_id=current_user.id, req=req)


@router.get("", response_model=List[AppointmentResponse], status_code=status.HTTP_200_OK)
def list_appointments(
    doctor_id: Optional[str] = Query(default=None, description="Filter by doctor ID (Admin only)"),
    patient_id: Optional[str] = Query(default=None, description="Filter by patient ID (Admin only)"),
    status_filter: Optional[AppointmentStatus] = Query(default=None, alias="status", description="Filter by appointment status"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List appointments for authorized user."""
    return appointment_service.list_appointments(
        db, user=current_user, doctor_id=doctor_id, patient_id=patient_id, status_filter=status_filter
    )


@router.get("/{appointment_id}", response_model=AppointmentResponse, status_code=status.HTTP_200_OK)
def get_appointment(
    appointment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retrieve details of a single appointment."""
    return appointment_service.get_appointment(db, appointment_id=appointment_id, user=current_user)


@router.post("/{appointment_id}/reschedule", response_model=AppointmentResponse, status_code=status.HTTP_200_OK)
def reschedule_appointment(
    appointment_id: str,
    req: AppointmentRescheduleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Reschedule an existing appointment to a new available slot."""
    return appointment_service.reschedule_appointment(
        db, appointment_id=appointment_id, user=current_user, req=req
    )


@router.post("/{appointment_id}/cancel", response_model=AppointmentResponse, status_code=status.HTTP_200_OK)
def cancel_appointment(
    appointment_id: str,
    req: Optional[AppointmentCancelRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Cancel an appointment."""
    return appointment_service.cancel_appointment(
        db, appointment_id=appointment_id, user=current_user, req=req
    )
