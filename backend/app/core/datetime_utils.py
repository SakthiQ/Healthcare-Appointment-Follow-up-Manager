from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure a datetime object is timezone-aware (UTC)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class UTCDateTime(TypeDecorator):
    """A timezone-aware DateTime column that always round-trips as UTC.

    PostgreSQL's timestamptz already returns aware values, but SQLite (tests,
    local dev) drops the offset and hands back naive datetimes, which then
    serialise without a "Z"/"+00:00" designator. Normalising on both write and
    read means every value leaving the ORM is aware and in UTC, whatever the
    dialect or the connection's session time zone.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Optional[datetime], dialect) -> Optional[datetime]:
        if value is None:
            return None
        return ensure_utc(value).astimezone(timezone.utc)

    def process_result_value(self, value: Optional[datetime], dialect) -> Optional[datetime]:
        if value is None:
            return None
        return ensure_utc(value).astimezone(timezone.utc)
