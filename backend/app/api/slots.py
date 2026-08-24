from datetime import date
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user, require_role
from models.user import User, UserRole
from services.slot_service import slot_service
from services.hold_service import hold_service
from schemas.slot import SlotGenerationResponse, HoldCreateRequest, HoldResponse

router = APIRouter(tags=["Slot Engine & Holds"])


@router.get("/doctors/{doctor_id}/slots", response_model=SlotGenerationResponse, status_code=status.HTTP_200_OK)
def get_available_slots(
    doctor_id: str,
    target_date: date = Query(..., alias="date", description="Target date in YYYY-MM-DD format"),
    db: Session = Depends(get_db)
):
    """Retrieve available slots for a doctor on a given date."""
    return slot_service.generate_slots(db, doctor_id, target_date)


@router.post("/slots/holds", response_model=HoldResponse, status_code=status.HTTP_201_CREATED)
def create_slot_hold(
    req: HoldCreateRequest,
    current_user: User = Depends(require_role(UserRole.PATIENT)),
    db: Session = Depends(get_db)
):
    """Patient creates a temporary hold on a slot."""
    return hold_service.create_hold(db, patient_id=current_user.id, req=req)


@router.get("/slots/holds/{hold_id}", response_model=HoldResponse, status_code=status.HTTP_200_OK)
def get_slot_hold(
    hold_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retrieve hold details."""
    return hold_service.get_hold(db, hold_id)


@router.post("/slots/holds/{hold_id}/release", status_code=status.HTTP_204_NO_CONTENT)
def release_slot_hold(
    hold_id: str,
    current_user: User = Depends(require_role(UserRole.PATIENT)),
    db: Session = Depends(get_db)
):
    """Patient releases their temporary slot hold."""
    hold_service.release_hold(db, hold_id, patient_id=current_user.id)
