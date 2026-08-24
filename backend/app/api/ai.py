from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import require_role, get_current_user
from models.user import User, UserRole
from services.ai_service import ai_service
from schemas.ai import (
    SymptomReportCreateRequest,
    SymptomReportResponse,
    AISummaryResponse,
    ConsultationCreateRequest,
    ConsultationResponse,
)

router = APIRouter(prefix="/appointments/{appointment_id}", tags=["AI Summaries"])


@router.post("/symptom-report", response_model=SymptomReportResponse, status_code=status.HTTP_201_CREATED)
def submit_symptom_report(
    appointment_id: str,
    req: SymptomReportCreateRequest,
    current_user: User = Depends(require_role(UserRole.PATIENT)),
    db: Session = Depends(get_db)
):
    """Patient submits symptoms before confirming/visiting — input for the pre-visit AI summary."""
    return ai_service.submit_symptom_report(db, appointment_id, patient=current_user, symptoms=req.symptoms)


@router.post("/ai/pre-visit-summary", response_model=AISummaryResponse, status_code=status.HTTP_200_OK)
def generate_pre_visit_summary(
    appointment_id: str,
    current_user: User = Depends(require_role(UserRole.PATIENT)),
    db: Session = Depends(get_db)
):
    """Generate (or regenerate) the AI pre-visit summary from the submitted symptom report."""
    return ai_service.generate_pre_visit_summary(db, appointment_id, patient=current_user)


@router.get("/ai/pre-visit-summary", response_model=AISummaryResponse, status_code=status.HTTP_200_OK)
def get_pre_visit_summary(
    appointment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retrieve the latest pre-visit AI summary (patient, treating doctor, or admin)."""
    return ai_service.get_pre_visit_summary(db, appointment_id, user=current_user)


@router.post("/consultation", response_model=ConsultationResponse, status_code=status.HTTP_201_CREATED)
def submit_consultation(
    appointment_id: str,
    req: ConsultationCreateRequest,
    current_user: User = Depends(require_role(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """Doctor submits post-visit notes and prescription — input for the post-visit AI summary."""
    return ai_service.submit_consultation(
        db, appointment_id, doctor=current_user,
        notes=req.notes,
        prescription_instructions=req.prescription_instructions,
        medications=[m.model_dump() for m in req.medications]
    )


@router.get("/consultation", response_model=ConsultationResponse, status_code=status.HTTP_200_OK)
def get_consultation(
    appointment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retrieve the submitted consultation and prescription."""
    return ai_service.get_consultation(db, appointment_id, user=current_user)


@router.post("/ai/post-visit-summary", response_model=AISummaryResponse, status_code=status.HTTP_200_OK)
def generate_post_visit_summary(
    appointment_id: str,
    current_user: User = Depends(require_role(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """Generate (or regenerate) the AI post-visit summary from the submitted consultation notes."""
    return ai_service.generate_post_visit_summary(db, appointment_id, doctor=current_user)


@router.get("/ai/post-visit-summary", response_model=AISummaryResponse, status_code=status.HTTP_200_OK)
def get_post_visit_summary(
    appointment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retrieve the latest post-visit AI summary (patient, treating doctor, or admin)."""
    return ai_service.get_post_visit_summary(db, appointment_id, user=current_user)
