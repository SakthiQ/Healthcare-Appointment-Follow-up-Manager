import uuid
from datetime import datetime, timezone
from app.core.datetime_utils import UTCDateTime
from sqlalchemy import Column, String, Text
from app.database import Base


class AuditLog(Base):
    """Append-only record of who did or looked at what.

    Deliberately no foreign keys: an entry must outlive the user or appointment it
    mentions. It holds identifiers and an action name, never clinical content, so the
    log itself is not a second copy of patient data. Nothing in the application updates
    or deletes rows.
    """
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    occurred_at = Column(UTCDateTime(), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    actor_user_id = Column(String(36), nullable=True, index=True)
    actor_role = Column(String(16), nullable=True)
    # Dotted action name, e.g. "appointment.view", "consultation.submit", "auth.login".
    action = Column(String(64), nullable=False, index=True)
    resource_type = Column(String(32), nullable=True)
    resource_id = Column(String(36), nullable=True, index=True)
    # Whose data was touched, so "who accessed this patient's records" is one query.
    patient_id = Column(String(36), nullable=True, index=True)
    ip = Column(String(64), nullable=True)
    # Small JSON string of non-clinical context (e.g. a filter, an attempted email).
    detail = Column(Text, nullable=True)
