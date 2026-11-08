from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import require_role
from models.user import User, UserRole
from services.audit_service import audit_service
from services.doctor_service import doctor_service
from services.schedule_service import schedule_service
from services.leave_service import leave_service
from services.doctor_leave_service import doctor_leave_service
from schemas.audit import AuditLogPageResponse
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
)
def create_doctor(
    req: DoctorCreateRequest,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db)
):
    """Admin creates a new doctor profile with user account."""
    result = doctor_service.create_doctor(db, req)
    audit_service.record(db, "doctor.create", actor=current_user, resource_type="doctor", resource_id=result.id)
    return result


@router.put(
    "/doctors/{doctor_id}",
    response_model=DoctorResponse,
    status_code=status.HTTP_200_OK,
)
def update_doctor(
    doctor_id: str,
    req: DoctorUpdateRequest,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db)
):
    """Admin updates doctor specialization, slot duration, or active status."""
    result = doctor_service.update_doctor(db, doctor_id, req)
    audit_service.record(
        db, "doctor.update", actor=current_user, resource_type="doctor", resource_id=doctor_id,
        detail={"fields": sorted(req.model_dump(exclude_unset=True).keys())},
    )
    return result


@router.patch(
    "/doctors/{doctor_id}/status",
    response_model=DoctorResponse,
    status_code=status.HTTP_200_OK,
)
def set_doctor_status(
    doctor_id: str,
    is_active: bool = Query(...),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db)
):
    """Admin activates or deactivates a doctor profile."""
    result = doctor_service.set_active_status(db, doctor_id, is_active)
    audit_service.record(
        db, "doctor.status", actor=current_user, resource_type="doctor", resource_id=doctor_id,
        detail={"is_active": is_active},
    )
    return result


@router.post(
    "/doctors/{doctor_id}/schedule",
    response_model=List[WorkingHoursResponse],
    status_code=status.HTTP_200_OK,
)
def configure_working_hours(
    doctor_id: str,
    req: WorkingHoursConfigRequest,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db)
):
    """Admin configures doctor working hours and slot schedule."""
    result = schedule_service.configure_working_hours(db, doctor_id, req)
    audit_service.record(
        db, "doctor.schedule.update", actor=current_user, resource_type="doctor", resource_id=doctor_id,
        detail={"days": len(req.working_hours)},
    )
    return result


@router.post(
    "/doctors/{doctor_id}/leaves",
    response_model=DoctorLeaveResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_doctor_leave(
    doctor_id: str,
    req: DoctorLeaveRequest,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db)
):
    """Admin creates a leave date for a doctor. Detects and resolves any
    appointments that conflict with the new leave date (marks them
    CONFLICTED and queues patient notification jobs) in the same transaction."""
    result = doctor_leave_service.create_leave(db, doctor_id, req)
    audit_service.record(
        db, "doctor.leave.create", actor=current_user, resource_type="doctor", resource_id=doctor_id,
        detail={"leave_date": req.leave_date.isoformat()},
    )
    return result


@router.delete(
    "/doctors/{doctor_id}/leaves/{leave_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_doctor_leave(
    doctor_id: str,
    leave_id: str,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db)
):
    """Admin deletes a leave date for a doctor."""
    leave_service.delete_leave(db, doctor_id, leave_id)
    audit_service.record(
        db, "doctor.leave.delete", actor=current_user, resource_type="doctor", resource_id=doctor_id,
        detail={"leave_id": leave_id},
    )


@router.get("/audit-logs", response_model=AuditLogPageResponse, status_code=status.HTTP_200_OK)
def list_audit_logs(
    action: Optional[str] = Query(default=None, max_length=64, description='Exact action, or a prefix ending in "." or "*" (e.g. "auth.")'),
    actor_id: Optional[str] = Query(default=None, max_length=36),
    patient_id: Optional[str] = Query(default=None, max_length=36, description="Whose data was touched"),
    resource_id: Optional[str] = Query(default=None, max_length=36),
    since: Optional[datetime] = Query(default=None, description="Inclusive lower bound"),
    until: Optional[datetime] = Query(default=None, description="Exclusive upper bound"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db)
):
    """Admin reads the audit trail, newest first. Reading it is itself audited."""
    page = audit_service.search(
        db, action=action, actor_user_id=actor_id, patient_id=patient_id, resource_id=resource_id,
        since=since, until=until, limit=limit, offset=offset,
    )
    audit_service.record(
        db, "audit.view", actor=current_user,
        detail={k: v for k, v in {"action": action, "actor_id": actor_id, "patient_id": patient_id,
                                  "resource_id": resource_id}.items() if v},
    )
    return page
