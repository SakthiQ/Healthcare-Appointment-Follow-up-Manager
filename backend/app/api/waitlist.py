from datetime import date
from typing import List

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import rate_limited_per_user, require_role
from models.user import User, UserRole
from schemas.waitlist import WaitlistEntryResponse, WaitlistJoinRequest
from services.waitlist_service import waitlist_service

router = APIRouter(tags=["Waitlist"])


@router.post("/doctors/{doctor_id}/waitlist", response_model=WaitlistEntryResponse, status_code=status.HTTP_201_CREATED)
def join_waitlist(
    doctor_id: str,
    req: WaitlistJoinRequest,
    current_user: User = Depends(rate_limited_per_user("waitlist", "WAITLIST_RATE_LIMIT_PER_HOUR",
                                                       roles=(UserRole.PATIENT,))),
    db: Session = Depends(get_db),
):
    """Wait for a slot on a fully booked future day. 409 when the day still has a free slot,
    when already waiting, or at the cap of active waitlists."""
    return waitlist_service.join(db, current_user.id, doctor_id, req.date)


@router.delete("/doctors/{doctor_id}/waitlist", status_code=status.HTTP_204_NO_CONTENT)
def leave_waitlist(
    doctor_id: str,
    day: date = Query(..., alias="date"),
    current_user: User = Depends(require_role(UserRole.PATIENT)),
    db: Session = Depends(get_db),
):
    """Leave the waitlist for that doctor and day."""
    waitlist_service.leave(db, current_user.id, doctor_id, day)


@router.get("/patients/me/waitlist", response_model=List[WaitlistEntryResponse], status_code=status.HTTP_200_OK)
def my_waitlist(current_user: User = Depends(require_role(UserRole.PATIENT)), db: Session = Depends(get_db)):
    """The signed-in patient's waitlist entries for today onwards."""
    return waitlist_service.list_mine(db, current_user.id)
