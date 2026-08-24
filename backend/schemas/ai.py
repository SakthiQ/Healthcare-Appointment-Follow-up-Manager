from datetime import datetime
from typing import Optional, List, Literal, Any, Dict
from pydantic import BaseModel, ConfigDict, Field
from models.clinical import AISummaryType, AISummaryStatus


class PreVisitAIOutput(BaseModel):
    """Strict contract for pre-visit AI output, per AGENT_SPEC.md."""
    urgency: Literal["Low", "Medium", "High"]
    chief_complaint: str = Field(..., min_length=1)
    suggested_questions: List[str] = Field(..., min_length=3, max_length=3)


class PostVisitAIOutput(BaseModel):
    """Contract for post-visit AI output: patient-friendly summary,
    medication schedule, and follow-up steps."""
    summary: str = Field(..., min_length=1)
    medication_schedule: str = Field(..., min_length=1)
    follow_up_steps: str = Field(..., min_length=1)


class SymptomReportCreateRequest(BaseModel):
    symptoms: str = Field(..., min_length=3, max_length=5000)


class SymptomReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    appointment_id: str
    symptoms: str
    created_at: datetime


class AISummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    appointment_id: str
    type: AISummaryType
    status: AISummaryStatus
    payload: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    created_at: datetime


class MedicationItem(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    dosage: str = Field(..., min_length=1, max_length=255)
    frequency: str = Field(..., min_length=1, max_length=255)
    duration_days: Optional[int] = Field(default=None, ge=1)


class MedicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    dosage: str
    frequency: str
    duration_days: Optional[int]


class ConsultationCreateRequest(BaseModel):
    notes: str = Field(..., min_length=1, max_length=10000)
    prescription_instructions: Optional[str] = Field(default=None, max_length=5000)
    medications: List[MedicationItem] = Field(default_factory=list)


class ConsultationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    appointment_id: str
    notes: str
    created_at: datetime
    medications: List[MedicationResponse] = Field(default_factory=list)
