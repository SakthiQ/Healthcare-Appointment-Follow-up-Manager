from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from models.user import UserRole



class UserRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, description="Minimum 6 characters")
    full_name: str = Field(..., min_length=2, description="User full name")
    role: UserRole = Field(default=UserRole.PATIENT, description="User role: PATIENT, DOCTOR, ADMIN")
    specialization: Optional[str] = Field(default=None, description="Required if role is DOCTOR")


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
