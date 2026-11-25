from typing import Optional

from pydantic import BaseModel, Field, field_validator


def _clean_name(value: Optional[str]) -> Optional[str]:
    if value is None:
        return value
    value = " ".join(value.split())
    if len(value) < 2:
        raise ValueError("Department name must be at least 2 characters.")
    return value


class DepartmentCreateRequest(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)

    _clean = field_validator("name")(_clean_name)


class DepartmentUpdateRequest(BaseModel):
    """Rename, re-describe or (de)activate. Omitted fields stay as they are."""
    name: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    is_active: Optional[bool] = None

    _clean = field_validator("name")(_clean_name)


class DepartmentResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    is_active: bool
    active_doctor_count: int = 0
