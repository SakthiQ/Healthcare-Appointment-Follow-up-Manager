"""Verify the database-level guarantees against a REAL PostgreSQL.

The test suite runs on SQLite, which has no row locks, no exclusion constraints and no
real concurrency, so this is what proves the PostgreSQL-only parts: every migration
applies, overlapping appointments are rejected by the database, concurrent bookings and
holds resolve to one winner, and a leave cannot interleave with a booking.

    cd backend
    VERIFY_PG_URL=postgresql://user:pass@host/scratch_db VERIFY_PG_WIPE=yes python scripts/verify_postgres.py

*** IT DROPS AND RECREATES THE `public` SCHEMA OF THE DATABASE YOU POINT IT AT. ***
Use an empty scratch database or a throwaway branch (e.g. a Neon branch), never a real one.
It refuses to run without VERIFY_PG_WIPE=yes. Exits non-zero if any check fails.

If the server has the `btree_gist` extension (Neon, Supabase and Render Postgres do) the
real migration is applied and the per-doctor exclusion constraint is checked in full;
otherwise a variant without the doctor-equality column is used and that is reported.
"""
import os, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time as dtime, timedelta, timezone

PG = os.environ.get("VERIFY_PG_URL", "")
if not PG or os.environ.get("VERIFY_PG_WIPE") != "yes":
    sys.exit("Set VERIFY_PG_URL to a SCRATCH database and VERIFY_PG_WIPE=yes (this wipes its public schema). See the docstring.")
BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BACKEND)
os.environ.update(DATABASE_URL=PG, ALLOW_PRIVILEGED_SELF_REGISTRATION="True", ENVIRONMENT="development")
sys.path.insert(0, BACKEND)

import psycopg2

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n       {detail}" if detail else ""), flush=True)


def sql(query, args=None, fetch=False):
    conn = psycopg2.connect(PG.replace('postgresql+psycopg2://', 'postgresql://'))
    conn.autocommit = True
    try:
        cur = conn.cursor()
        cur.execute(query, args)
        return cur.fetchall() if fetch else None
    finally:
        conn.close()


def alembic(*args):
    r = subprocess.run([sys.executable, "-m", "alembic", *args], capture_output=True, text=True, env=os.environ)
    if r.returncode != 0:
        print(r.stdout[-1500:], r.stderr[-2500:])
    return r.returncode == 0


# ------------------------------------------------------------------ migrations
sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
check("migrations 1-4 apply on PostgreSQL", alembic("upgrade", "21a72a0914c8"))

HAS_GIST = sql("SELECT count(*) FROM pg_available_extensions WHERE name = 'btree_gist'", fetch=True)[0][0] > 0
if HAS_GIST:
    check("the overlap migration (CREATE EXTENSION btree_gist + exclusion constraint) applies", alembic("upgrade", "a3c5d7e9f1b2"))
else:
    print("NOTE: btree_gist is not available on this server; verifying the exclusion constraint's range logic "
          "WITHOUT its per-doctor equality column. Re-run on a server that has btree_gist for the full check.")
    sql("ALTER TABLE appointments ADD CONSTRAINT ex_doctor_profile_no_overlap_active "
        "EXCLUDE USING gist (tstzrange(start_time, end_time) WITH &&) "
        "WHERE (status IN ('HELD', 'CONFIRMED', 'RESCHEDULED'))")
    alembic("stamp", "a3c5d7e9f1b2")

# two ACTIVE holds on one slot, as a pre-migration database could contain
now = datetime.now(timezone.utc)
sql("INSERT INTO users (id,email,password_hash,full_name,role,is_active,created_at,updated_at) "
    "VALUES ('u1','p@x.com','x','P','PATIENT',true,%s,%s),('u2','d@x.com','x','D','DOCTOR',true,%s,%s)",
    (now, now, now, now))
sql("INSERT INTO doctors (id,user_id,specialization,slot_duration_minutes,is_active,created_at,updated_at) "
    "VALUES ('d1','u2','Cardio',30,true,%s,%s)", (now, now))
for hid in ("h1", "h2"):
    sql("INSERT INTO appointment_holds (id,doctor_id,patient_id,start_time,end_time,expires_at,is_active,created_at) "
        "VALUES (%s,'d1','u1',%s,%s,%s,true,%s)",
        (hid, now + timedelta(days=3), now + timedelta(days=3, minutes=30), now + timedelta(minutes=10), now))
check("migrations 5-6 apply on PostgreSQL (dedupes pre-existing duplicate active holds)", alembic("upgrade", "head"))
active = sql("SELECT count(*) FROM appointment_holds WHERE is_active", fetch=True)[0][0]
check("exactly one of the duplicate active holds survived", active == 1, f"active holds = {active}")
cols = {r[0] for r in sql("SELECT column_name FROM information_schema.columns WHERE table_name IN ('doctors','users')", fetch=True)}
check("new columns exist", {"timezone", "token_version"} <= cols)
check("login_throttles table exists", bool(sql("SELECT to_regclass('public.login_throttles')", fetch=True)[0][0]))
sql("DELETE FROM appointment_holds; DELETE FROM doctors; DELETE FROM users;")

# ------------------------------------------------------------------ DB-level guards
sql("INSERT INTO users (id,email,password_hash,full_name,role,is_active,created_at,updated_at,token_version) "
    "VALUES ('u1','p@x.com','x','P','PATIENT',true,%s,%s,0),('u2','d@x.com','x','D','DOCTOR',true,%s,%s,0)",
    (now, now, now, now))
sql("INSERT INTO doctors (id,user_id,specialization,slot_duration_minutes,is_active,created_at,updated_at,timezone) "
    "VALUES ('d1','u2','Cardio',30,true,%s,%s,'UTC')", (now, now))


def insert_appt(aid, start, minutes, status="CONFIRMED"):
    sql("INSERT INTO appointments (id,patient_id,doctor_id,doctor_profile_id,start_time,end_time,status,created_at,updated_at) "
        "VALUES (%s,'u1','u2','d1',%s,%s,%s,%s,%s)", (aid, start, start + timedelta(minutes=minutes), status, now, now))


t0 = (now + timedelta(days=5)).replace(minute=0, second=0, microsecond=0)
insert_appt("a1", t0, 30)
for label, aid, start, status, should_fail in [
    ("overlapping with a different start time is rejected (exclusion constraint)", "a2", t0 + timedelta(minutes=15), "CONFIRMED", True),
    ("same start time is rejected (unique index)", "a3", t0, "CONFIRMED", True),
    ("back-to-back slot is allowed", "a4", t0 + timedelta(minutes=30), "CONFIRMED", False),
    ("an overlapping CANCELLED row is allowed", "a5", t0 + timedelta(minutes=15), "CANCELLED", False),
]:
    try:
        insert_appt(aid, start, 30, status)
        failed = False
    except psycopg2.errors.IntegrityError as exc:
        failed = True
        kind = type(exc).__name__
    check(label, failed == should_fail, f"raised IntegrityError subclass: {kind}" if failed else "accepted")
if HAS_GIST:
    sql("INSERT INTO users (id,email,password_hash,full_name,role,is_active,created_at,updated_at,token_version) "
        "VALUES ('u3','d2@x.com','x','D2','DOCTOR',true,%s,%s,0)", (now, now))
    sql("INSERT INTO doctors (id,user_id,specialization,slot_duration_minutes,is_active,created_at,updated_at,timezone) "
        "VALUES ('d2','u3','Cardio',30,true,%s,%s,'UTC')", (now, now))
    try:
        sql("INSERT INTO appointments (id,patient_id,doctor_id,doctor_profile_id,start_time,end_time,status,created_at,updated_at) "
            "VALUES ('a9','u1','u3','d2',%s,%s,'CONFIRMED',%s,%s)", (t0, t0 + timedelta(minutes=30), now, now))
        other_ok = True
    except psycopg2.errors.IntegrityError:
        other_ok = False
    check("a different doctor may book the same time (the constraint is per doctor)", other_ok)
sql("DELETE FROM appointments")

# ------------------------------------------------------------------ application on PostgreSQL
from fastapi.testclient import TestClient
from app.main import app
import repositories.doctor_repository as drepo
import services.doctor_leave_service as leave_mod

client = TestClient(app)
client.__enter__()


def mk(email, role):
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123", "full_name": email.split("@")[0], "role": role})
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


admin = mk("admin@pg.com", "ADMIN")


def new_doctor(tag):
    doc = client.post("/api/v1/admin/doctors", json={"email": f"doc_{tag}@pg.com", "password": "password123", "full_name": f"Dr {tag}",
                                                     "specialization": "Cardiology", "slot_duration_minutes": 30}, headers=admin).json()
    client.post(f"/api/v1/admin/doctors/{doc['id']}/schedule", json={"working_hours": [
        {"day_of_week": d, "start_time": "09:00:00", "end_time": "12:00:00", "is_active": True} for d in range(7)]}, headers=admin)
    return doc


def slot(day_offset, hour=9):
    d = date.today() + timedelta(days=day_offset)
    s = datetime.combine(d, dtime(hour, 0), tzinfo=timezone.utc)
    return s, s + timedelta(minutes=30)


def book(doc, headers, start, end):
    return client.post("/api/v1/appointments", json={"doctor_id": doc["id"], "start_time": start.isoformat(),
                                                     "end_time": end.isoformat()}, headers=headers)


doc = new_doctor("main")
patients = [mk(f"p{i}@pg.com", "PATIENT") for i in range(12)]
s, e = slot(10)
r = book(doc, patients[0], s, e)
check("a normal booking works on PostgreSQL", r.status_code == 201, r.text[:200])
client.post(f"/api/v1/appointments/{r.json()['id']}/cancel", headers=patients[0])

with ThreadPoolExecutor(max_workers=12) as pool:
    codes = list(pool.map(lambda h: book(doc, h, *slot(11)).status_code, patients))
check("12 truly concurrent bookings of one slot: exactly one wins, the rest are 409, no 5xx",
      codes.count(201) == 1 and codes.count(409) == 11, f"codes={sorted(codes)}")

hs, he = slot(12)
body = {"doctor_id": doc["id"], "start_time": hs.isoformat(), "end_time": he.isoformat()}
with ThreadPoolExecutor(max_workers=12) as pool:
    codes = list(pool.map(lambda h: client.post("/api/v1/slots/holds", json=body, headers=h).status_code, patients))
check("12 concurrent holds on one slot: exactly one wins, the rest are 409, no 5xx",
      codes.count(201) == 1 and codes.count(409) == 11, f"codes={sorted(codes)}")


def leave_race(tag, day_offset, disable_lock):
    d = new_doctor(tag)
    start, end = slot(day_offset)
    original_get = drepo.DoctorRepository.get_by_id
    original_q = leave_mod.appointment_repository.get_active_appointments_for_doctor_on_date

    def maybe_unlocked(self, db, doctor_id, with_for_update=False):
        return original_get(self, db, doctor_id, with_for_update=False if disable_lock else with_for_update)

    def slow_after_query(*a, **k):
        rows = original_q(*a, **k)  # leave has looked for appointments to conflict...
        time.sleep(1.5)             # ...and has not committed yet
        return rows

    drepo.DoctorRepository.get_by_id = maybe_unlocked
    leave_mod.appointment_repository.get_active_appointments_for_doctor_on_date = slow_after_query
    out = {}
    try:
        def do_leave():
            out["leave"] = client.post(f"/api/v1/admin/doctors/{d['id']}/leaves",
                                       json={"leave_date": start.date().isoformat(), "reason": "x"}, headers=admin).status_code

        def do_book():
            time.sleep(0.5)
            out["book"] = book(d, patients[1], start, end).status_code

        threads = [threading.Thread(target=do_leave), threading.Thread(target=do_book)]
        [t.start() for t in threads]
        [t.join() for t in threads]
    finally:
        drepo.DoctorRepository.get_by_id = original_get
        leave_mod.appointment_repository.get_active_appointments_for_doctor_on_date = original_q
    stranded = sql("SELECT count(*) FROM appointments WHERE doctor_profile_id=%s AND status IN ('CONFIRMED','RESCHEDULED','HELD')",
                   (d["id"],), fetch=True)[0][0]
    return out, stranded


out, stranded = leave_race("lock", 13, disable_lock=False)
check("leave vs concurrent booking WITH the doctor-row lock: no appointment is left on the leave day",
      out.get("leave") == 201 and stranded == 0, f"{out}, active appointments on leave day = {stranded}")
out, stranded = leave_race("nolock", 14, disable_lock=True)
check("control: the same race WITHOUT the lock does strand an appointment (proves the test can detect the bug)",
      stranded >= 1, f"{out}, active appointments on leave day = {stranded}")

# reschedule vs leave on the same doctor, repeatedly: must not deadlock
dd = new_doctor("dead")
errors = []
for i in range(6):
    s1, e1 = slot(20 + i, 9)
    s2, e2 = slot(20 + i, 10)
    appt = book(dd, patients[2 + i], s1, e1).json()

    def resched():
        errors.append(client.post(f"/api/v1/appointments/{appt['id']}/reschedule",
                                  json={"new_start_time": s2.isoformat(), "new_end_time": e2.isoformat()},
                                  headers=patients[2 + i]).status_code)

    def leave():
        errors.append(client.post(f"/api/v1/admin/doctors/{dd['id']}/leaves",
                                  json={"leave_date": s1.date().isoformat(), "reason": "x"}, headers=admin).status_code)

    ts = [threading.Thread(target=resched), threading.Thread(target=leave)]
    [t.start() for t in ts]
    [t.join() for t in ts]
check("reschedule racing leave creation never deadlocks or 500s (6 rounds)", all(c < 500 for c in errors), f"statuses={sorted(errors)}")

# throttle + logout + timezone path on PostgreSQL
bad = [client.post("/api/v1/auth/login", json={"email": "p0@pg.com", "password": "nope-nope"}).status_code for _ in range(6)]
check("login throttle works on PostgreSQL (5x 401 then 429)", bad[:5] == [401] * 5 and bad[5] == 429, f"{bad}")
tok = client.post("/api/v1/auth/login", json={"email": "p1@pg.com", "password": "password123"}).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}
client.post("/api/v1/auth/logout", headers=h)
check("logout revokes the token on PostgreSQL", client.get("/api/v1/auth/me", headers=h).status_code == 401)
ist = client.post("/api/v1/admin/doctors", json={"email": "doc_ist@pg.com", "password": "password123", "full_name": "Dr IST",
                                                 "specialization": "Cardiology", "timezone": "Asia/Kolkata"}, headers=admin).json()
check("per-doctor timezone round-trips on PostgreSQL", ist.get("timezone") == "Asia/Kolkata")

client.__exit__(None, None, None)
print(f"\nSUMMARY: {sum(results)}/{len(results)} passed", flush=True)
sys.exit(0 if all(results) else 1)
