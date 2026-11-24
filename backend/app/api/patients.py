from typing import List

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_role
from models.user import User, UserRole
from schemas.history import HistoryItem
from services.audit_service import audit_service
from services.history_service import history_service

router = APIRouter(prefix="/patients", tags=["Patients"])


@router.get("/me/history", response_model=List[HistoryItem], status_code=status.HTTP_200_OK)
def my_health_history(
    response: Response,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_role(UserRole.PATIENT)),
    db: Session = Depends(get_db),
):
    """The signed-in patient's completed visits, newest first, with prescribed medications,
    instructions and follow-up steps. Patients only; each call is audited."""
    items, total = history_service.patient_history(db, current_user.id, limit=limit, offset=offset)
    response.headers["X-Total-Count"] = str(total)
    audit_service.record(db, "patient.history.view", actor=current_user, resource_type="patient",
                         resource_id=current_user.id, patient_id=current_user.id,
                         detail={"limit": limit, "offset": offset, "returned": len(items)})
    return items
