"""Build a standard iCalendar (.ics) file for one appointment, so it can be added to Apple
Calendar, Outlook or any other calendar app without Google OAuth.

Standard library only. Follows RFC 5545: CRLF line endings, text escaping (section 3.3.11)
and folding of lines longer than 75 octets (section 3.1). The file holds when and with whom,
and a link back to the app; never symptoms, notes or prescriptions (email and calendar files
are not a private channel).
"""
from datetime import datetime, timezone

from app.config import settings
from models.appointment import AppointmentStatus
from models.user import UserRole
from schemas.appointment import AppointmentResponse

_FOLD_AT = 75  # octets per line, CRLF excluded


def escape_text(value: str) -> str:
    """Escape a TEXT value (RFC 5545 3.3.11): backslash first, then ; , and newlines."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def fold_line(line: str) -> str:
    """Fold a content line into chunks of at most 75 octets (RFC 5545 3.1). Continuation
    lines start with one space. Never splits a multi-byte UTF-8 character."""
    out, current, size = [], "", 0
    for char in line:
        width = len(char.encode("utf-8"))
        limit = _FOLD_AT if not out else _FOLD_AT - 1  # the leading space counts
        if size + width > limit:
            out.append(current)
            current, size = "", 0
        current += char
        size += width
    out.append(current)
    return "\r\n ".join(out)


def _utc(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_appointment_ics(appt: AppointmentResponse, viewer_role: UserRole, now: datetime | None = None) -> str:
    """One VCALENDAR with one VEVENT. The summary names the other person from the viewer's
    side: a patient sees the doctor, a doctor sees the patient."""
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    if viewer_role == UserRole.DOCTOR:
        other = appt.patient_name or "a patient"
        link = f"{base}/doctor/appointments/{appt.id}"
    elif viewer_role == UserRole.PATIENT:
        other = appt.doctor_name or "your doctor"
        link = f"{base}/patient/appointments/{appt.id}"
    else:
        other = appt.doctor_name or "a doctor"
        link = base
    status = "CANCELLED" if appt.status == AppointmentStatus.CANCELLED else "CONFIRMED"

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Healthflow//Appointments//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:appointment-{appt.id}@healthflow",
        f"DTSTAMP:{_utc(now or datetime.now(timezone.utc))}",
        f"DTSTART:{_utc(appt.start_time)}",
        f"DTEND:{_utc(appt.end_time)}",
        f"SUMMARY:{escape_text(f'Appointment with {other}')}",
        f"DESCRIPTION:{escape_text(f'Open this appointment in Healthflow: {link}')}",
        f"URL:{link}",
        f"STATUS:{status}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(fold_line(line) for line in lines) + "\r\n"
