from datetime import date, time, datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator
from app.core.datetime_utils import is_valid_timezone
from schemas.auth import _password_fits_bcrypt


def _check_timezone(value: Optional[str]) -> Optional[str]:
    if value is not None and not is_valid_timezone(value):
        raise ValueError("Unknown timezone. Use an IANA name such as 'Asia/Kolkata' or 'America/New_York'.")
    return value


class DoctorCreateRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=2)
    specialization: str = Field(..., min_length=2)
    slot_duration_minutes: int = Field(default=30, ge=5, le=240)
    timezone: str = Field(default="UTC", max_length=64, description="IANA timezone the working hours are written in")
    department_id: Optional[str] = Field(default=None, max_length=36)

    _validate_timezone = field_validator("timezone")(_check_timezone)
    # Same limit as every other password field: bcrypt raises on more than 72 bytes,
    # which would otherwise surface as a 500.
    _password_fits_bcrypt = field_validator("password")(_password_fits_bcrypt)


class DoctorUpdateRequest(BaseModel):
    specialization: Optional[str] = Field(default=None, min_length=2)
    slot_duration_minutes: Optional[int] = Field(default=None, ge=5, le=240)
    is_active: Optional[bool] = None
    timezone: Optional[str] = Field(default=None, max_length=64)
    # Send null to take the doctor out of their department; leave it out to keep it.
    department_id: Optional[str] = Field(default=None, max_length=36)

    _validate_timezone = field_validator("timezone")(_check_timezone)


class DoctorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    # The doctor's account id and login email are for admins only. The public doctor
    # endpoints leave them out (None) for everyone else.
    user_id: Optional[str] = None
    email: Optional[str] = None
    full_name: str
    specialization: str
    slot_duration_minutes: int
    timezone: str = "UTC"
    is_active: bool
    created_at: datetime
    department_id: Optional[str] = None
    department_name: Optional[str] = None


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
