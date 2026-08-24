from typing import List
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import require_role
from models.user import User, UserRole
from services.doctor_service import doctor_service
from services.schedule_service import schedule_service
from services.leave_service import leave_service
from services.doctor_leave_service import doctor_leave_service
from schemas.doctor import (
    DoctorCreateRequest,
    DoctorUpdateRequest,
    DoctorResponse,
    WorkingHoursConfigRequest,
    WorkingHoursResponse,
    DoctorLeaveRequest,
    DoctorLeaveResponse
)

router = APIRouter(prefix="/admin", tags=["Admin Portal"])


@router.post(
    "/doctors",
    response_model=DoctorResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.ADMIN))]
)
def create_doctor(
    req: DoctorCreateRequest,
    db: Session = Depends(get_db)
):
    """Admin creates a new doctor profile with user account."""
    return doctor_service.create_doctor(db, req)


@router.put(
    "/doctors/{doctor_id}",
    response_model=DoctorResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_role(UserRole.ADMIN))]
)
def update_doctor(
    doctor_id: str,
    req: DoctorUpdateRequest,
    db: Session = Depends(get_db)
):
    """Admin updates doctor specialization, slot duration, or active status."""
    return doctor_service.update_doctor(db, doctor_id, req)


@router.patch(
    "/doctors/{doctor_id}/status",
    response_model=DoctorResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_role(UserRole.ADMIN))]
)
def set_doctor_status(
    doctor_id: str,
    is_active: bool = Query(...),
    db: Session = Depends(get_db)
):
    """Admin activates or deactivates a doctor profile."""
    return doctor_service.set_active_status(db, doctor_id, is_active)


@router.post(
    "/doctors/{doctor_id}/schedule",
    response_model=List[WorkingHoursResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_role(UserRole.ADMIN))]
)
def configure_working_hours(
    doctor_id: str,
    req: WorkingHoursConfigRequest,
    db: Session = Depends(get_db)
):
    """Admin configures doctor working hours and slot schedule."""
    return schedule_service.configure_working_hours(db, doctor_id, req)


@router.post(
    "/doctors/{doctor_id}/leaves",
    response_model=DoctorLeaveResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.ADMIN))]
)
def create_doctor_leave(
    doctor_id: str,
    req: DoctorLeaveRequest,
    db: Session = Depends(get_db)
):
    """Admin creates a leave date for a doctor. Detects and resolves any
    appointments that conflict with the new leave date (marks them
    CONFLICTED and queues patient notification jobs) in the same transaction."""
    return doctor_leave_service.create_leave(db, doctor_id, req)


@router.delete(
    "/doctors/{doctor_id}/leaves/{leave_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.ADMIN))]
)
def delete_doctor_leave(
    doctor_id: str,
    leave_id: str,
    db: Session = Depends(get_db)
):
    """Admin deletes a leave date for a doctor."""
    leave_service.delete_leave(db, doctor_id, leave_id)
