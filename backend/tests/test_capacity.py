"""Behaviour under load: the request cap, pool sizing, query counts that do not grow with
the data, paging, the admin dashboard counts, workers draining a backlog, and the SQLite
login lock."""
import asyncio
import threading
import time as walltime
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.config import Settings, settings
from app.core.concurrency_limit import BUSY_MESSAGE, ConcurrencyLimitMiddleware
from app.database import Base, _engine_kwargs
from app.main import app
from tests.conftest import test_engine
from workers.runner import WorkerRunner, batch_was_full


# --------------------------------------------------------------------------- helpers

def _register_login(client, email, role="PATIENT"):
    client.post("/api/v1/auth/register", json={
        "email": email, "password": "password123", "full_name": email.split("@")[0], "role": role})
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _doctor(client, admin, tag):
    doc = client.post("/api/v1/admin/doctors", json={
        "email": f"doc_{tag}@example.com", "password": "password123", "full_name": f"Dr {tag}",
        "specialization": "Cardiology", "slot_duration_minutes": 30}, headers=admin).json()
    client.post(f"/api/v1/admin/doctors/{doc['id']}/schedule", json={"working_hours": [
        {"day_of_week": d, "start_time": "08:00:00", "end_time": "18:00:00", "is_active": True} for d in range(7)]},
        headers=admin)
    return doc


def _book(client, headers, doc, day_offset, hour):
    start = datetime.combine(date.today() + timedelta(days=day_offset), time(hour, 0), tzinfo=timezone.utc)
    r = client.post("/api/v1/appointments", json={
        "doctor_id": doc["id"], "start_time": start.isoformat(),
        "end_time": (start + timedelta(minutes=30)).isoformat()}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


class _QueryCounter:
    def __init__(self, engine):
        self.engine, self.count = engine, 0

    def _hit(self, *args, **kwargs):
        self.count += 1

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._hit)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self._hit)


def _queries(client, url, headers=None):
    with _QueryCounter(test_engine) as counter:
        r = client.get(url, headers=headers)
    assert r.status_code == 200, r.text
    return counter.count, r


# --------------------------------------------------------------------------- request cap

def _gated_middleware():
    """A ConcurrencyLimitMiddleware around an app whose requests finish only when
    `release` is set, and a helper that runs one request through it."""
    release = asyncio.Event()

    async def slow_app(scope, receive, send):
        await release.wait()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": scope["path"].encode()})

    middleware = ConcurrencyLimitMiddleware(slow_app)

    async def call(path, method="GET"):
        sent = []

        async def send(message):
            sent.append(message)

        await middleware({"type": "http", "path": path, "method": method}, None, send)
        return sent

    return middleware, release, call


def test_requests_beyond_the_cap_get_a_503_once_the_wait_runs_out(monkeypatch):
    """With a cap of 2 and no waiting allowed, a third concurrent request is turned away
    at once with Retry-After, while the two in flight complete normally."""
    monkeypatch.setattr(settings, "MAX_CONCURRENT_REQUESTS", 2)
    monkeypatch.setattr(settings, "REQUEST_QUEUE_TIMEOUT_SECONDS", 0)
    middleware, release, call = _gated_middleware()

    async def scenario():
        first = asyncio.create_task(call("/api/v1/doctors"))
        second = asyncio.create_task(call("/api/v1/doctors"))
        await asyncio.sleep(0)
        assert middleware.in_flight == 2
        rejected = await asyncio.wait_for(call("/api/v1/doctors"), timeout=1)
        # The health check and CORS preflights are never capped.
        health = asyncio.create_task(call("/health"))
        preflight = asyncio.create_task(call("/api/v1/doctors", method="OPTIONS"))
        await asyncio.sleep(0)
        release.set()
        done = await asyncio.gather(first, second, health, preflight)
        return rejected, done

    rejected, done = asyncio.run(scenario())
    start, body = rejected
    assert start["status"] == 503
    assert dict(start["headers"])[b"retry-after"] == b"1"
    assert BUSY_MESSAGE.encode() in body["body"] and b"SERVER_BUSY" in body["body"]
    assert all(messages[0]["status"] == 200 for messages in done)
    assert middleware.in_flight == 0, "every finished request must release its place"


def test_requests_beyond_the_cap_wait_their_turn_in_order(monkeypatch):
    """A short burst is absorbed: extra requests wait for a place and are served first
    come first served, and one that waits longer than the timeout gets a 503."""
    monkeypatch.setattr(settings, "MAX_CONCURRENT_REQUESTS", 1)
    monkeypatch.setattr(settings, "REQUEST_QUEUE_TIMEOUT_SECONDS", 5)
    middleware, release, call = _gated_middleware()

    async def scenario():
        order = []

        async def tracked(path):
            sent = await call(path)
            order.append(path)
            return sent

        first = asyncio.create_task(tracked("/a"))
        await asyncio.sleep(0)
        second = asyncio.create_task(tracked("/b"))
        await asyncio.sleep(0)
        third = asyncio.create_task(tracked("/c"))
        await asyncio.sleep(0.05)
        assert middleware.in_flight == 1 and len(middleware._waiters) == 2
        release.set()
        results = await asyncio.wait_for(asyncio.gather(first, second, third), timeout=5)
        return order, results

    order, results = asyncio.run(scenario())
    assert order == ["/a", "/b", "/c"]
    assert all(r[0]["status"] == 200 for r in results)
    assert middleware.in_flight == 0 and not middleware._waiters

    # Now a wait that runs out: the place stays taken past the timeout.
    monkeypatch.setattr(settings, "REQUEST_QUEUE_TIMEOUT_SECONDS", 0.05)
    middleware, release, call = _gated_middleware()

    async def timeout_scenario():
        holder = asyncio.create_task(call("/holder"))
        await asyncio.sleep(0)
        rejected = await call("/late")
        release.set()
        await holder
        return rejected

    rejected = asyncio.run(timeout_scenario())
    assert rejected[0]["status"] == 503
    assert middleware.in_flight == 0 and not middleware._waiters, "a timed-out waiter must not keep a place"


def _limit_middleware():
    """The ConcurrencyLimitMiddleware instance inside the app's built middleware stack."""
    node = app.middleware_stack
    while node is not None and not isinstance(node, ConcurrencyLimitMiddleware):
        node = getattr(node, "app", None)
    assert node is not None, "ConcurrencyLimitMiddleware is not installed"
    return node


def test_a_busy_503_reaches_the_browser_with_cors_headers_and_health_stays_up(client, monkeypatch):
    monkeypatch.setattr(settings, "MAX_CONCURRENT_REQUESTS", 1)
    monkeypatch.setattr(settings, "REQUEST_QUEUE_TIMEOUT_SECONDS", 0)
    origin = settings.cors_allowed_origins_list[0]
    # Sequential requests each release their place.
    for _ in range(3):
        assert client.get("/api/v1/doctors", headers={"Origin": origin}).status_code == 200

    limiter = _limit_middleware()
    limiter.in_flight = 1  # as if one request were still being worked on
    try:
        busy = client.get("/api/v1/doctors", headers={"Origin": origin})
        health = client.get("/health")
    finally:
        limiter.in_flight = 0

    assert busy.status_code == 503
    assert busy.json() == {"detail": BUSY_MESSAGE, "error_code": "SERVER_BUSY"}
    assert busy.headers["retry-after"] == "1"
    assert busy.headers["access-control-allow-origin"] == origin, "the browser must be able to read the 503"
    assert "Retry-After" in busy.headers.get("access-control-expose-headers", "")
    assert health.status_code == 200


def test_pool_shortfall_reports_a_pool_too_small_for_the_cap():
    ok = Settings(MAX_CONCURRENT_REQUESTS=12, DB_POOL_SIZE=10, DB_MAX_OVERFLOW=20)
    small = Settings(MAX_CONCURRENT_REQUESTS=12, DB_POOL_SIZE=5, DB_MAX_OVERFLOW=10)
    uncapped = Settings(MAX_CONCURRENT_REQUESTS=0, DB_POOL_SIZE=1, DB_MAX_OVERFLOW=0)
    assert ok.pool_shortfall() == 0
    assert small.pool_shortfall() == 2 * 12 + 5 - 15
    assert uncapped.pool_shortfall() == 0


def test_engine_gets_the_configured_pool_except_for_in_memory_sqlite():
    for url in ("postgresql+psycopg2://u:p@db/x", "sqlite:///./dev.db"):
        kwargs = _engine_kwargs(url)
        assert kwargs["pool_size"] == settings.DB_POOL_SIZE
        assert kwargs["max_overflow"] == settings.DB_MAX_OVERFLOW
        assert kwargs["pool_timeout"] == settings.DB_POOL_TIMEOUT_SECONDS
    for url in ("sqlite:///:memory:", "sqlite://"):
        assert "pool_size" not in _engine_kwargs(url)


# --------------------------------------------------------------------------- query counts

def test_listing_appointments_costs_the_same_queries_for_one_row_or_many(client):
    """Each row used to load its patient, doctor and doctor profile one query at a time,
    so an admin list of 2,600 appointments ran ~7,800 queries."""
    admin = _register_login(client, "admin_nplus1@example.com", "ADMIN")
    doc = _doctor(client, admin, "nplus1")
    patients = [_register_login(client, f"p{i}_nplus1@example.com") for i in range(4)]

    _book(client, patients[0], doc, 90, 8)
    url = f"/api/v1/appointments?doctor_id={doc['id']}"
    one, r_one = _queries(client, url, admin)
    for i, headers in enumerate(patients[1:], start=1):
        _book(client, headers, doc, 90, 8 + i)
    many, r_many = _queries(client, url, admin)

    assert len(r_one.json()) == 1 and len(r_many.json()) == 4
    assert many == one, f"1 row took {one} queries, 4 rows took {many}"
    assert {a["patient_name"] for a in r_many.json()} == {f"p{i}_nplus1" for i in range(4)}
    assert all(a["doctor_name"] == "Dr nplus1" and a["doctor_specialization"] == "Cardiology" for a in r_many.json())


def test_doctor_search_costs_the_same_queries_for_one_doctor_or_many(client):
    admin = _register_login(client, "admin_docsearch@example.com", "ADMIN")
    client.post("/api/v1/admin/doctors", json={"email": "solo_ds@example.com", "password": "password123",
                "full_name": "Dr Solo", "specialization": "Rheumatology"}, headers=admin)
    one, r_one = _queries(client, "/api/v1/doctors?specialization=Rheumatology")
    for i in range(3):
        client.post("/api/v1/admin/doctors", json={"email": f"more{i}_ds@example.com", "password": "password123",
                    "full_name": f"Dr More {i}", "specialization": "Rheumatology"}, headers=admin)
    many, r_many = _queries(client, "/api/v1/doctors?specialization=Rheumatology")
    assert len(r_one.json()) == 1 and len(r_many.json()) == 4
    assert many == one, f"1 doctor took {one} queries, 4 doctors took {many}"
    assert [d["full_name"] for d in r_many.json()] == sorted(d["full_name"] for d in r_many.json())


# --------------------------------------------------------------------------- paging and stats

def test_appointment_list_pages_and_reports_the_total(client):
    admin = _register_login(client, "admin_paging@example.com", "ADMIN")
    doc = _doctor(client, admin, "paging")
    patient = _register_login(client, "patient_paging@example.com")
    other = _register_login(client, "other_paging@example.com")
    booked = [_book(client, patient, doc, 95, 8 + i) for i in range(5)]
    _book(client, other, doc, 95, 15)

    everything = client.get("/api/v1/appointments", headers=patient)
    assert [a["id"] for a in everything.json()] == [a["id"] for a in booked]
    assert everything.headers["x-total-count"] == "5"

    first = client.get("/api/v1/appointments?limit=2", headers=patient)
    second = client.get("/api/v1/appointments?limit=2&offset=2", headers=patient)
    last = client.get("/api/v1/appointments?limit=2&offset=4", headers=patient)
    pages = [first.json(), second.json(), last.json()]
    assert [len(p) for p in pages] == [2, 2, 1]
    assert [a["id"] for p in pages for a in p] == [a["id"] for a in booked], "pages must not overlap or skip"
    assert {r.headers["x-total-count"] for r in (first, second, last)} == {"5"}, "only the patient's own"

    for bad in ("limit=0", "limit=1001", "offset=-1"):
        assert client.get(f"/api/v1/appointments?{bad}", headers=patient).status_code == 422


def test_admin_stats_counts_in_the_database_and_is_admin_only(client):
    admin = _register_login(client, "admin_stats@example.com", "ADMIN")
    patient = _register_login(client, "patient_stats@example.com")
    before = client.get("/api/v1/admin/stats", headers=admin).json()

    doc = _doctor(client, admin, "stats")
    first = _book(client, patient, doc, 97, 9)
    _book(client, patient, doc, 97, 10)
    client.post(f"/api/v1/appointments/{first['id']}/cancel", headers=patient)

    after = client.get("/api/v1/admin/stats", headers=admin).json()
    assert after["active_doctors"] == before["active_doctors"] + 1
    assert after["appointments_total"] == before["appointments_total"] + 2
    by = after["appointments_by_status"]
    assert set(by) == {"HELD", "CONFIRMED", "RESCHEDULED", "CANCELLED", "CONFLICTED", "COMPLETED"}
    assert by["CANCELLED"] == before["appointments_by_status"]["CANCELLED"] + 1
    assert by["CONFIRMED"] == before["appointments_by_status"]["CONFIRMED"] + 1
    assert sum(by.values()) == after["appointments_total"]

    assert client.get("/api/v1/admin/stats", headers=patient).status_code == 403
    assert client.get("/api/v1/admin/stats").status_code == 401


# --------------------------------------------------------------------------- workers

def test_a_worker_with_a_full_batch_goes_again_without_waiting_for_the_poll():
    class Backlog:
        batch_size = 3

        def __init__(self):
            self.remaining, self.calls = 7, 0
            self.drained = threading.Event()

        def run_once(self, db):
            self.calls += 1
            claimed = min(self.batch_size, self.remaining)
            self.remaining -= claimed
            if self.remaining == 0:
                self.drained.set()
            return {"claimed": claimed}

    class Session:
        def close(self):
            pass

    worker = Backlog()
    runner = WorkerRunner(Session, {"backlog": worker}, poll_interval_seconds=60)
    runner.start()
    try:
        assert worker.drained.wait(5), "a 60 s poll interval must not apply between full batches"
    finally:
        runner.stop()
    assert worker.calls == 3  # 3 + 3 + 1, then it waits for the next poll

    assert batch_was_full(SimpleNamespace(batch_size=3), {"claimed": 3})
    assert not batch_was_full(SimpleNamespace(batch_size=3), {"claimed": 2})
    assert not batch_was_full(SimpleNamespace(), {"claimed": 99})  # workers without batches
    assert not batch_was_full(SimpleNamespace(batch_size=3), None)  # a run that raised


def test_queue_workers_use_the_configured_batch_sizes():
    from workers.calendar_worker import CalendarWorker, calendar_worker
    from workers.notification_worker import NotificationWorker, notification_worker
    assert notification_worker.batch_size == settings.NOTIFICATION_BATCH_SIZE
    assert calendar_worker.batch_size == settings.CALENDAR_BATCH_SIZE
    assert NotificationWorker(batch_size=7).batch_size == 7 and CalendarWorker(batch_size=7).batch_size == 7


# --------------------------------------------------------------------------- locks

def test_the_process_wide_booking_lock_is_only_taken_on_sqlite():
    from services.appointment_service import _booking_lock, _sqlite_booking_lock

    postgres_db = SimpleNamespace(bind=SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    finished = threading.Event()

    def book_on_postgres():
        with _sqlite_booking_lock(postgres_db):
            finished.set()

    with _booking_lock:  # held, as by a booking for some other doctor
        worker = threading.Thread(target=book_on_postgres)
        worker.start()
        assert finished.wait(2), "a PostgreSQL booking must not queue behind the process-wide lock"
    worker.join()


def test_a_successful_login_on_file_sqlite_is_fast_and_audited(tmp_path):
    """The throttle reset left a write transaction open, so on a real SQLite file every
    login waited 5 s for the lock and then lost its audit entry."""
    from app.core.security import hash_password
    from models.audit import AuditLog
    from models.user import User, UserRole
    from schemas.auth import UserLoginRequest
    from services.auth_service import auth_service

    engine = create_engine(f"sqlite:///{tmp_path / 'login.db'}", **_engine_kwargs("sqlite:///x.db"))
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with Session() as db:
        db.add(User(email="fast@example.com", password_hash=hash_password("password123"),
                    full_name="Fast", role=UserRole.PATIENT))
        db.commit()

    db = Session()
    try:
        started = walltime.perf_counter()
        token = auth_service.login_user(db, UserLoginRequest(email="fast@example.com", password="password123"),
                                        client_ip="203.0.113.5")
        elapsed = walltime.perf_counter() - started
    finally:
        db.close()

    assert token.access_token
    assert elapsed < 3, f"login took {elapsed:.1f}s"
    with Session() as check:
        assert check.query(AuditLog).filter_by(action="auth.login").count() == 1
    engine.dispose()
