from datetime import datetime
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from models.audit import AuditLog


class AuditRepository:
    def query(
        self,
        db: Session,
        action: Optional[str] = None,
        actor_user_id: Optional[str] = None,
        patient_id: Optional[str] = None,
        resource_id: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[AuditLog], int]:
        """Newest first. `action` matches exactly, or as a prefix when it ends in "." or "*"
        (e.g. "auth." for every authentication event)."""
        q = db.query(AuditLog)
        if action:
            if action.endswith("*") or action.endswith("."):
                prefix = action.rstrip("*")
                q = q.filter(AuditLog.action.like(prefix.replace("%", r"\%").replace("_", r"\_") + "%", escape="\\"))
            else:
                q = q.filter(AuditLog.action == action)
        if actor_user_id:
            q = q.filter(AuditLog.actor_user_id == actor_user_id)
        if patient_id:
            q = q.filter(AuditLog.patient_id == patient_id)
        if resource_id:
            q = q.filter(AuditLog.resource_id == resource_id)
        if since:
            q = q.filter(AuditLog.occurred_at >= since)
        if until:
            q = q.filter(AuditLog.occurred_at < until)
        total = q.count()
        rows = q.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc()).offset(offset).limit(limit).all()
        return rows, total


audit_repository = AuditRepository()
