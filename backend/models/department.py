import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Index, String, Text, func
from sqlalchemy.orm import relationship

from app.core.datetime_utils import UTCDateTime
from app.database import Base


class Department(Base):
    """A hospital department (Cardiology, Paediatrics…) that groups doctors. Names are unique
    regardless of case, so "Cardiology" and "cardiology" cannot both exist."""
    __tablename__ = "departments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(UTCDateTime(), nullable=False, default=lambda: datetime.now(timezone.utc))

    doctors = relationship("Doctor", back_populates="department")

    __table_args__ = (Index("uq_departments_name_lower", func.lower(name), unique=True),)
