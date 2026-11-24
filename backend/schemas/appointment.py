from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
from models.appointment import AppointmentStatus


def _blank_to_none(value: Optional[str]) -> Optional[str]:
    """Trim free text; an empty or all-whitespace value means "none given"."""
    if value is None:
        return None
    value = value.strip()
    return value or None


class AppointmentCreateRequest(BaseModel):
    doctor_id: str = Field(..., description="Doctor profile ID")
    hold_id: Optional[str] = Field(default=None, description="Optional active slot hold ID")
    start_time: Optional[datetime] = Field(default=None, description="Slot start time (required if hold_id is not provided)")
    end_time: Optional[datetime] = Field(default=None, description="Slot end time (required if hold_id is not provided)")
    notes: Optional[str] = Field(default=None, max_length=2000, description="Patient notes for the doctor (stored on the appointment)")

    _clean_notes = field_validator("notes")(_blank_to_none)


class AppointmentRescheduleRequest(BaseModel):
    new_start_time: datetime
    new_end_time: datetime


class AppointmentCancelRequest(BaseModel):
    cancellation_reason: Optional[str] = Field(default=None, max_length=500, description="Reason for cancellation (stored on the appointment)")

    _clean_reason = field_validator("cancellation_reason")(_blank_to_none)


class AppointmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    patient_id: str
    doctor_id: str
    doctor_profile_id: Optional[str]
    start_time: datetime
    end_time: datetime
    status: AppointmentStatus
    notes: Optional[str] = None
    cancellation_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    patient_name: Optional[str] = None
    doctor_name: Optional[str] = None
    doctor_specialization: Optional[str] = None
    doctor_timezone: Optional[str] = None
