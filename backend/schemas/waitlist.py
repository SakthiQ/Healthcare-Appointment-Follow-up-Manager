from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class WaitlistJoinRequest(BaseModel):
    date: date


class WaitlistEntryResponse(BaseModel):
    id: str
    doctor_id: str
    date: date
    created_at: datetime
    notified_at: Optional[datetime] = None
    doctor_name: Optional[str] = None
    doctor_specialization: Optional[str] = None
