from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from app.core.datetime_utils import is_valid_timezone


class InvitationCreateRequest(BaseModel):
    email: EmailStr
    # Patients sign themselves up, so only staff roles can be invited.
    role: Literal["DOCTOR", "ADMIN"]
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=255, description="Pre-fills the signup form")
    # Doctor profile; required for a doctor, refused for an admin.
    specialization: Optional[str] = Field(default=None, min_length=2, max_length=255)
    slot_duration_minutes: Optional[int] = Field(default=None, ge=5, le=240)
    timezone: Optional[str] = Field(default=None, max_length=64, description="IANA timezone the working hours are in")

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not is_valid_timezone(value):
            raise ValueError("Unknown timezone. Use an IANA name such as 'Asia/Kolkata' or 'America/New_York'.")
        return value

    @model_validator(mode="after")
    def _profile_matches_role(self):
        if self.role == "DOCTOR" and not self.specialization:
            raise ValueError("A doctor invitation needs a specialization.")
        if self.role == "ADMIN" and (self.specialization or self.slot_duration_minutes or self.timezone):
            raise ValueError("Doctor details (specialization, slot duration, timezone) only apply to a doctor invitation.")
        return self


class InvitationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    role: str
    full_name: Optional[str]
    specialization: Optional[str]
    slot_duration_minutes: Optional[int]
    timezone: Optional[str]
    status: Literal["PENDING", "ACCEPTED", "REVOKED", "EXPIRED"]
    expires_at: datetime
    created_at: datetime
    invited_by: Optional[str] = None


class InvitationCreatedResponse(BaseModel):
    invitation: InvitationResponse
    # Shown once, here, so an admin can hand the link over if email is not set up. Only a hash
    # is stored, so it cannot be shown again.
    invite_link: str
    email_queued: bool


class InvitationLookupRequest(BaseModel):
    token: str = Field(..., min_length=10, max_length=200)


class InvitationLookupResponse(BaseModel):
    """What the signup page needs to show, nothing more."""
    email: str
    role: str
    full_name: Optional[str]
    expires_at: datetime
