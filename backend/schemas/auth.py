from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator
from models.user import UserRole


def _password_fits_bcrypt(value: str) -> str:
    # bcrypt only reads the first 72 bytes: older versions silently ignore the
    # rest (a longer password is weaker than it looks), newer ones raise.
    if len(value.encode("utf-8")) > 72:
        raise ValueError("Password must be at most 72 bytes (bcrypt limit).")
    return value


class UserRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, description="Minimum 6 characters")
    full_name: str = Field(..., min_length=2, description="User full name")
    role: UserRole = Field(default=UserRole.PATIENT, description="User role: PATIENT, DOCTOR, ADMIN")
    specialization: Optional[str] = Field(default=None, description="Required if role is DOCTOR")
    # From an invitation link. When present, the role and doctor profile come from the
    # invitation and the `role` and `specialization` above are ignored.
    invite_token: Optional[str] = Field(default=None, min_length=10, max_length=200)

    _password_fits_bcrypt = field_validator("password")(_password_fits_bcrypt)


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6, description="Minimum 6 characters")

    _password_fits_bcrypt = field_validator("new_password")(_password_fits_bcrypt)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=10, max_length=200)
    new_password: str = Field(..., min_length=6, description="Minimum 6 characters")

    _password_fits_bcrypt = field_validator("new_password")(_password_fits_bcrypt)


class VerifyEmailRequest(BaseModel):
    token: str = Field(..., min_length=10, max_length=200)


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class MessageResponse(BaseModel):
    message: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    email_verified: bool = True
    created_at: datetime



class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
