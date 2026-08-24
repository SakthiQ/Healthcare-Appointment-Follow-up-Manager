# 03 - Progress Tracker

## Current State
- **Current Phase:** Final release-engineer red-team audit complete (post-Phase-13). All 14 phases (0-13) of AGENT_PHASES.md are done. This pass adversarially re-verified prior work rather than trusting it — see 04/05 for what was actually re-tested and what was found.
- **Two more test gaps found and closed this pass:** no test exercised an expired JWT specifically (only missing/wrong-password auth), and no test proved job durability across a simulated backend restart. Both added with passing regression tests (`test_auth.py::test_expired_token_rejected`, `test_e2e.py::test_e2e_backend_restart_with_pending_jobs`).
- **Submission-readiness gap found, not fixed:** the repository has **zero git commits** (`git log` confirms "does not have any commits yet") — everything is untracked working-tree content. Not something to fix without being asked (git commits require explicit user instruction).
- **Completed Phases:**
  - [x] Phase 0 — Architecture & Planning (Docs created in `docs/`)
  - [x] Phase 1 — Project Foundation (FastAPI app, config, DB connection, Alembic setup, logging, exception handlers, health API, test suite)
  - [x] Phase 2 — Database & Domain Models (13 domain entities, enums, relationships, indexes, constraints, Alembic migration, model tests)
  - [x] Phase 3 — Authentication & RBAC (Bcrypt password hashing, JWT authentication, patient/doctor/admin registration, login API, server-side RBAC dependencies, resource ownership check)
  - [x] Phase 4 — Doctor & Schedule Management (`DoctorService`, `ScheduleService`, `LeaveService`, Admin CRUD APIs, specialization search, working hours & slot duration validation, leave management)
  - [x] Phase 5 — Slot Engine & Slot Holds (`SlotService`, `HoldService`, slot interval generation, leave/hold/booking exclusions, hold expiration, hold confirmation validation)
  - [x] Phase 6 — Appointment Booking, Rescheduling, Cancellation & Concurrency (`AppointmentService`, appointments API, 100-simultaneous-booking test). Hardened on 2026-08-23: added a DB-level partial unique index (`uq_doctor_profile_start_time_active`, migration `f39781a8abe6`) as the true final-authority double-booking guard, closed an app-lock gap on the hold-confirmation booking path, and added regression tests for expired-hold booking attempts and reschedule non-duplication. See `05_KNOWN_ISSUES.md` for what is still open.
  - [x] Phase 7 — AI Pre-Visit & Post-Visit System (`AIProvider`/`RealAIProvider`/`MockAIProvider`, `AIService`, strict Pydantic output contracts, graceful failure handling, `docs/ai-design.md`). Also added the minimal symptom-report and consultation/prescription intake endpoints needed to feed the AI (no dedicated phase covers this elsewhere, and Phase 9's medication reminders need `Prescription`/`Medication` rows to exist).
  - [x] Phase 8 — Doctor Leave & Conflict Handling (`DoctorLeaveService`, transactional leave creation: detects overlapping active appointments, marks them `CONFLICTED` without deleting anything, queues `DOCTOR_LEAVE_CONFLICT` notification jobs — no email delivery, that's Phase 9). `POST /admin/doctors/{id}/leaves` now routes through it instead of the old `LeaveService.create_leave` (removed — superseded).
  - [x] Phase 9 — Notifications, Email Retries & Medication Reminders (`NotificationService`, `NotificationJobRepository`, `NotificationWorker`, `EmailProvider`/`RealEmailProvider`(SMTP)/`MockEmailProvider`, `ReminderService`). Booking confirmation, cancellation, appointment reminders, and medication reminders now all queue real `NotificationJob` rows; `NotificationWorker.run_once()` claims due jobs and sends via the active `EmailProvider` with bounded retry (`NOTIFICATION_MAX_ATTEMPTS`, exponential backoff capped at 60min). `DoctorLeaveService` (Phase 8) refactored to queue through `NotificationService` instead of the repository directly, for consistency.

  - [x] Phase 10 — Google Calendar Integration (`CalendarProvider`/`GoogleCalendarProvider`(OAuth 2.0 refresh-token flow)/`MockCalendarProvider`, `CalendarService`, `CalendarEventRepository`, `CalendarWorker`). Create on booking, update on reschedule, delete on cancellation — all armed as local `CalendarEvent` rows post-commit and pushed later by the worker, never inline. Migration `21a72a0914c8` adds `pending_operation`/`idempotency_key`/`attempts`/`next_retry_at`/`last_error` + `UniqueConstraint(appointment_id, recipient_type)`. Docs: `docs/google-calendar-setup.md`.

  - [x] Phase 11 — Frontend: Patient, Doctor & Admin Portals (React 18 + TypeScript + Vite in `frontend/`). All three portals against real APIs; role-based nav + route guards; UTC-safe date handling; real backend error messages surfaced. Verified end-to-end in a real browser against a live backend, not just built. See `frontend/README.md`.

  - [x] Phase 12 — Integration & End-to-End Testing (`tests/test_e2e.py`, 13 tests). All 5 required workflows + 6 failure scenarios driven through the HTTP API, asserting HTTP response, DB state, authorization, background jobs, provider interaction, and resulting state. **Found and fixed a real gap: reschedule created no notifications** and stale reminders for the old time stayed pending. Architectural criteria audited (no route bypasses services; only AI/calendar/notification services import providers; `AppointmentService` imports none).

  - [x] Phase 13 — Final Audit, Documentation, Security & Deployment. Requirement/code-quality/security/reliability audits done. **Found and fixed a critical vulnerability**: `POST /auth/register` accepted a caller-supplied `role` including `ADMIN` with zero authentication — now gated by `ALLOW_PRIVILEGED_SELF_REGISTRATION` (default False), with a regression test. Also fixed a CORS misconfiguration (`allow_origins=["*"]` + `allow_credentials=True`). Created root `README.md`, `docs/failure-handling.md`, `docs/requirement-mapping.md`, `docs/deployment.md`, root `.gitignore` (didn't exist before). Fixed documentation drift in `docs/architecture.md` (module-structure sections described the Phase 0 plan, not what was actually built). Full suite re-verified clean (105/105) from a freshly-migrated DB. **Deployment not done** — no hosting credentials in this environment; `docs/deployment.md` has the exact steps.

## Execution Roadmap
- [x] Phase 1 — Project Foundation
- [x] Phase 2 — Database & Domain Models
- [x] Phase 3 — Authentication & RBAC
- [x] Phase 4 — Doctor & Schedule Management
- [x] Phase 5 — Slot Engine & Slot Holds
- [x] Phase 6 — Appointment Booking, Rescheduling, Cancellation & Concurrency
- [x] Phase 7 — AI Pre-Visit & Post-Visit System
- [x] Phase 8 — Doctor Leave & Conflict Handling
- [x] Phase 9 — Notifications, Email Retries & Medication Reminders
- [x] Phase 10 — Google Calendar Integration
- [x] Phase 11 — Frontend: Patient, Doctor & Admin Portals
- [x] Phase 12 — Integration & End-to-End Testing
- [x] Phase 13 — Final Audit, Documentation, Security & Deployment (docs/audits done, deployment not done)

## Next Action
- All 14 phases done. Remaining work is entirely deployment: create hosting accounts (Render/Railway + Postgres for backend, Vercel/Netlify for frontend) and follow `docs/deployment.md`. This requires the user's credentials/accounts — an autonomous session cannot do it.
- If asked to continue improving the app: `second-brain/05_KNOWN_ISSUES.md` has the full prioritized list (backend timezone-naive datetimes is the most impactful remaining item; the others are "unverified against a real external service" caveats that only matter once real credentials exist).





