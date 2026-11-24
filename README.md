# Healthcare Appointment & Follow-up Manager

[![CI](https://github.com/SakthiQ/Healthcare-Appointment-Follow-up-Manager/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/SakthiQ/Healthcare-Appointment-Follow-up-Manager/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

An open-source project building toward a **scalable hospital management application with
AI built in**. It starts with the part of hospital work that patients feel most: booking a
visit, the consultation itself, and the follow-up afterwards.

Today it is a working clinic platform with separate portals for patients, doctors and
admins. Patients describe their symptoms before a visit, and AI turns them into a short
pre-visit summary for the doctor. Doctors record the consultation and prescription, and AI
turns their notes into a plain-language summary and medication schedule for the patient.
Email reminders and Google Calendar sync run in the background.

**Want to help?** Read [How to contribute](#how-to-contribute), then follow the
[local setup guide](docs/local-setup.md). You need no API keys or accounts to run it.

## Contents

- [The aim](#the-aim)
- [What it does today](#what-it-does-today)
- [Roadmap](#roadmap)
- [Quick start](#quick-start)
- [How to contribute](#how-to-contribute)
- [Project layout](#project-layout)
- [Architecture](#architecture)
- [Reference](#reference): [stack](#stack), [environment variables](#environment-variables),
  [DEMO_MODE](#demo_mode), [first admin](#creating-the-first-admin-account),
  [API](#api-documentation), [database](#database-schema), [LLM prompts](#llm-prompts),
  [Google Calendar](#google-calendar--oauth-20-setup), [tests](#running-tests),
  [deployment](#deployment), [capacity](#capacity)
- [Known limitations](#known-limitations)
- [Project status](#project-status)
- [License](#license)

## The aim

Hospitals and clinics lose a lot of staff time to scheduling, paperwork and chasing
follow-ups, and patients often leave a visit unsure what to do next. The long-term goal is an
open-source hospital management application that:

- **lets AI take on the paperwork around care, while people make the decisions.** AI
  summarises, sorts and reminds. It never diagnoses, and every AI answer is checked against a
  strict format before anyone sees it. If the AI fails, the care workflow carries on without it.
- **scales from one clinic to a whole hospital.** The API keeps no state between requests, so
  you can run more copies of it behind a load balancer. PostgreSQL is the single source of truth,
  and its constraints stop double bookings even when many people book at once.
- **keeps working when outside services fail.** AI, email and calendar calls happen after the
  record is saved, and they are retried in the background. A Google or email outage never
  stops a booking.
- **is safe with patient data by default.** It has role-based access, login throttling, rate
  limits, an audit log and invitation-only staff accounts, and it refuses to start in
  production with unsafe settings.
- **runs anywhere, for anyone.** With `DEMO_MODE` on, offline stand-ins replace every
  outside service, so a student on a laptop can run the whole system and its tests.
- **is built in the open,** through a maintainer-led process in which every change is
  reviewed and tested.

## What it does today

| Who | What they can do |
|---|---|
| **Patients** | Sign up, search doctors by specialty, see open slots, hold a slot while booking, book, reschedule and cancel. They describe symptoms before a visit, and afterwards they read a plain-language summary with a medication schedule and follow-up steps. |
| **Doctors** | See their appointments, read the AI pre-visit summary (urgency, main complaint, suggested questions), and record the consultation and prescription. Bookings sync to Google Calendar. |
| **Admins** | Manage doctors, working hours and leave, invite staff by email, resolve appointments that clash with leave, and review the dashboard and the audit log. |
| **Behind the scenes** | Background workers send confirmation and medication-reminder emails, sync calendars, release expired slot holds and clear out expired tokens and rate-limit counters. Failed jobs are retried a limited number of times. |

## Roadmap

The project grows in stages. Each piece of work becomes an issue before anyone starts on it.

**Done (v0.2):** appointments, the three portals, AI pre-visit and post-visit summaries,
email notifications, calendar sync, staff invitations, the audit log, security hardening,
load protection with automatic retry, and CI with PostgreSQL checks. Since then: search by
doctor name, a proper "appointment rescheduled" email, admin retry of failed jobs, and a
clean database for every backend test.

**Next (open issues you can ask for):** the [issues page](../../issues) always has the current
list. New contributors should start with [`good first issue`](../../labels/good%20first%20issue).

- *For patients:*
  - [#66](../../issues/66): see your whole visit history in one place
  - [#67](../../issues/67): record allergies and date of birth for your doctor
  - [#71](../../issues/71): join a waitlist for a fully booked day
  - [#72](../../issues/72): use the app in Tamil or Hindi
  - [#53](../../issues/53): a dark theme that follows the system setting
- *For doctors:*
  - [#68](../../issues/68): mark an appointment as a no-show
  - [#73](../../issues/73): an AI summary of the patient's previous visits
- *For admins and the hospital:*
  - [#70](../../issues/70): group doctors into departments
  - [#65](../../issues/65): a page to retry failed emails and calendar syncs
  - [#57](../../issues/57): CSV export of appointments
  - [#52](../../issues/52): clearer appointment emails with names, links and HTML
- *Frontend tests:*
  - [#35](../../issues/35): the booking page *(good first issue)*
  - [#36](../../issues/36): the doctor's appointment and consultation page *(good first issue)*
  - [#42](../../issues/42): the patient's doctor search and dashboard *(good first issue)*
- *Code quality:*
  - [#47](../../issues/47): ESLint for the frontend
- *Docs and setup:*
  - [#49](../../issues/49): check the local setup guide on macOS and Linux *(good first issue)*
  - [#55](../../issues/55): Docker Compose to run the whole app with one command

**Later (direction only, no issues yet):** these are ideas the project is heading towards, not
promises. Please don't open pull requests for them. If one interests you, start a
conversation with a [feature request](../../issues/new/choose).

- *Hospital scope:* wards and beds, and several branches in one system.
- *Clinical modules:* lab and imaging results, pharmacy stock, billing and insurance claims.
- *More AI help:* a guided symptom-intake chat, no-show prediction and smarter scheduling.
- *Running at scale:* separate worker processes, caching for busy read pages, and metrics
  and tracing for operators.

## Quick start

Requires Python 3.12+ and Node 22 LTS (22.22+) or 24 LTS. **New here? Follow the
step-by-step [local setup guide](docs/local-setup.md)**, which covers Windows, macOS and
Linux, demo accounts and troubleshooting.

```bash
# Backend
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt -c constraints.txt
cp .env.example .env            # defaults work out of the box (SQLite + DEMO_MODE=True)
alembic upgrade head
python -m scripts.seed_demo     # demo admin, doctor and patient (password: demo-password)
python -m uvicorn app.main:app --reload
# → http://localhost:8000 , docs at http://localhost:8000/api/v1/docs
```

```bash
# Frontend (separate terminal)
cd frontend
npm ci
cp .env.example .env            # defaults proxy to http://localhost:8000
npm run dev
# → http://localhost:5173
```

Sign in as `patient@demo.example.com`, `doctor@demo.example.com` or
`admin@demo.example.com` to try each portal.

> **Windows note:** if your checkout path contains `&`, `npm run` and `npx` fail to resolve
> module paths. Clone somewhere like `C:\dev\`, or run the tools directly, e.g.
> `node ./node_modules/vite/bin/vite.js build` (see `frontend/README.md`).

## How to contribute

Contributions are welcome through a **maintainer-led process**, similar to a Google Summer of
Code project. The maintainer ([@SakthiQ](https://github.com/SakthiQ)) opens and assigns
issues, contributors work on their own fork, and the maintainer reviews and merges every
pull request.

1. **Pick an issue.** Look for [`good first issue`](../../labels/good%20first%20issue) if
   you're new, or [`help wanted`](../../labels/help%20wanted) if you have some experience.
2. **Ask for it.** Comment on the issue with a line or two on how you'd approach it.
3. **Wait to be assigned,** then fork, set up with the [local setup guide](docs/local-setup.md),
   and branch from `main` (for example `35-booking-page-tests`).
4. **Make the change with tests.** Run the checks CI runs (see [Running tests](#running-tests)).
5. **Open a pull request** that says `Closes #<issue>`, and fill in the template.

You can also help without writing code. Report bugs with the bug template, suggest features
with the feature template, and fix unclear docs. If you found a mistake while following the
setup guide, that is worth an issue too.

Read [CONTRIBUTING.md](CONTRIBUTING.md) before starting, and follow the
[Code of Conduct](CODE_OF_CONDUCT.md). Report security problems through
[SECURITY.md](SECURITY.md), never in a public issue.

## Project layout

| Path | What lives there |
|---|---|
| `backend/app/api/` | Route handlers. They stay thin and only check input and call a service. |
| `backend/services/` | Business rules and transaction boundaries (booking, holds, consultations, admin). |
| `backend/repositories/` | Database access. |
| `backend/models/`, `backend/schemas/` | SQLAlchemy tables and Pydantic request and response shapes. |
| `backend/providers/` | AI, email and calendar integrations. Each has a real version and a mock version (`DEMO_MODE`). |
| `backend/workers/` | Background jobs: notifications, calendar sync, hold expiry and housekeeping. |
| `backend/alembic/versions/` | Database migrations. |
| `backend/scripts/` | `seed_demo`, `create_admin`, `verify_postgres`. |
| `backend/tests/` | pytest suite. |
| `frontend/src/pages/` | Pages for each portal (`patient/`, `doctor/`, `admin/`) and the account pages. |
| `frontend/src/api/client.ts` | Every API call the frontend makes. |
| `docs/` | Design notes: [architecture](docs/architecture.md), [system design](docs/system-design.md), [database](docs/database-design.md), [AI](docs/ai-design.md), [failure handling](docs/failure-handling.md), [decisions](docs/engineering-decisions.md), [deployment](docs/deployment.md). |

## Architecture

Full detail is in `docs/architecture.md` and `docs/database-design.md`. The short version:

```
frontend/  (React SPA)
   │  fetch, Bearer JWT (or an httpOnly cookie)
   ▼
backend/app/api/          thin route handlers, no business logic
   │
   ▼
backend/services/         business rules, transaction boundaries
   │                       AppointmentService imports NO provider, so the
   │                       booking transaction cannot touch an external service
   ▼
backend/repositories/     persistence
   │
   ▼
PostgreSQL

backend/providers/        AIProvider · EmailProvider · CalendarProvider
                           each: Real* (the actual service) + Mock* (DEMO_MODE)
backend/workers/          notification · calendar · hold expiry · housekeeping
                           poll for due jobs, call providers, retry with backoff
```

Every external call (LLM, email, Google Calendar) happens **after** the appointment
transaction has committed, in a separate best-effort step. If that step fails, the failure is
recorded on its own row and the appointment is untouched. See `docs/failure-handling.md` for
the full comparison table, and `docs/system-design.md` for how double bookings, leave
conflicts, slot holds and notifications are handled.

It is a modular monolith on purpose: no microservices, message broker or Kubernetes (see
`docs/engineering-decisions.md`). It scales by running more copies of the same process on
one PostgreSQL database. Modules get split out only when a real need appears.

## Reference

### Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12+ + FastAPI |
| Database | PostgreSQL (SQLite fallback for local dev/tests) |
| ORM / Migrations | SQLAlchemy 2 + Alembic |
| Validation | Pydantic |
| Auth | JWT (PyJWT) + bcrypt |
| Background jobs | Four simple polling workers: notifications, calendar, hold expiry, housekeeping (no broker/queue) |
| Frontend | React 19 + TypeScript + Vite, React Router, plain `fetch` |
| Testing | pytest (backend) and Vitest + Testing Library (frontend), run by CI. See [Running tests](#running-tests) |

### Environment variables

Every variable is documented inline in `backend/.env.example` and `frontend/.env.example`.
Summary:

| Variable | Purpose | Required when |
|---|---|---|
| `DATABASE_URL` | PostgreSQL (or SQLite) connection string | always |
| `SECRET_KEY` | JWT signing key | always. **Change it for any real deployment.** The app refuses to start with the default key when `ENVIRONMENT=production` |
| `DEMO_MODE` | `True` → Mock AI/Email/Calendar providers, zero external credentials needed | always (default `True`) |
| `ALLOW_PRIVILEGED_SELF_REGISTRATION` | Gates whether `/auth/register` can create anything but a PATIENT | always. **It must stay `False`** outside tests, see [below](#creating-the-first-admin-account) |
| `CORS_ALLOWED_ORIGINS` | Comma-separated allow-list for the frontend origin | always |
| `AI_DEMO_MODE`, `EMAIL_DEMO_MODE`, `CALENDAR_DEMO_MODE` | Per-integration override of `DEMO_MODE` (unset = follow it) | optional |
| `AI_PROVIDER_*` | OpenAI-compatible LLM endpoint/key/model (OpenAI, Gemini, Groq, …) | AI is real |
| `SMTP_*`, `EMAIL_FROM_ADDRESS` | SMTP relay for real email | email is real |
| `GOOGLE_*` | OAuth 2.0 client + refresh token for Calendar API | calendar is real |
| `NOTIFICATION_MAX_ATTEMPTS`, `CALENDAR_MAX_ATTEMPTS` | Bounded retry counts | optional (sensible defaults) |
| `RUN_WORKERS_IN_PROCESS`, `WORKER_POLL_INTERVAL_SECONDS` | Run the notification, calendar, hold-expiry and housekeeping workers on threads in the web process | `True` on hosts with no separate worker process (the Render blueprint sets it) |
| `MAX_CONCURRENT_REQUESTS`, `REQUEST_QUEUE_TIMEOUT_SECONDS`, `DB_POOL_*` | Requests one process works on at once, and its database connection pool | optional (12 / 2 s / 10 + 20), see [Capacity](#capacity) |
| `CLIENT_IP_HEADER`, `TRUSTED_PROXY_HOPS` | How to find the client's IP behind proxies | behind a proxy or CDN |
| `LOGIN_MAX_FAILED_ATTEMPTS`, `LOGIN_LOCKOUT_MINUTES` | Login throttling per (email, IP) | optional (5 / 15) |
| `AI_MAX_SUMMARIES_PER_APPOINTMENT` | Cap on AI summaries per appointment and type | optional (10) |
| `RATE_LIMITING_ENABLED`, `REGISTER_RATE_LIMIT_PER_HOUR`, `AI_RATE_LIMIT_PER_HOUR`, `PASSWORD_RESET_RATE_LIMIT_PER_HOUR`, `PASSWORD_RESET_EMAIL_RATE_LIMIT_PER_HOUR`, `AUTH_TOKEN_RATE_LIMIT_PER_HOUR`, `CHANGE_PASSWORD_RATE_LIMIT_PER_HOUR` | Request limits (fixed one-hour windows, kept in the database) | optional (10 / 30 / 5 / 3 / 30 / 10 per hour) |
| `FRONTEND_BASE_URL` | Origin that password-reset, verification and invitation links point to | **production** (default is `http://localhost:5173`) |
| `REQUIRE_EMAIL_VERIFICATION` | Refuse login until the email address is verified | optional (default `False`, so the demo flow works) |
| `PASSWORD_RESET_TOKEN_TTL_MINUTES`, `EMAIL_VERIFICATION_TOKEN_TTL_HOURS`, `INVITATION_TTL_DAYS` | How long the emailed links work | optional (30 min / 24 h / 7 days) |
| `INVITE_RATE_LIMIT_PER_HOUR` | Invitations one admin may send per hour | optional (30) |
| `AUTH_COOKIE_MODE`, `VITE_AUTH_COOKIES` (frontend build) | Session in an httpOnly cookie instead of `localStorage` | optional; same-site deployments only, see [docs/system-design.md](docs/system-design.md) |
| `CONSULTATION_EARLY_SUBMIT_MINUTES` | Reject consultations recorded too long before the appointment | optional; unset for the demo flow |
| `NOTIFICATION_PROCESSING_TIMEOUT_MINUTES` | When a job abandoned by a crashed worker goes back in the queue | optional (default 30) |
| `VITE_API_BASE_URL` | Frontend: backend origin in production (empty = same-origin/dev proxy) | production build |

Never commit a real `.env`. `.gitignore` excludes it, and only the `.env.example` files are
tracked. Hosted deployments keep their secrets in the host's dashboard, so contributors
never see them.

### DEMO_MODE

`DEMO_MODE=True` (the default) swaps every external provider for an in-memory mock:

- `MockAIProvider` judges urgency from keywords and always returns a valid answer.
- `MockEmailProvider` records what would have been sent and never touches the network.
- `MockCalendarProvider` keeps events in memory.

Booking, AI summaries, notifications and calendar sync all work end to end with no external
credentials, and every automated test runs this way. Set `DEMO_MODE=False` only once real
`AI_PROVIDER_*`, `SMTP_*` and `GOOGLE_*` credentials are configured. You can also switch one
integration at a time with `AI_DEMO_MODE`, `EMAIL_DEMO_MODE` or `CALENDAR_DEMO_MODE`. For
example, `AI_DEMO_MODE=False` uses a real LLM while email and calendar stay mocked.

`GET /health` reports the setting each integration ends up with, as `ai_provider`,
`email_provider` and `calendar_provider` (`"mock"` or `"real"`), and those values are the
ones to trust. Its `demo_mode` field shows only the global `DEMO_MODE` default, so it can read
`true` while one integration is real.

With a real LLM, the post-visit medication schedule is checked against the prescription. If
the schedule leaves out a prescribed medication or gives it no dosage of its own, the summary
is stored as `FAILED` instead of being shown to the patient, and the doctor can regenerate it.

### Creating the first admin account

**`POST /auth/register` only ever creates a PATIENT account** unless
`ALLOW_PRIVILEGED_SELF_REGISTRATION=True`. No API endpoint creates the first admin. Create
one directly in the database with the bundled script, which works against local SQLite or a
hosted Postgres through `DATABASE_URL`:

```bash
cd backend
python -m scripts.create_admin --email admin@yourclinic.com --name "Clinic Admin"
# prompts for the password (hidden); or set ADMIN_PASSWORD
```

Once that admin exists, they bring in staff in one of two ways (see
[API documentation](#api-documentation)). Doctors and admins never choose their own role.

- **Invite by email (recommended).** *Invitations* in the admin portal (or
  `POST /admin/invitations`) emails a single-use link to `/register?invite=…`. The invitee
  opens the **same signup page patients use** and chooses a password. The account gets the
  role stored in the invitation, and for a doctor also the specialisation, slot length and
  timezone. Nothing on the form can change them. Links expire after `INVITATION_TTL_DAYS`
  (7), work once, and are stored only as a hash. If email is not set up, the admin sees the
  link once and can hand it over.
- **Create directly.** `POST /admin/doctors` creates a doctor with a temporary password.

The only built-in accounts are the local demo ones from `python -m scripts.seed_demo`. That
script refuses to run when `ENVIRONMENT=production` or `DEMO_MODE` is off. The database is
never committed (see `.gitignore`).

### API documentation

The running backend serves full interactive OpenAPI docs at `/api/v1/docs` (Swagger UI) and
`/api/v1/redoc`. They are generated from the Pydantic schemas, so they always match the code.
The full requirement → endpoint → test mapping is in `docs/requirement-mapping.md`. Route
summary:

| Area | Base path | Notes |
|---|---|---|
| Auth | `/api/v1/auth` | register (patients, or anyone holding an invitation link; rate-limited), `invitations/lookup`, login (throttled), logout, `me`, change-password, forgot-password, reset-password, verify-email, resend-verification |
| Doctors (public) | `/api/v1/doctors` | search, profile, schedule, leaves, slots |
| Slots & holds | `/api/v1/slots` | create/get/release a hold |
| Appointments | `/api/v1/appointments` | book, list, get, reschedule, cancel |
| AI & clinical | `/api/v1/appointments/{id}/...` | symptom-report, consultation, pre/post-visit AI summaries |
| Admin | `/api/v1/admin` | doctor CRUD, working hours, leave, staff invitations (`/admin/invitations`), audit log (`GET /admin/audit-logs`), failed email and calendar jobs (`GET /admin/failed-jobs`, `POST .../retry`) |

### Database schema

The full ERD, state machines and constraints are in `docs/database-design.md`. Core entities:
`User`, `Doctor` (+ `DoctorWorkingHours`, `DoctorLeave`), `Appointment` (+
`AppointmentHold`), `SymptomReport`, `AISummary`, `Consultation` (+ `Prescription`,
`Medication`), `NotificationJob`, `CalendarEvent`, plus `AuthToken` (password-reset and
verification links), `Invitation` (staff signup links), `AuditLog`, `RateLimit` and
`LoginThrottle`. The schema comes entirely from migrations: 11 Alembic revisions in
`backend/alembic/versions/`, which CI applies to an empty database.

The appointment state machine is `HELD → CONFIRMED → {RESCHEDULED, CANCELLED,
CONFLICTED, COMPLETED}`. A partial unique index
(`uq_doctor_profile_start_time_active` on `appointments(doctor_profile_id, start_time)`,
filtered to active statuses) prevents double bookings, so the database has the final say,
not the application.

### LLM prompts

These prompts come word for word from the original project brief and are implemented in
`backend/providers/ai_provider.py`.

**Pre-visit.** The output must match `{urgency: Low|Medium|High, chief_complaint: string, suggested_questions: [string, string, string]}`:
> Analyse these symptoms and return: urgency level (Low / Medium / High), chief complaint, and three suggested questions for the doctor. Symptoms: `{symptoms}`

**Post-visit.** The output must match `{summary, medication_schedule, follow_up_steps}`:
> Convert these clinical notes into a patient-friendly summary with medication schedule and follow-up steps: `{notes}`

Both come with a system prompt that tells the model to return only JSON of exactly that
shape, with no diagnosis and no text outside the JSON. Every response, real or mock, is
checked against a Pydantic schema before it is used. A malformed or invalid response is
recorded as `AISummaryStatus.FAILED` and never raises an error past the API boundary. The full
design and failure-mode table are in `docs/ai-design.md` and `docs/failure-handling.md`.

### Google Calendar & OAuth 2.0 setup

The step-by-step guide is in `docs/google-calendar-setup.md`. It covers the Cloud project,
the OAuth consent screen and getting a refresh token from the OAuth 2.0 Playground. In short:

1. Create OAuth 2.0 credentials in Google Cloud Console and enable the Calendar API.
2. Get a refresh token with the `calendar.events` scope.
3. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `GOOGLE_REFRESH_TOKEN`, and set
   `CALENDAR_DEMO_MODE=False` (or `DEMO_MODE=False`).

Calendar sync runs separately from the booking transaction (see [Architecture](#architecture)),
so a Google outage never blocks or fails a booking.

### Running tests

```bash
# Backend
cd backend
pip install -r requirements.txt -c constraints.txt   # exact, tested versions; see docs/deployment.md
python -m pytest -q

# Frontend
cd frontend
npm ci
npm run typecheck && npm test && npm run build
```

Backend tests use their own in-memory SQLite database (`tests/conftest.py`), not
`DATABASE_URL`. At the last full run, **all 284 backend tests and 122 frontend tests
passed**.

SQLite has no row locks, exclusion constraints or real concurrency. A separate script,
`python backend/scripts/verify_postgres.py`, proves the PostgreSQL-only guarantees against a
real server: the overlap constraint, one winner when bookings race, locking between leave and
bookings, and the rate limiter under concurrency. It wipes the database you point it at, so
see `docs/deployment.md` first. On every push and pull request, **CI**
(`.github/workflows/ci.yml`) runs the backend tests, that script against a PostgreSQL service
container, and the frontend typecheck, tests and build.

### Deployment

The repository has ready-made config for **Neon** (Postgres), **Render** (backend,
`render.yaml`) and **Vercel** (frontend, `frontend/vercel.json`).
[`docs/deployment.md`](docs/deployment.md) has the step-by-step guide, including how to
create the first admin on the hosted database. The frontend works only once
`VITE_API_BASE_URL` points at a deployed backend. Without it, every API call returns
"Not found."

### Capacity

One web process works on `MAX_CONCURRENT_REQUESTS` (12) requests at once. A request beyond
that waits up to 2 seconds, then gets a quick `503 Server busy` answer, and the frontend retries
it automatically. The server never stalls under a burst. In a local load test with the
production settings (`backend/scripts/load_test.py`), one process served **600 signed-in users
browsing at once** at 266 requests a second, with 95% of responses under 51 ms and no errors.
When 100 patients raced for the same slot, exactly one got it. To handle more traffic, run more
processes or instances on PostgreSQL; [docs/deployment.md](docs/deployment.md#capacity-and-scaling)
explains how.

## Known limitations

Each limitation comes with the reason for it, and some link to the open issue that addresses it.

- **The real AI, email and Google Calendar providers have never been tested against a real
  LLM, SMTP server or Google account**, because this environment has no credentials for them.
  Every test runs against the mock providers. This is the biggest gap between
  "implemented" and "verified against the real thing".
- **SQLite tests can't prove multi-connection safety.** SQLite runs everything one at a time
  in-process. The real proof is `backend/scripts/verify_postgres.py`, which CI runs against
  PostgreSQL.
- **The audit log is kept forever by default.** Audit writes are best-effort: a failed write is
  logged and the request carries on, so a problem with the audit table can't take patient care
  offline. Entries are never edited. Set `AUDIT_LOG_RETENTION_DAYS` (30 or more) to have the
  maintenance worker delete older entries; see [docs/deployment.md](docs/deployment.md).
- **Email verification is off by default** (`REQUIRE_EMAIL_VERIFICATION=False`) so the
  demo flow works. Real password-reset and verification emails need real SMTP.
- **The booking and consultation pages have no component tests.** They were checked by hand
  in a browser. → [#35](../../issues/35), [#36](../../issues/36)

## Project status

**Version 0.2.0.** Every requirement of the original brief has code and a test or a documented
manual check behind it (see `docs/requirement-mapping.md`), and CI passes on `main`. A
privilege-escalation bug found in a security audit (`/auth/register` accepted `role=ADMIN`)
was fixed and has a regression test. What hasn't been verified yet is a long-running hosted
deployment with the real AI, email and calendar providers. The [Roadmap](#roadmap) shows where
the project goes from here.

## License

[MIT](LICENSE)
