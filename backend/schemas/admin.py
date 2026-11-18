from datetime import datetime
from enum import Enum
from typing import Dict, Optional

from pydantic import BaseModel


class AdminStatsResponse(BaseModel):
    """Counts for the admin dashboard, computed in the database so the dashboard never
    has to download every appointment to show a number."""
    active_doctors: int
    appointments_total: int
    # Every AppointmentStatus value is present, with 0 where there are none.
    appointments_by_status: Dict[str, int]


class FailedJobKind(str, Enum):
    NOTIFICATION = "notification"
    CALENDAR = "calendar"


class FailedJobResponse(BaseModel):
    """A failed email or calendar job, as the admin sees it. `type` is the notification type,
    or the calendar operation and whose calendar it is."""
    id: str
    kind: FailedJobKind
    type: str
    status: str
    appointment_id: Optional[str] = None
    attempts: int
    last_error: Optional[str] = None
    updated_at: datetime
    retryable: bool
    not_retryable_reason: Optional[str] = None
