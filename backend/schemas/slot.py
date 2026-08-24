from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class SlotItem(BaseModel):
    start_time: datetime
    end_time: datetime
    is_available: bool


class SlotGenerationResponse(BaseModel):
    doctor_id: str
    target_date: date
    slot_duration_minutes: int
    total_slots: int
    available_slots: int
    slots: List[SlotItem]


class HoldCreateRequest(BaseModel):
    doctor_id: str
    start_time: datetime
    end_time: datetime


class HoldResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    doctor_id: str
    patient_id: str
    start_time: datetime
    end_time: datetime
    expires_at: datetime
    is_active: bool
    created_at: datetime
