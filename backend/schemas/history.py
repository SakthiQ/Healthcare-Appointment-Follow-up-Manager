from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class HistoryMedication(BaseModel):
    name: str
    dosage: str
    frequency: str
    duration_days: Optional[int] = None


class HistoryItem(BaseModel):
    """One completed visit in a patient's own health history."""
    appointment_id: str
    start_time: datetime
    doctor_name: Optional[str] = None
    doctor_specialization: Optional[str] = None
    doctor_timezone: Optional[str] = None
    medications: List[HistoryMedication] = []
    instructions: Optional[str] = None
    follow_up_steps: Optional[str] = None
