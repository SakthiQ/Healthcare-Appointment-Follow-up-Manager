# Healthcare Appointment & Follow-up Manager

A clinic booking platform with separate patient, doctor, and admin portals. Patients
share symptoms before a visit and get an AI-generated pre-visit summary for the doctor;
doctors record consultations and prescriptions and get an AI-generated post-visit
summary for the patient; both sides get email notifications and Google Calendar sync;
medication reminders are scheduled automatically from the prescription.

Built in 13 phases against the original project brief. All
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
| Background jobs | Four simple polling workers: notifications, calendar, hold expiry, housekeeping (no broker/queue) |
| Frontend | React 18 + TypeScript + Vite, React Router, plain `fetch` |
| Testing | pytest (backend) and Vitest + Testing Library (frontend), run by CI — see [Running tests](#running-tests) |

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
| `SECRET_KEY` | JWT signing key | always — **change for any real deployment**; the app refuses to start with the default key when `ENVIRONMENT=production` |
| `DEMO_MODE` | `True` → Mock AI/Email/Calendar providers, zero external credentials needed | always (default `True`) |
| `ALLOW_PRIVILEGED_SELF_REGISTRATION` | Gates whether `/auth/register` can create anything but a PATIENT | always — **must stay `False`** outside tests, see [below](#creating-the-first-admin-account) |
| `CORS_ALLOWED_ORIGINS` | Comma-separated allow-list for the frontend origin | always |
| `AI_DEMO_MODE`, `EMAIL_DEMO_MODE`, `CALENDAR_DEMO_MODE` | Per-integration override of `DEMO_MODE` (unset = follow it) | optional |
| `AI_PROVIDER_*` | OpenAI-compatible LLM endpoint/key/model (OpenAI, Gemini, Groq, …) | AI is real |
| `SMTP_*`, `EMAIL_FROM_ADDRESS` | SMTP relay for real email | email is real |
| `GOOGLE_*` | OAuth 2.0 client + refresh token for Calendar API | calendar is real |
| `NOTIFICATION_MAX_ATTEMPTS`, `CALENDAR_MAX_ATTEMPTS` | Bounded retry counts | optional (sensible defaults) |
| `RUN_WORKERS_IN_PROCESS`, `WORKER_POLL_INTERVAL_SECONDS` | Run the notification, calendar, hold-expiry and housekeeping workers on threads in the web process | `True` on hosts with no separate worker process (the Render blueprint sets it) |
| `LOGIN_MAX_FAILED_ATTEMPTS`, `LOGIN_LOCKOUT_MINUTES` | Login throttling per (email, IP) | optional (5 / 15) |
| `AI_MAX_SUMMARIES_PER_APPOINTMENT` | Cap on AI summaries per appointment and type | optional (10) |
| `RATE_LIMITING_ENABLED`, `REGISTER_RATE_LIMIT_PER_HOUR`, `AI_RATE_LIMIT_PER_HOUR`, `PASSWORD_RESET_RATE_LIMIT_PER_HOUR`, `PASSWORD_RESET_EMAIL_RATE_LIMIT_PER_HOUR`, `AUTH_TOKEN_RATE_LIMIT_PER_HOUR`, `CHANGE_PASSWORD_RATE_LIMIT_PER_HOUR` | Request limits (fixed one-hour windows, kept in the database) | optional (10 / 30 / 5 / 3 / 30 / 10 per hour) |
| `FRONTEND_BASE_URL` | Origin the password-reset and email-verification links point at | **production** (default is `http://localhost:5173`) |
| `REQUIRE_EMAIL_VERIFICATION` | Refuse login until the email address is verified | optional (default `False`, so the demo flow works) |
| `PASSWORD_RESET_TOKEN_TTL_MINUTES`, `EMAIL_VERIFICATION_TOKEN_TTL_HOURS`, `INVITATION_TTL_DAYS` | How long the emailed links work | optional (30 min / 24 h / 7 days) |
| `INVITE_RATE_LIMIT_PER_HOUR` | Invitations one admin may send per hour | optional (30) |
| `AUTH_COOKIE_MODE`, `VITE_AUTH_COOKIES` (frontend build) | Session in an httpOnly cookie instead of `localStorage` | optional; same-site deployments only, see [docs/system-design.md](docs/system-design.md) |
| `CONSULTATION_EARLY_SUBMIT_MINUTES` | Reject consultations recorded too long before the appointment | optional; unset for the demo flow |
| `NOTIFICATION_PROCESSING_TIMEOUT_MINUTES` | When a job abandoned by a crashed worker goes back in the queue | optional (default 30) |
| `VITE_API_BASE_URL` | Frontend: backend origin in production (empty = same-origin/dev proxy) | production build |

Never commit a real `.env` — `.gitignore` excludes it; only `.env.example` files are tracked.

## DEMO_MODE

`DEMO_MODE=True` (the default) swaps every external provider for an in-memory mock:
`MockAIProvider` (keyword-based urgency, always schema-valid), `MockEmailProvider`
(records sends, never touches the network), `MockCalendarProvider` (in-memory event
store). The entire application — booking, AI summaries, notifications, calendar sync —
works end-to-end with zero external credentials. This is what every automated test and
the Phase 11 manual browser verification actually exercised. Flip to `DEMO_MODE=False`
only once real `AI_PROVIDER_*`/`SMTP_*`/`GOOGLE_*` credentials are configured — or switch
one integration at a time with `AI_DEMO_MODE`, `EMAIL_DEMO_MODE` or `CALENDAR_DEMO_MODE`
(e.g. `AI_DEMO_MODE=False` for a real LLM while email and calendar stay mocked).

`GET /health` reports the result per integration as `ai_provider`, `email_provider` and
`calendar_provider` (`"mock"` or `"real"`) — those are authoritative. Its `demo_mode` field
is only the global `DEMO_MODE` default, so it can read `true` while one integration is real.

With a real LLM, the post-visit medication schedule is checked against the prescription:
if it omits a prescribed medication or doesn't give it its own dosage, the summary is stored as `FAILED`
(the doctor can regenerate) rather than shown to the patient.

## Creating the first admin account

**`POST /auth/register` only ever creates a PATIENT account** unless
`ALLOW_PRIVILEGED_SELF_REGISTRATION=True` (this was a real vulnerability found during
the Phase 13 security audit — see [Known limitations](#known-limitations)). There is no
API endpoint that creates the first admin. Create one directly in the database with the
bundled script (works against local SQLite or a hosted Postgres via `DATABASE_URL`):

```bash
cd backend
python -m scripts.create_admin --email admin@yourclinic.com --name "Clinic Admin"
# prompts for the password (hidden); or set ADMIN_PASSWORD
```

Once that admin exists, they bring in staff in one of two ways (see
[API documentation](#api-documentation)) — doctors and admins never pick their own role:

- **Invite by email (recommended).** *Invitations* in the admin portal (or
  `POST /admin/invitations`) emails a single-use link to `/register?invite=…`. The invitee
  opens the **same signup page patients use**, chooses a password, and the account is created
  with the role (and, for a doctor, the specialisation, slot length and timezone) stored in the
  invitation. Nothing on the form can change it. Links expire after `INVITATION_TTL_DAYS`
  (7), work once, and are stored only as a hash. If email is not set up, the admin is shown the
  link once to hand over.
- **Create directly.** `POST /admin/doctors` creates a doctor with a temporary password.

There are no seeded/demo credentials checked into this repo; the database itself is never
committed (see `.gitignore`).

## API documentation

Full interactive OpenAPI docs are served by the running backend at
`/api/v1/docs` (Swagger UI) and `/api/v1/redoc`, generated directly from the Pydantic
schemas — always in sync with the code, unlike a hand-maintained list. The full requirement
→ endpoint → test mapping is in `docs/requirement-mapping.md`. Route summary:

| Area | Base path | Notes |
|---|---|---|
| Auth | `/api/v1/auth` | register (patients, or anyone holding an invitation link; rate-limited), `invitations/lookup`, login (throttled), logout, `me`, change-password, forgot-password, reset-password, verify-email, resend-verification |
| Doctors (public) | `/api/v1/doctors` | search, profile, schedule, leaves, slots |
| Slots & holds | `/api/v1/slots` | create/get/release a hold |
| Appointments | `/api/v1/appointments` | book, list, get, reschedule, cancel |
| AI & clinical | `/api/v1/appointments/{id}/...` | symptom-report, consultation, pre/post-visit AI summaries |
| Admin | `/api/v1/admin` | doctor CRUD, working hours, leave, staff invitations (`/admin/invitations`), audit log (`GET /admin/audit-logs`) |

## Database schema

Full ERD, state machines, and constraints in `docs/database-design.md`. Core entities:
`User`, `Doctor` (+ `DoctorWorkingHours`, `DoctorLeave`), `Appointment` (+
`AppointmentHold`), `SymptomReport`, `AISummary`, `Consultation` (+ `Prescription`,
`Medication`), `NotificationJob`, `CalendarEvent`, plus `AuthToken` (password-reset and
verification links), `Invitation` (staff signup links), `AuditLog`, `RateLimit` and `LoginThrottle`. Schema is entirely migration-driven —
9 Alembic revisions in `backend/alembic/versions/`, verified to apply cleanly from an
empty database (see [Running tests](#running-tests)).

The appointment state machine: `HELD → CONFIRMED → {RESCHEDULED, CANCELLED,
CONFLICTED, COMPLETED}`. Double-booking is prevented by a partial unique index
(`uq_doctor_profile_start_time_active` on `appointments(doctor_profile_id, start_time)`
filtered to active statuses) — the database, not the application, is the final authority.

## LLM prompts

Taken verbatim from the original project brief's "LLM Usage Guidance" and implemented in
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
`GOOGLE_REFRESH_TOKEN` with `CALENDAR_DEMO_MODE=False` (or `DEMO_MODE=False`). Calendar sync is fully decoupled from the
booking transaction (see [Architecture](#architecture)) — a Google outage never blocks
or fails a booking.

## Running tests

```bash
# Backend
cd backend
pip install -r requirements.txt -c constraints.txt   # exact, tested versions; see docs/deployment.md
python -m pytest tests/ -v

# Frontend
cd frontend
npm ci
npm run typecheck && npm test && npm run build
```

Backend tests use an isolated in-memory SQLite database (`tests/conftest.py`), not
`DATABASE_URL`. **249 backend tests and 104 frontend tests, all passing** on the last
full run.

SQLite has no row locks, exclusion constraints or real concurrency, so the PostgreSQL-only
guarantees (overlap constraint, one winner under concurrent bookings, leave vs. booking
locking, the rate limiter under concurrency) are proven by a separate script against a real
server: `python backend/scripts/verify_postgres.py` (it wipes the database you point it at;
see `docs/deployment.md`). **CI** (`.github/workflows/ci.yml`) runs the backend tests, that
script against a PostgreSQL service container, and the frontend typecheck, tests and build on
every push and pull request.

> **Windows note:** if the checkout path contains `&`, `npm run` fails. Call the tools
> directly: `node node_modules/vitest/vitest.mjs run`, `node node_modules/typescript/bin/tsc --noEmit`.

## Deployment

Ready-made config for **Neon** (Postgres) → **Render** (backend, `render.yaml`) →
**Vercel** (frontend, `frontend/vercel.json`). Step-by-step guide, including creating the
first admin on the hosted database: [`docs/deployment.md`](docs/deployment.md). The
frontend only works once `VITE_API_BASE_URL` points at a deployed backend — without it,
every API call returns "Not found."

## Known limitations

Each entry gives the reasoning behind it.

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
- **The 100-thread concurrency test doesn't prove true multi-connection safety** —
  SQLite forces serialization in-process. The real proof is `backend/scripts/verify_postgres.py`
  (concurrent bookings and holds, the overlap constraint, leave-vs-booking locking), which
  passed against a real PostgreSQL. One part, the per-doctor `btree_gist` constraint, needs a
  server with that extension; CI's PostgreSQL job exercises it.
- **A test-infrastructure bug**: the shared test-DB session doesn't fully roll back
  between tests when a test performs multiple commits, so committed rows can leak
  across tests. Attempted fix (SQLAlchemy SAVEPOINT pattern) broke the concurrency test
  and was reverted; affected tests were rewritten to use scoped/delta assertions instead.
- **No way to retry a `FAILED` notification job** — once a job exhausts its retries
  it stays `FAILED`; an operator must reset `status`/`attempts` in the database by hand
  (no admin endpoint exists). See `docs/failure-handling.md`.
- **The audit log is best-effort and has no retention policy.** A failed audit write is
  logged at ERROR and the request carries on (so an audit-table problem cannot take patient
  care offline); the application never updates or deletes entries, but how long to keep them
  is a policy decision the code does not make.
- **Email verification is not enforced by default** (`REQUIRE_EMAIL_VERIFICATION=False`) so
  the demo flow works; real password-reset and verification emails need real SMTP. In demo
  mode the links appear in the logs only at `LOG_LEVEL=DEBUG`.
- **Frontend tests cover the API client, auth context, layout, routing, login, the account
  flows and the audit log**; the booking and consultation pages have no component tests (they
  were verified by hand in a real browser).

## Project status

All 13 build phases are complete. **"Complete" here means:** every
requirement has real code, a real test, or documented manual verification behind it
(see `docs/requirement-mapping.md` — nothing is marked done without evidence), 249/249
backend tests pass in a freshly-migrated environment, the frontend builds and typechecks
cleanly, and a genuine security vulnerability found during the final audit was fixed and
covered by a regression test rather than just written up. It does **not** mean the app
has been deployed, or that the real (non-mock) AI/email/calendar providers have been
verified end-to-end — both are stated plainly above rather than implied.
