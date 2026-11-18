"""What appointment emails say (issue #52): who the appointment is with, a link back to
the app, an HTML part next to the plain text, escaped values, and no clinical details."""
import email
import json
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.config import settings
from models.appointment import Appointment
from models.notification import NotificationType
from models.user import User
from providers.email_provider import MockEmailProvider, RealEmailProvider
from services.email_templates import render_email
from services.notification_service import notification_service
from tests.test_notifications import book_appointment, get_next_monday, setup_notification_test_env

BASE = "https://app.example.test"


@pytest.fixture
def appointment(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", BASE + "/")
    doc, _, patient_headers, _ = setup_notification_test_env(client)
    monday = get_next_monday()
    appt = book_appointment(
        client, patient_headers, doc["id"],
        datetime.combine(monday, time(9, 0), tzinfo=timezone.utc),
        datetime.combine(monday, time(9, 30), tzinfo=timezone.utc),
    )
    return db_session.get(Appointment, appt["id"])


def _job(appointment, notification_type, recipient_id, payload=None):
    return SimpleNamespace(
        notification_type=notification_type,
        appointment_id=appointment.id if appointment else None,
        recipient_id=recipient_id,
        payload=json.dumps(payload) if payload else None,
    )


APPOINTMENT_TYPES = [
    (NotificationType.BOOKING_CONFIRMATION, None),
    (NotificationType.APPOINTMENT_REMINDER, None),
    (NotificationType.CANCELLATION, None),
    (NotificationType.APPOINTMENT_RESCHEDULED, "reschedule"),
]


@pytest.mark.parametrize("notification_type,payload_kind", APPOINTMENT_TYPES)
def test_patient_email_names_the_doctor_and_links_to_the_patient_page(db_session, appointment, notification_type, payload_kind):
    payload = {"previous_start_time": (appointment.start_time - timedelta(days=1)).isoformat()} if payload_kind else None
    content = notification_service._build_content(
        db_session, _job(appointment, notification_type, appointment.patient_id, payload)
    )
    link = f"{BASE}/patient/appointments/{appointment.id}"
    for body in (content.text, content.html):
        assert "Dr. Notif (Pediatrics)" in body
        assert link in body
        assert "Patient Notif" not in body


@pytest.mark.parametrize("notification_type,payload_kind", APPOINTMENT_TYPES)
def test_doctor_email_names_the_patient_and_links_to_the_doctor_page(db_session, appointment, notification_type, payload_kind):
    payload = {"previous_start_time": (appointment.start_time - timedelta(days=1)).isoformat()} if payload_kind else None
    content = notification_service._build_content(
        db_session, _job(appointment, notification_type, appointment.doctor_id, payload)
    )
    link = f"{BASE}/doctor/appointments/{appointment.id}"
    for body in (content.text, content.html):
        assert "Patient Notif" in body
        assert link in body
        assert "/patient/appointments/" not in body


def test_leave_conflict_names_the_doctor_and_links_to_booking(db_session, appointment):
    content = notification_service._build_content(db_session, _job(
        appointment, NotificationType.DOCTOR_LEAVE_CONFLICT, appointment.patient_id,
        {"original_start_time": "2030-01-07 09:00 UTC", "leave_date": "2030-01-07"},
    ))
    assert "Dr. Notif (Pediatrics)" in content.text
    assert f"{BASE}/patient/doctors" in content.text and f"{BASE}/patient/doctors" in content.html


def test_medication_reminder_links_to_the_appointment_but_names_no_drug(db_session, appointment):
    content = notification_service._build_content(db_session, _job(
        appointment, NotificationType.MEDICATION_REMINDER, appointment.patient_id,
        {"medication_name": "Sertraline", "dosage": "50mg", "frequency": "Once daily", "day": 1},
    ))
    assert f"{BASE}/patient/appointments/{appointment.id}" in content.text
    for body in (content.text, content.html):
        for secret in ("Sertraline", "50mg", "Once daily"):
            assert secret not in body


def test_names_from_the_database_are_escaped_in_html(db_session, appointment):
    patient = db_session.get(User, appointment.patient_id)
    patient.full_name = "<b>Pat</b> & co"
    db_session.commit()
    content = notification_service._build_content(
        db_session, _job(appointment, NotificationType.BOOKING_CONFIRMATION, appointment.doctor_id)
    )
    assert "<b>Pat</b>" not in content.html
    assert "&lt;b&gt;Pat&lt;/b&gt; &amp; co" in content.html
    assert "<b>Pat</b> & co" in content.text  # the plain-text part is shown as text anyway


def test_html_is_self_contained():
    content = render_email("Subject", ["Hello"], "https://app.example.test/x", "Open")
    html = content.html.lower()
    assert "<img" not in html and "<script" not in html and "<link" not in html
    assert "src=" not in html and "<style" not in html


def test_link_with_quotes_cannot_break_out_of_the_href():
    content = render_email("Subject", ["Hello"], 'https://x.test/"><script>alert(1)</script>', "Open")
    assert "<script>" not in content.html


def test_mock_provider_records_the_html_part(db_session, appointment):
    provider = MockEmailProvider()
    provider.send("a@example.com", "Subject", "text", html="<p>hi</p>")
    assert provider.sent_emails[-1]["html"] == "<p>hi</p>"


def test_smtp_message_is_multipart_with_text_and_html(monkeypatch):
    import smtplib

    sent = {}

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, **kwargs): pass
        def login(self, *a): pass
        def sendmail(self, from_addr, to_addrs, message): sent["message"] = message

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    content = render_email("Appointment Confirmed", ["Your appointment is confirmed."], "https://x.test/a", "View")
    RealEmailProvider().send("someone@example.com", content.subject, content.text, html=content.html)

    message = email.message_from_string(sent["message"])
    assert message.get_content_type() == "multipart/alternative"
    parts = [p.get_content_type() for p in message.get_payload()]
    assert parts == ["text/plain", "text/html"]
    text = message.get_payload()[0].get_payload(decode=True).decode()
    assert "Your appointment is confirmed." in text and "https://x.test/a" in text


def test_smtp_message_without_html_stays_plain_text(monkeypatch):
    import smtplib

    sent = {}

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, **kwargs): pass
        def login(self, *a): pass
        def sendmail(self, from_addr, to_addrs, message): sent["message"] = message

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    RealEmailProvider().send("someone@example.com", "Subject", "Just text")
    assert email.message_from_string(sent["message"]).get_content_type() == "text/plain"
