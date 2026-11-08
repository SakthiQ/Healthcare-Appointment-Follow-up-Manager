from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator

UTC_ZONE = ZoneInfo("UTC")


def is_valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError, KeyError, OSError):
        return False


def get_zone(name: Optional[str]) -> ZoneInfo:
    """The IANA zone for a doctor's `timezone` value; UTC if it is blank or unknown."""
    if name and is_valid_timezone(name):
        return ZoneInfo(name)
    return UTC_ZONE


def local_to_utc(day: date, wall_time: time, zone: ZoneInfo) -> datetime:
    """The UTC instant at which `wall_time` happens on `day` in `zone`."""
    return datetime.combine(day, wall_time, tzinfo=zone).astimezone(timezone.utc)


def local_day_bounds_utc(day: date, zone: ZoneInfo) -> Tuple[datetime, datetime]:
    """[start, end) of the calendar day `day` in `zone`, as UTC instants. A day with a
    daylight-saving change is 23 or 25 hours long, which this gets right."""
    return local_to_utc(day, time(0, 0), zone), local_to_utc(day + timedelta(days=1), time(0, 0), zone)


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
