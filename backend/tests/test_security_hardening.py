"""Client IP behind proxies, the per-patient hold cap, stored booking notes and
cancellation reasons, and the 8-character password minimum."""
from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.config import settings
from app.core.client_ip import resolve_client_ip
from app.core.security import hash_password
from models.appointment import AppointmentHold
from models.user import User, UserRole


def _scope(peer="10.0.0.9", headers=()):
    return {"type": "http", "client": (peer, 5555),
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers]}


def _register_login(client, email, role="PATIENT", password="password123"):
    client.post("/api/v1/auth/register", json={
        "email": email, "password": password, "full_name": email.split("@")[0], "role": role})
    token = client.post("/api/v1/auth/login", json={"email": email, "password": password}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _doctor(client, admin, tag):
    doc = client.post("/api/v1/admin/doctors", json={
        "email": f"doc_{tag}@example.com", "password": "password123", "full_name": f"Dr {tag}",
        "specialization": "Cardiology", "slot_duration_minutes": 30}, headers=admin).json()
    client.post(f"/api/v1/admin/doctors/{doc['id']}/schedule", json={"working_hours": [
        {"day_of_week": d, "start_time": "08:00:00", "end_time": "18:00:00", "is_active": True} for d in range(7)]},
        headers=admin)
    return doc


def _slot(day_offset, hour):
    start = datetime.combine(date.today() + timedelta(days=day_offset), time(hour, 0), tzinfo=timezone.utc)
    return start.isoformat(), (start + timedelta(minutes=30)).isoformat()


# --------------------------------------------------------------------------- client IP

@pytest.fixture
def proxy_settings(monkeypatch):
    def configure(header=None, hops=0):
        monkeypatch.setattr(settings, "CLIENT_IP_HEADER", header)
        monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", hops)
    configure()
    return configure


def test_without_proxy_settings_the_tcp_peer_is_the_client(proxy_settings):
    spoofed = _scope(headers=[("X-Forwarded-For", "1.2.3.4"), ("CF-Connecting-IP", "5.6.7.8")])
    assert resolve_client_ip(spoofed) == "10.0.0.9"


def test_x_forwarded_for_is_read_from_the_right_so_client_entries_are_ignored(proxy_settings):
    proxy_settings(hops=2)
    # client -> Cloudflare (appends the client) -> Render proxy (appends Cloudflare)
    honest = _scope(headers=[("X-Forwarded-For", "203.0.113.7, 104.22.17.40")])
    forged = _scope(headers=[("X-Forwarded-For", "6.6.6.6, 7.7.7.7, 203.0.113.7, 104.22.17.40")])
    assert resolve_client_ip(honest) == "203.0.113.7"
    assert resolve_client_ip(forged) == "203.0.113.7", "entries the client wrote must not matter"

    # Split over several header lines, as some proxies send it.
    split = _scope(headers=[("X-Forwarded-For", "6.6.6.6"), ("X-Forwarded-For", "203.0.113.7, 104.22.17.40")])
    assert resolve_client_ip(split) == "203.0.113.7"

    # Too few entries (request did not come through the proxies) or garbage: fall back to the peer.
    assert resolve_client_ip(_scope(headers=[("X-Forwarded-For", "203.0.113.7")])) == "10.0.0.9"
    assert resolve_client_ip(_scope(headers=[("X-Forwarded-For", "not-an-ip, 104.22.17.40")])) == "10.0.0.9"


def test_a_configured_edge_header_wins_and_bad_values_fall_through(proxy_settings):
    proxy_settings(header="CF-Connecting-IP", hops=2)
    both = _scope(headers=[("CF-Connecting-IP", "198.51.100.23"),
                           ("X-Forwarded-For", "203.0.113.7, 104.22.17.40")])
    assert resolve_client_ip(both) == "198.51.100.23"
    assert resolve_client_ip(_scope(headers=[("cf-connecting-ip", "2001:db8::1")])) == "2001:db8::1"
    assert resolve_client_ip(_scope(headers=[("CF-Connecting-IP", "203.0.113.9:443")])) == "203.0.113.9"
    bad_header = _scope(headers=[("CF-Connecting-IP", "<script>"),
                                 ("X-Forwarded-For", "203.0.113.7, 104.22.17.40")])
    assert resolve_client_ip(bad_header) == "203.0.113.7"


def test_a_fake_ip_per_request_no_longer_dodges_the_login_lockout(client, proxy_settings):
    """With `--forwarded-allow-ips='*'` the leftmost X-Forwarded-For entry was trusted, so
    an attacker could send a new fake IP with every guess and never be locked out."""
    proxy_settings(hops=1)
    client.post("/api/v1/auth/register", json={
        "email": "victim_xff@example.com", "password": "password123", "full_name": "Victim"})
    statuses = []
    for i in range(settings.LOGIN_MAX_FAILED_ATTEMPTS + 1):
        r = client.post("/api/v1/auth/login",
                        json={"email": "victim_xff@example.com", "password": "wrong-guess"},
                        headers={"X-Forwarded-For": f"10.66.0.{i}, 198.51.100.7"})
        statuses.append(r.status_code)
    assert statuses[:-1] == [401] * settings.LOGIN_MAX_FAILED_ATTEMPTS
    assert statuses[-1] == 429


# --------------------------------------------------------------------------- hold cap

def test_a_patient_can_only_hold_a_few_slots_at_once(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "MAX_ACTIVE_HOLDS_PER_PATIENT", 2)
    admin = _register_login(client, "admin_holdcap@example.com", "ADMIN")
    doc = _doctor(client, admin, "holdcap")
    patient = _register_login(client, "patient_holdcap@example.com")
    other = _register_login(client, "other_holdcap@example.com")

    def hold(headers, hour):
        start, end = _slot(100, hour)
        return client.post("/api/v1/slots/holds", json={"doctor_id": doc["id"], "start_time": start, "end_time": end},
                           headers=headers)

    first, second = hold(patient, 8), hold(patient, 9)
    assert first.status_code == 201 and second.status_code == 201
    third = hold(patient, 10)
    assert third.status_code == 409 and "2 slot(s) on hold" in third.json()["detail"]
    assert hold(other, 10).status_code == 201, "the cap is per patient"

    # Releasing one frees a place.
    assert client.post(f"/api/v1/slots/holds/{first.json()['id']}/release", headers=patient).status_code == 204
    assert hold(patient, 11).status_code == 201

    # An expired hold no longer counts.
    db_session.get(AppointmentHold, second.json()["id"]).expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()
    assert hold(patient, 12).status_code == 201


# --------------------------------------------------------------------------- notes and reasons

def test_booking_notes_and_cancellation_reasons_are_stored_and_shown(client):
    admin = _register_login(client, "admin_notes@example.com", "ADMIN")
    doc = _doctor(client, admin, "notes")
    patient = _register_login(client, "patient_notes@example.com")
    doctor = _register_login(client, "doc_notes@example.com")

    start, end = _slot(101, 9)
    booked = client.post("/api/v1/appointments", json={
        "doctor_id": doc["id"], "start_time": start, "end_time": end, "notes": "  Knee pain since Monday  "},
        headers=patient)
    assert booked.status_code == 201, booked.text
    appt = booked.json()
    assert appt["notes"] == "Knee pain since Monday" and appt["cancellation_reason"] is None
    assert client.get(f"/api/v1/appointments/{appt['id']}", headers=doctor).json()["notes"] == "Knee pain since Monday"

    # Through a hold, too.
    start, end = _slot(101, 10)
    hold = client.post("/api/v1/slots/holds", json={"doctor_id": doc["id"], "start_time": start, "end_time": end},
                       headers=patient).json()
    from_hold = client.post("/api/v1/appointments", json={"doctor_id": doc["id"], "hold_id": hold["id"],
                            "notes": "Follow-up"}, headers=patient).json()
    assert from_hold["notes"] == "Follow-up"

    cancelled = client.post(f"/api/v1/appointments/{appt['id']}/cancel",
                            json={"cancellation_reason": " Feeling better "}, headers=patient)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED" and cancelled.json()["cancellation_reason"] == "Feeling better"
    listed = {a["id"]: a for a in client.get("/api/v1/appointments", headers=doctor).json()}
    assert listed[appt["id"]]["cancellation_reason"] == "Feeling better"

    # A blank reason, or none at all, is stored as no reason.
    blank = client.post(f"/api/v1/appointments/{from_hold['id']}/cancel", json={"cancellation_reason": "   "},
                        headers=patient).json()
    assert blank["cancellation_reason"] is None


def test_overlong_notes_and_reasons_are_rejected(client):
    admin = _register_login(client, "admin_longnotes@example.com", "ADMIN")
    doc = _doctor(client, admin, "longnotes")
    patient = _register_login(client, "patient_longnotes@example.com")
    start, end = _slot(102, 9)
    too_long = client.post("/api/v1/appointments", json={
        "doctor_id": doc["id"], "start_time": start, "end_time": end, "notes": "x" * 2001}, headers=patient)
    assert too_long.status_code == 422
    appt = client.post("/api/v1/appointments", json={
        "doctor_id": doc["id"], "start_time": start, "end_time": end}, headers=patient).json()
    assert client.post(f"/api/v1/appointments/{appt['id']}/cancel", json={"cancellation_reason": "y" * 501},
                       headers=patient).status_code == 422


# --------------------------------------------------------------------------- passwords

def test_new_passwords_need_eight_characters_but_old_short_ones_still_sign_in(client, db_session):
    seven, eight = "abc1234", "abcd1234"
    r = client.post("/api/v1/auth/register", json={"email": "short_pw@example.com", "password": seven, "full_name": "Short"})
    assert r.status_code == 422
    assert client.post("/api/v1/auth/register", json={
        "email": "ok_pw@example.com", "password": eight, "full_name": "Okay"}).status_code == 201

    headers = {"Authorization": "Bearer " + client.post("/api/v1/auth/login", json={
        "email": "ok_pw@example.com", "password": eight}).json()["access_token"]}
    assert client.post("/api/v1/auth/change-password", json={"current_password": eight, "new_password": seven},
                       headers=headers).status_code == 422

    admin = _register_login(client, "admin_pw@example.com", "ADMIN")
    assert client.post("/api/v1/admin/doctors", json={"email": "doc_shortpw@example.com", "password": seven,
                       "full_name": "Dr Short", "specialization": "GP"}, headers=admin).status_code == 422

    # An account created before the rule, with a 6-character password, can still sign in.
    db_session.add(User(email="legacy_pw@example.com", password_hash=hash_password("abc123"),
                        full_name="Legacy", role=UserRole.PATIENT))
    db_session.commit()
    assert client.post("/api/v1/auth/login", json={"email": "legacy_pw@example.com", "password": "abc123"}).status_code == 200
