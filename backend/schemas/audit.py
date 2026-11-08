from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    occurred_at: datetime
    actor_user_id: Optional[str]
    actor_role: Optional[str]
    action: str
    resource_type: Optional[str]
    resource_id: Optional[str]
    patient_id: Optional[str]
    ip: Optional[str]
    detail: Optional[str]


class AuditLogPageResponse(BaseModel):
    items: List[AuditLogResponse]
    total: int
    limit: int
    offset: int
