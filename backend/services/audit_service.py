import json
import logging
from datetime import datetime
from typing import Any, Optional
from sqlalchemy.orm import Session
from app.core.request_context import current_client_ip
from models.audit import AuditLog
from repositories.appointment_repository import appointment_repository
from repositories.audit_repository import audit_repository
from schemas.audit import AuditLogPageResponse, AuditLogResponse

logger = logging.getLogger(__name__)


def _role_value(actor: Any) -> Optional[str]:
    role = getattr(actor, "role", None)
    if role is None:
        return None
    return role.value if hasattr(role, "value") else str(role)


class AuditService:
    """Writes the audit trail and reads it back.

    record() is best-effort: if the write fails it logs at ERROR level and the request
    carries on, so an audit-table problem cannot take patient care offline. Run it AFTER
    the action it describes has succeeded. It writes through its own session on the same
    database, so it never commits or rolls back the caller's half-finished work.
    """

    def record(
        self,
        db: Session,
        action: str,
        actor: Any = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        patient_id: Optional[str] = None,
        detail: Optional[dict] = None,
    ) -> None:
        try:
            entry = AuditLog(
                actor_user_id=getattr(actor, "id", None),
                actor_role=_role_value(actor),
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                patient_id=patient_id,
                ip=current_client_ip(),
                detail=json.dumps(detail, default=str)[:1000] if detail else None,
            )
            with Session(bind=db.get_bind()) as audit_db:
                audit_db.add(entry)
                audit_db.commit()
        except Exception:
            logger.exception(
                "AUDIT WRITE FAILED action=%s actor=%s resource=%s/%s",
                action, getattr(actor, "id", None), resource_type, resource_id,
            )

    def record_appointment_access(
        self, db: Session, action: str, actor: Any, appointment_id: str, detail: Optional[dict] = None
    ) -> None:
        """Audit someone reading or acting on an appointment's clinical data. A patient
        looking at their OWN record is not logged: the trail is about everyone else's access."""
        try:
            appointment = appointment_repository.get_by_id(db, appointment_id)
            patient_id = appointment.patient_id if appointment else None
        except Exception:
            logger.exception("could not resolve the patient for audit of appointment %s", appointment_id)
            patient_id = None
        if patient_id is not None and getattr(actor, "id", None) == patient_id:
            return
        self.record(
            db, action, actor=actor, resource_type="appointment", resource_id=appointment_id,
            patient_id=patient_id, detail=detail,
        )

    def search(
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
    ) -> AuditLogPageResponse:
        rows, total = audit_repository.query(
            db, action=action, actor_user_id=actor_user_id, patient_id=patient_id,
            resource_id=resource_id, since=since, until=until, limit=limit, offset=offset,
        )
        return AuditLogPageResponse(
            items=[AuditLogResponse.model_validate(r) for r in rows],
            total=total, limit=limit, offset=offset,
        )


audit_service = AuditService()
