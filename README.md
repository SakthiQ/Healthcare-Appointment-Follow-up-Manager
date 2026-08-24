# Healthcare Appointment & Follow-up Manager

A clinic booking platform with separate patient, doctor, and admin portals. Patients
share symptoms before a visit and get an AI-generated pre-visit summary for the doctor;
doctors record consultations and prescriptions and get an AI-generated post-visit
summary for the patient; both sides get email notifications and Google Calendar sync;
medication reminders are scheduled automatically from the prescription.

Built across 13 phases (see `AGENT_PHASES.md`) against the spec in `AGENT_SPEC.md`. All
13 are complete — see [Project status](#project-status) for exactly what that does and
doesn't mean.

## Contents

- [Stack](#stack)
- [Architecture](#architecture)
- [Setup](#setup)
- [Environment variables](#environment-variables)
- [DEMO_MODE](#demo_mode)
- [Creating the first admin account](#creating-the-first-admin-account)
- [API documentation](#api-documentation)
- [Database schema](#database-schema)
- [LLM prompts](#llm-prompts)
- [Google Calendar & OAuth 2.0 setup](#google-calendar--oauth-20-setup)
- [Running tests](#running-tests)
- [Deployment](#deployment)
- [Known limitations](#known-limitations)
- [Project status](#project-status)

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.14 + FastAPI |
| Database | PostgreSQL (SQLite fallback for local dev/tests) |
| ORM / Migrations | SQLAlchemy + Alembic |
| Validation | Pydantic |
| Auth | JWT (PyJWT) + bcrypt |
| Background jobs | Two simple polling workers (no broker/queue) |
| Frontend | React 18 + TypeScript + Vite, React Router, plain `fetch` |
| Testing | pytest (backend, 105 tests) — see [Running tests](#running-tests) |

No microservices, Kafka, Kubernetes, Redis, RAG, or multi-agent frameworks — a modular
monolith throughout, by design (see `docs/engineering-decisions.md`).

## Architecture

Full detail in `docs/architecture.md` and `docs/database-design.md`. The short version:

```
frontend/  (React SPA)
   │  fetch, Bearer JWT
   ▼
backend/app/api/          thin route handlers — no business logic
   │
   ▼
backend/services/         business rules, transaction boundaries
   │                       AppointmentService imports NO provider — the
   │                       booking transaction cannot touch an external service
   ▼
backend/repositories/     persistence
   │
   ▼
PostgreSQL

backend/providers/        AIProvider · EmailProvider · CalendarProvider
                           each: Real* (the actual service) + Mock* (DEMO_MODE)
backend/workers/          NotificationWorker · CalendarWorker
                           poll for due jobs, call providers, retry with backoff
```

Every external call (LLM, email, Google Calendar) happens **after** the appointment
transaction has already committed, in a separate best-effort step whose failure is
recorded on its own row and never touches the appointment. See
`docs/failure-handling.md` for the full comparison table, and
`docs/system-design.md` for the double-booking / leave-conflict / slot-hold / notification
mechanisms specifically.

## Setup

Requires Python 3.11+ and Node 18+.

```bash
# Backend
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
cp .env.example .env            # defaults work out of the box (SQLite + DEMO_MODE=True)
alembic upgrade head
python -m uvicorn app.main:app --reload
# → http://localhost:8000 , docs at http://localhost:8000/api/v1/docs
```

```bash
# Frontend (separate terminal)
cd frontend
npm install
cp .env.example .env            # defaults proxy to http://localhost:8000
npm run dev
# → http://localhost:5173
```

> **Windows note:** if your checkout path contains `&` (as this repo's default clone
> location does), `npx` fails to resolve module paths. Run local binaries directly, e.g.
> `node ./node_modules/vite/bin/vite.js build` — see `frontend/README.md`.

To use PostgreSQL instead of the SQLite fallback, set `DATABASE_URL` in `backend/.env`
to a `postgresql://...` URL before running `alembic upgrade head`.

## Environment variables

Every variable is documented inline in `backend/.env.example` and `frontend/.env.example`.
Summary:

| Variable | Purpose | Required when |
|---|---|---|
| `DATABASE_URL` | PostgreSQL (or SQLite) connection string | always |
| `SECRET_KEY` | JWT signing key | always — **change for any real deployment** |
| `DEMO_MODE` | `True` → Mock AI/Email/Calendar providers, zero external credentials needed | always (default `True`) |
| `ALLOW_PRIVILEGED_SELF_REGISTRATION` | Gates whether `/auth/register` can create anything but a PATIENT | always — **must stay `False`** outside tests, see [below](#creating-the-first-admin-account) |
| `CORS_ALLOWED_ORIGINS` | Comma-separated allow-list for the frontend origin | always |
| `AI_PROVIDER_*` | OpenAI-compatible LLM endpoint/key/model | `DEMO_MODE=False` |
| `SMTP_*`, `EMAIL_FROM_ADDRESS` | SMTP relay for real email | `DEMO_MODE=False` |
| `GOOGLE_*` | OAuth 2.0 client + refresh token for Calendar API | `DEMO_MODE=False` |
| `NOTIFICATION_MAX_ATTEMPTS`, `CALENDAR_MAX_ATTEMPTS` | Bounded retry counts | optional (sensible defaults) |
| `VITE_API_BASE_URL` | Frontend: backend origin in production (empty = same-origin/dev proxy) | production build |

Never commit a real `.env` — `.gitignore` excludes it; only `.env.example` files are tracked.

## DEMO_MODE

`DEMO_MODE=True` (the default) swaps every external provider for an in-memory mock:
`MockAIProvider` (keyword-based urgency, always schema-valid), `MockEmailProvider`
(records sends, never touches the network), `MockCalendarProvider` (in-memory event
store). The entire application — booking, AI summaries, notifications, calendar sync —
works end-to-end with zero external credentials. This is what every automated test and
the Phase 11 manual browser verification actually exercised. Flip to `DEMO_MODE=False`
only once real `AI_PROVIDER_*`/`SMTP_*`/`GOOGLE_*` credentials are configured.

## Creating the first admin account

**`POST /auth/register` only ever creates a PATIENT account** unless
`ALLOW_PRIVILEGED_SELF_REGISTRATION=True` (this was a real vulnerability found during
the Phase 13 security audit — see [Known limitations](#known-limitations)). There is no
API endpoint that creates the first admin. To bootstrap one:

```bash
cd backend
ALLOW_PRIVILEGED_SELF_REGISTRATION=True python -m uvicorn app.main:app
# in another terminal, once:
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@yourclinic.com","password":"<strong password>","full_name":"Admin","role":"ADMIN"}'
# then stop the server, remove the env var (or set it back to False), and restart.
```

Once that admin exists, they create every doctor account via
`POST /admin/doctors` (see [API documentation](#api-documentation)) — doctors never
self-register. There are no seeded/demo credentials checked into this repo; the database
itself is never committed (see `.gitignore`).

## API documentation

Full interactive OpenAPI docs are served by the running backend at
`/api/v1/docs` (Swagger UI) and `/api/v1/redoc`, generated directly from the Pydantic
schemas — always in sync with the code, unlike a hand-maintained list. The full requirement
→ endpoint → test mapping is in `docs/requirement-mapping.md`. Route summary:

| Area | Base path | Notes |
|---|---|---|
| Auth | `/api/v1/auth` | register (patient-only, see above), login, `me` |
| Doctors (public) | `/api/v1/doctors` | search, profile, schedule, leaves, slots |
| Slots & holds | `/api/v1/slots` | create/get/release a hold |
| Appointments | `/api/v1/appointments` | book, list, get, reschedule, cancel |
| AI & clinical | `/api/v1/appointments/{id}/...` | symptom-report, consultation, pre/post-visit AI summaries |
| Admin | `/api/v1/admin` | doctor CRUD, working hours, leave |

## Database schema

Full ERD, state machines, and constraints in `docs/database-design.md`. Core entities:
`User`, `Doctor` (+ `DoctorWorkingHours`, `DoctorLeave`), `Appointment` (+
`AppointmentHold`), `SymptomReport`, `AISummary`, `Consultation` (+ `Prescription`,
`Medication`), `NotificationJob`, `CalendarEvent`. Schema is entirely migration-driven —
4 Alembic revisions in `backend/alembic/versions/`, verified to apply cleanly from an
empty database (see [Running tests](#running-tests)).

The appointment state machine: `HELD → CONFIRMED → {RESCHEDULED, CANCELLED,
CONFLICTED, COMPLETED}`. Double-booking is prevented by a partial unique index
(`uq_doctor_profile_start_time_active` on `appointments(doctor_profile_id, start_time)`
filtered to active statuses) — the database, not the application, is the final authority.

## LLM prompts

Taken verbatim from `AGENT_SPEC.md`'s "LLM Usage Guidance" and implemented in
`backend/providers/ai_provider.py`:

**Pre-visit** — output validated against `{urgency: Low|Medium|High, chief_complaint: string, suggested_questions: [string, string, string]}`:
> Analyse these symptoms and return: urgency level (Low / Medium / High), chief complaint, and three suggested questions for the doctor. Symptoms: `{symptoms}`

**Post-visit** — output validated against `{summary, medication_schedule, follow_up_steps}`:
> Convert these clinical notes into a patient-friendly summary with medication schedule and follow-up steps: `{notes}`

Both are paired with a system prompt instructing the model to return only JSON of the
exact shape, no diagnosis, no text outside the JSON. Every response — real or mock — is
validated against a Pydantic schema before being trusted; a malformed or invalid
response is recorded as `AISummaryStatus.FAILED` and never raises past the API boundary.
Full design and failure-mode table in `docs/ai-design.md` and `docs/failure-handling.md`.

## Google Calendar & OAuth 2.0 setup

Full step-by-step (Cloud project, OAuth consent screen, obtaining a refresh token via
the OAuth 2.0 Playground) in `docs/google-calendar-setup.md`. Summary: create OAuth 2.0
credentials in Google Cloud Console, enable the Calendar API, obtain a refresh token
with the `calendar.events` scope, and set `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` /
`GOOGLE_REFRESH_TOKEN` with `DEMO_MODE=False`. Calendar sync is fully decoupled from the
booking transaction (see [Architecture](#architecture)) — a Google outage never blocks
or fails a booking.

## Running tests

```bash
cd backend
pip install -r requirements.txt
alembic upgrade head              # or let tests create their own in-memory DB — see below
python -m pytest tests/ -v
```

Tests use an isolated in-memory SQLite database (`tests/conftest.py`) — they do not
touch `DATABASE_URL`. **105 tests, 105 passing**, verified in a clean environment
(fresh-migrated DB, full verbose run) immediately before this document was written —
see `second-brain/04_TEST_STATUS.md` for the exact per-suite breakdown and the command
used. Frontend: `cd frontend && npm run typecheck && npm run build`.

## Deployment

**Not deployed.** This environment has no hosting-provider accounts or credentials, and
creating one is outside what an autonomous coding session can do on its own — see
`docs/deployment.md` for exactly what "done" looks like and the steps to get there
(Render/Railway for the backend + a managed Postgres, Vercel/Netlify for the frontend).
Both halves are deployment-ready today: the backend needs only `DATABASE_URL` +
`SECRET_KEY` (+ optionally real `AI_PROVIDER_*`/`SMTP_*`/`GOOGLE_*` credentials) and runs
`alembic upgrade head` then `uvicorn app.main:app`; the frontend is a static Vite build
(`npm run build` → `dist/`) needing only `VITE_API_BASE_URL` pointed at the deployed
backend. Neither requires code changes to deploy — see `docs/deployment.md`.

## Known limitations

The full list with reasoning is in `second-brain/05_KNOWN_ISSUES.md`, kept up to date
after every phase. Headlines:

- **`RealAIProvider`, `RealEmailProvider`, and `GoogleCalendarProvider` have never been
  exercised against a real LLM, SMTP server, or Google account** — no credentials exist
  in this environment. Every test and the manual browser verification ran against the
  Mock providers (`DEMO_MODE=True`). This is the single largest gap between
  "implemented" and "verified against the real thing."
- **A privilege-escalation vulnerability was found and fixed during the Phase 13
  security audit**: `POST /auth/register` accepted a caller-supplied `role`, including
  `ADMIN`, with no authentication. Now restricted to PATIENT-only by default
  (`ALLOW_PRIVILEGED_SELF_REGISTRATION`, see above). Regression test:
  `tests/test_auth.py::test_privileged_self_registration_rejected_by_default`.
- **Backend datetimes read back from the database are timezone-naive** (values
  generated in-memory carry a UTC offset; values round-tripped through the DB don't).
  The frontend works around this (`parseServerDate()`); the correct fix is backend-side
  and hasn't been made, to avoid touching code covered by 105 passing tests this late.
- **The 100-thread concurrency test doesn't prove true multi-connection safety** —
  SQLite forces serialization in-process. The independent, dialect-agnostic proof is the
  database unique-index test, which has also never run against live PostgreSQL.
- **A test-infrastructure bug**: the shared test-DB session doesn't fully roll back
  between tests when a test performs multiple commits, so committed rows can leak
  across tests. Attempted fix (SQLAlchemy SAVEPOINT pattern) broke the concurrency test
  and was reverted; affected tests were rewritten to use scoped/delta assertions instead.
- **Doctor-leave conflicts don't sync to the calendar** — Phase 10's stated scope was
  create/update/delete on booking/reschedule/cancellation only.
- No automated frontend test suite (not required by the phase spec; verification was
  manual-but-real, driving an actual browser against a live backend).

## Project status

All 13 phases in `AGENT_PHASES.md` are complete. **"Complete" here means:** every
requirement has real code, a real test, or documented manual verification behind it
(see `docs/requirement-mapping.md` — nothing is marked done without evidence), 105/105
backend tests pass in a freshly-migrated environment, the frontend builds and typechecks
cleanly, and a genuine security vulnerability found during the final audit was fixed and
covered by a regression test rather than just written up. It does **not** mean the app
has been deployed, or that the real (non-mock) AI/email/calendar providers have been
verified end-to-end — both are stated plainly above rather than implied.
