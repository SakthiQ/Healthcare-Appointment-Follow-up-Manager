from typing import List, Optional
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_optional_user
from models.user import User, UserRole
from services.doctor_service import doctor_service
from services.schedule_service import schedule_service
from services.leave_service import leave_service
from schemas.doctor import (
    DoctorResponse,
    WorkingHoursResponse,
    DoctorLeaveResponse
)

router = APIRouter(prefix="/doctors", tags=["Doctors & Schedules"])


@router.get("", response_model=List[DoctorResponse], status_code=status.HTTP_200_OK)
def search_doctors(
    specialization: Optional[str] = Query(default=None, description="Filter doctors by specialization"),
    db: Session = Depends(get_db)
):
    """Search active doctors by specialization (public/patient portal)."""
    return doctor_service.search_doctors(db, specialization=specialization, active_only=True)


@router.get("/{doctor_id}", response_model=DoctorResponse, status_code=status.HTTP_200_OK)
def get_doctor_profile(
    doctor_id: str,
    db: Session = Depends(get_db)
):
    """Retrieve detailed doctor profile."""
    return doctor_service.get_doctor(db, doctor_id)


@router.get("/{doctor_id}/schedule", response_model=List[WorkingHoursResponse], status_code=status.HTTP_200_OK)
def get_doctor_schedule(
    doctor_id: str,
    db: Session = Depends(get_db)
):
    """Retrieve doctor working hours and schedule configuration."""
    return schedule_service.get_working_hours(db, doctor_id)


@router.get("/{doctor_id}/leaves", response_model=List[DoctorLeaveResponse], status_code=status.HTTP_200_OK)
def get_doctor_leaves(
    doctor_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db)
):
    """Retrieve doctor leave dates. The free-text reason (it can be medical or
    personal) is only shown to admins; everyone else sees the dates alone."""
    leaves = leave_service.get_leaves(db, doctor_id)
    if current_user is not None and current_user.role == UserRole.ADMIN:
        return leaves
    return [leave.model_copy(update={"reason": None}) for leave in leaves]
