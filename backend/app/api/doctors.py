from typing import List, Optional
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_optional_user, require_role
from app.exceptions import NotFoundError
from repositories.doctor_repository import doctor_repository
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


def _is_admin(user: Optional[User]) -> bool:
    return user is not None and user.role == UserRole.ADMIN


@router.get("", response_model=List[DoctorResponse], status_code=status.HTTP_200_OK)
def search_doctors(
    specialization: Optional[str] = Query(default=None, max_length=100, description="Filter doctors by specialization (part of it, any case)"),
    name: Optional[str] = Query(default=None, max_length=100, description="Filter doctors by name (part of it, any case)"),
    current_user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db)
):
    """Search doctors by specialization and/or name. Public: active doctors only, without the
    doctor's login email or account id. Admins get those fields, and every doctor,
    so a deactivated one can still be found and reactivated."""
    is_admin = _is_admin(current_user)
    return doctor_service.search_doctors(
        db, specialization=specialization, name=name, active_only=not is_admin, include_private=is_admin
    )


@router.get("/me", response_model=DoctorResponse, status_code=status.HTTP_200_OK)
def get_my_doctor_profile(
    current_user: User = Depends(require_role(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """The signed-in doctor's own profile, including its id, so the doctor portal can show
    their working hours and leave. Defined before /{doctor_id} so "me" is not read as an id."""
    doctor = doctor_repository.get_by_user_id(db, current_user.id)
    if doctor is None:
        raise NotFoundError("No doctor profile is linked to this account.")
    return doctor_service.get_doctor(db, doctor.id, include_private=True)


@router.get("/{doctor_id}", response_model=DoctorResponse, status_code=status.HTTP_200_OK)
def get_doctor_profile(
    doctor_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db)
):
    """Retrieve a doctor profile. The login email and account id are only included for admins."""
    return doctor_service.get_doctor(db, doctor_id, include_private=_is_admin(current_user))


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
    personal) is only shown to admins and to the doctor themself; everyone else sees the
    dates alone."""
    leaves = leave_service.get_leaves(db, doctor_id)
    if current_user is not None and current_user.role == UserRole.ADMIN:
        return leaves
    if current_user is not None and current_user.role == UserRole.DOCTOR:
        own = doctor_repository.get_by_user_id(db, current_user.id)
        if own is not None and own.id == doctor_id:
            return leaves
    return [leave.model_copy(update={"reason": None}) for leave in leaves]
