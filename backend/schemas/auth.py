from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator
from models.user import UserRole



class UserRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, description="Minimum 6 characters")
    full_name: str = Field(..., min_length=2, description="User full name")
    role: UserRole = Field(default=UserRole.PATIENT, description="User role: PATIENT, DOCTOR, ADMIN")
    specialization: Optional[str] = Field(default=None, description="Required if role is DOCTOR")

    @field_validator("password")
    @classmethod
    def _password_fits_bcrypt(cls, value: str) -> str:
        # bcrypt only reads the first 72 bytes: older versions silently ignore the
        # rest (a longer password is weaker than it looks), newer ones raise.
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 bytes (bcrypt limit).")
        return value


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime



class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
