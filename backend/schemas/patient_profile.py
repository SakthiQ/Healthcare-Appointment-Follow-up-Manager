from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PatientProfileUpdate(BaseModel):
    """Every field is optional; null clears it."""
    date_of_birth: Optional[date] = None
    phone: Optional[str] = Field(default=None, max_length=32)
    allergies: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("date_of_birth")
    @classmethod
    def _not_in_the_future(cls, value: Optional[date]) -> Optional[date]:
        if value is not None and value > date.today():
            raise ValueError("Date of birth cannot be in the future.")
        return value

    @field_validator("phone", "allergies")
    @classmethod
    def _blank_means_none(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() or None if isinstance(value, str) else value


class PatientProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    date_of_birth: Optional[date] = None
    phone: Optional[str] = None
    allergies: Optional[str] = None
    updated_at: Optional[datetime] = None


class PatientHealthForDoctor(BaseModel):
    """What the appointment's doctor sees: the age, never the date of birth itself."""
    age: Optional[int] = None
    allergies: Optional[str] = None
