"""CSV export of appointments for clinic admins (issue #57).

Exports scheduling data only: never symptoms, consultation notes, prescriptions or AI
summaries. Cells that a spreadsheet would run as a formula are neutralised (CSV injection,
see https://owasp.org/www-community/attacks/CSV_Injection), and one export is capped.
"""
import csv
import io
from datetime import datetime, timezone
from typing import Optional, Tuple

from app.core.datetime_utils import ensure_utc, get_zone
from app.exceptions import AppException
from models.appointment import AppointmentStatus
from repositories.appointment_repository import appointment_repository

MAX_EXPORT_ROWS = 10_000

COLUMNS = [
    "appointment_id", "start_utc", "end_utc", "start_doctor_local", "doctor_timezone", "status",
    "doctor_name", "specialization", "patient_name", "patient_email", "booked_at_utc",
    "cancelled_at_utc", "cancellation_reason",
]

# A cell starting with one of these is a formula in Excel, Sheets and LibreOffice.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def neutralise(value: Optional[str]) -> str:
    """Prefix a would-be formula with ' so the spreadsheet shows it as text."""
    if value is None:
        return ""
    text = str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


def _iso_utc(moment: Optional[datetime]) -> str:
    return ensure_utc(moment).astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if moment else ""


def export_appointments_csv(
    db,
    doctor_id: Optional[str] = None,
    status_filter: Optional[AppointmentStatus] = None,
    from_time: Optional[datetime] = None,
    until_time: Optional[datetime] = None,
) -> Tuple[str, int]:
    """The matching appointments as CSV text, earliest first, and the row count. Raises a 400
    when more than MAX_EXPORT_ROWS match, so nobody receives a silently truncated file."""
    rows, _ = appointment_repository.list_page(
        db, doctor_any_id=doctor_id, status_filter=status_filter, from_time=from_time,
        until_time=until_time, limit=MAX_EXPORT_ROWS + 1,
    )
    if len(rows) > MAX_EXPORT_ROWS:
        raise AppException(
            f"More than {MAX_EXPORT_ROWS:,} appointments match. Narrow the date range or filters and export again.",
            error_code="EXPORT_TOO_LARGE",
        )

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(COLUMNS)
    for appt in rows:
        doctor = appt.doctor
        zone_name = doctor.timezone if doctor else "UTC"
        local_start = ensure_utc(appt.start_time).astimezone(get_zone(zone_name))
        cancelled = appt.status == AppointmentStatus.CANCELLED
        writer.writerow([neutralise(v) for v in (
            appt.id,
            _iso_utc(appt.start_time),
            _iso_utc(appt.end_time),
            local_start.isoformat(),
            zone_name,
            appt.status.value if hasattr(appt.status, "value") else str(appt.status),
            appt.doctor_user.full_name if appt.doctor_user else "",
            doctor.specialization if doctor else "",
            appt.patient.full_name if appt.patient else "",
            appt.patient.email if appt.patient else "",
            _iso_utc(appt.created_at),
            # No separate column records when it was cancelled; cancelling is its last change.
            _iso_utc(appt.updated_at) if cancelled else "",
            appt.cancellation_reason if cancelled else "",
        )])
    return out.getvalue(), len(rows)
