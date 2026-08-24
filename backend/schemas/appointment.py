from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field
from models.appointment import AppointmentStatus


class AppointmentCreateRequest(BaseModel):
    doctor_id: str = Field(..., description="Doctor profile ID")
    hold_id: Optional[str] = Field(default=None, description="Optional active slot hold ID")
    start_time: Optional[datetime] = Field(default=None, description="Slot start time (required if hold_id is not provided)")
    end_time: Optional[datetime] = Field(default=None, description="Slot end time (required if hold_id is not provided)")
    notes: Optional[str] = Field(default=None, description="Patient notes or symptom summary")


class AppointmentRescheduleRequest(BaseModel):
    new_start_time: datetime
    new_end_time: datetime


class AppointmentCancelRequest(BaseModel):
    cancellation_reason: Optional[str] = Field(default=None, description="Reason for cancellation")


class AppointmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    patient_id: str
    doctor_id: str
    doctor_profile_id: Optional[str]
    start_time: datetime
    end_time: datetime
    status: AppointmentStatus
    created_at: datetime
    updated_at: datetime
