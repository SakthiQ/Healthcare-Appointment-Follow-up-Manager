from typing import Dict
from pydantic import BaseModel


class AdminStatsResponse(BaseModel):
    """Counts for the admin dashboard, computed in the database so the dashboard never
    has to download every appointment to show a number."""
    active_doctors: int
    appointments_total: int
    # Every AppointmentStatus value is present, with 0 where there are none.
    appointments_by_status: Dict[str, int]
