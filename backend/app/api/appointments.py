from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, Response, status, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user, require_role
from models.user import User, UserRole
from models.appointment import AppointmentStatus
from services.appointment_service import appointment_service
from services.audit_service import audit_service
from services.ics_service import build_appointment_ics
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
    response: Response,
    doctor_id: Optional[str] = Query(default=None, description="Filter by doctor profile ID, or the doctor's user ID (Admin only)"),
    patient_id: Optional[str] = Query(default=None, description="Filter by patient ID (Admin only)"),
    status_filter: Optional[AppointmentStatus] = Query(default=None, alias="status", description="Filter by appointment status"),
    from_time: Optional[datetime] = Query(default=None, alias="from", description="Only appointments starting at or after this time (ISO 8601)"),
    limit: Optional[int] = Query(default=None, ge=1, le=1000, description="Page size. Omit for every match"),
    offset: int = Query(default=0, ge=0, description="Matches to skip, for paging"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List appointments for authorized user, earliest first. With `limit`/`offset` it
    returns one page; the X-Total-Count header always carries the total that match."""
    result, total = appointment_service.list_appointments(
        db, user=current_user, doctor_id=doctor_id, patient_id=patient_id, status_filter=status_filter,
        from_time=from_time, limit=limit, offset=offset,
    )
    response.headers["X-Total-Count"] = str(total)
    if current_user.role == UserRole.ADMIN:  # an admin listing everyone's appointments is worth a trail
        audit_service.record(
            db, "appointment.list", actor=current_user, resource_type="appointment",
            patient_id=patient_id,
            detail={k: v for k, v in {"doctor_id": doctor_id, "patient_id": patient_id,
                                      "status": status_filter.value if status_filter else None}.items() if v},
        )
    return result


@router.get("/{appointment_id}", response_model=AppointmentResponse, status_code=status.HTTP_200_OK)
def get_appointment(
    appointment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retrieve details of a single appointment."""
    result = appointment_service.get_appointment(db, appointment_id=appointment_id, user=current_user)
    audit_service.record_appointment_access(db, "appointment.view", current_user, appointment_id)
    return result


@router.get("/{appointment_id}/calendar.ics", response_class=Response, status_code=status.HTTP_200_OK)
def get_appointment_calendar(
    appointment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """The appointment as an iCalendar file, for Apple Calendar, Outlook and others. Same
    access rule as GET /appointments/{id}: the patient, the doctor or an admin."""
    appt = appointment_service.get_appointment(db, appointment_id=appointment_id, user=current_user)
    audit_service.record_appointment_access(db, "appointment.calendar_download", current_user, appointment_id)
    return Response(
        content=build_appointment_ics(appt, current_user.role),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="appointment-{appointment_id}.ics"'},
    )


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
