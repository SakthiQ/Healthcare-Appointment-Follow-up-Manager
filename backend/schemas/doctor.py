from datetime import date, time, datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator


class DoctorCreateRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)
    full_name: str = Field(..., min_length=2)
    specialization: str = Field(..., min_length=2)
    slot_duration_minutes: int = Field(default=30, ge=5, le=240)


class DoctorUpdateRequest(BaseModel):
    specialization: Optional[str] = Field(default=None, min_length=2)
    slot_duration_minutes: Optional[int] = Field(default=None, ge=5, le=240)
    is_active: Optional[bool] = None


class DoctorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    email: str
    full_name: str
    specialization: str
    slot_duration_minutes: int
    is_active: bool
    created_at: datetime


class WorkingHoursItem(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6, description="0=Monday, 6=Sunday")
    start_time: time
    end_time: time
    is_active: bool = True

    @field_validator('end_time')
    @classmethod
    def validate_end_time_after_start(cls, end_time: time, info):
        start_time = info.data.get('start_time')
        if start_time and end_time <= start_time:
            raise ValueError("end_time must be strictly after start_time")
        return end_time


class WorkingHoursConfigRequest(BaseModel):
    working_hours: List[WorkingHoursItem]


class WorkingHoursResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    doctor_id: str
    day_of_week: int
    start_time: time
    end_time: time
    is_active: bool


class DoctorLeaveRequest(BaseModel):
    leave_date: date
    reason: Optional[str] = Field(default=None, max_length=500)


class DoctorLeaveResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    doctor_id: str
    leave_date: date
    reason: Optional[str]
    created_at: datetime
