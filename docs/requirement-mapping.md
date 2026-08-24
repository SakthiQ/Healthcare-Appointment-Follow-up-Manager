# Requirement Mapping (Phase 13 — Evidence-Based)

This supersedes `docs/requirement-map.md`, which was written at Phase 0 as a *plan*
before any code existed (several endpoint paths and test names in it never matched what
was actually built). Every row below cites a real file, a real API path, and a real test
that exists in the repository today — verified by re-running the full suite
(104/104 passing, see `second-brain/04_TEST_STATUS.md`) immediately before writing this.

Status legend: ✅ Done & tested · ⚠️ Done, but with a caveat (see Notes) · ❌ Not implemented

| # | Requirement (from AGENT_SPEC.md) | Module | API / Mechanism | Test evidence | Status |
|---|---|---|---|---|---|
| 1 | Separate patient, doctor, admin portals | `frontend/src/pages/{patient,doctor,admin}` | React app, role-based nav (`Layout.tsx`) + route guard (`ProtectedRoute.tsx`) | Manual browser verification, Phase 11 (see `second-brain/04_TEST_STATUS.md`) | ⚠️ |
| 2 | Patient registration & login | `services/auth_service.py` | `POST /api/v1/auth/register`, `POST /api/v1/auth/login` | `test_auth.py` (9 tests) | ✅ |
| 3 | Doctor search by specialization | `services/doctor_service.py` | `GET /api/v1/doctors?specialization=` | `test_doctors.py::test_specialization_search_and_inactive_doctor_behavior` | ✅ |
| 4 | Admin-managed doctor profiles | `services/doctor_service.py` | `POST/PUT/PATCH /api/v1/admin/doctors...` | `test_doctors.py::test_admin_doctor_creation_and_permissions`, `test_admin_doctor_update` | ✅ |
| 5 | Doctor specialization | `models/doctor.py::Doctor.specialization` | part of doctor create/update | `test_doctors.py` | ✅ |
| 6 | Doctor working hours | `services/schedule_service.py` | `POST /api/v1/admin/doctors/{id}/schedule` | `test_doctors.py::test_working_hours_configuration_and_invalid_schedule_rejection` | ✅ |
| 7 | Slot duration | `models/doctor.py::Doctor.slot_duration_minutes` | part of doctor create/update; drives `services/slot_service.py` | `test_doctors.py::test_slot_duration_validation`, `test_e2e_admin_workflow` (duration change reflected in slot count) | ✅ |
| 8 | Doctor leave days | `services/doctor_leave_service.py` | `POST/DELETE /api/v1/admin/doctors/{id}/leaves` | `test_leave_conflicts.py` (8 tests) | ✅ |
| 9 | Appointment booking | `services/appointment_service.py` | `POST /api/v1/appointments` | `test_appointments.py`, `test_e2e_patient_booking_workflow` | ✅ |
| 10 | Slot holding | `services/hold_service.py` | `POST /api/v1/slots/holds`, `GET/POST .../release` | `test_slots.py` (hold creation/duplicate/expiry/confirmation) | ✅ |
| 11 | Double-booking prevention | DB partial unique index `uq_doctor_profile_start_time_active` | enforced at commit, translated to 409 | `test_models.py::test_appointment_double_booking_db_constraint` (bypasses the app lock entirely) | ✅ |
| 12 | Safe simultaneous booking | app-level lock + DB constraint | same booking endpoint | `test_concurrency.py::test_100_simultaneous_booking_concurrency` — 100 concurrent requests, exactly 1 succeeds | ⚠️ |
| 13 | Doctor leave conflict handling | `services/doctor_leave_service.py` | leave creation transactionally marks overlapping appointments `CONFLICTED` | `test_leave_conflicts.py` (zero/one/multiple conflicts, unrelated appointments untouched, transactional rollback) | ✅ |
| 14 | Patient notifications | `services/notification_service.py`, `workers/notification_worker.py` | booking/cancellation/reminder/leave-conflict jobs → `EmailProvider` | `test_notifications.py` (14 tests), `test_e2e.py` | ✅ |
| 15 | AI pre-visit summary (urgency + chief complaint + 3 questions) | `services/ai_service.py`, `providers/ai_provider.py` | `POST/GET /api/v1/appointments/{id}/ai/pre-visit-summary` | `test_ai.py` (schema validation, all failure modes), `test_e2e_patient_booking_workflow` | ✅ |
| 16 | AI post-visit summary | `services/ai_service.py` | `POST/GET /api/v1/appointments/{id}/ai/post-visit-summary` | `test_ai.py::test_valid_post_visit_summary_output_and_persistence`, `test_e2e_doctor_workflow` | ✅ |
| 17 | Prescription | `services/ai_service.py::submit_consultation` | `POST /api/v1/appointments/{id}/consultation` | `test_e2e_doctor_workflow` (multi-medication prescription persisted) | ✅ |
| 18 | Medication reminders based on prescription frequency | `services/reminder_service.py` | queued automatically on consultation submission | `test_notifications.py::test_medication_reminder_generation_from_prescription`, `test_medication_reminder_bounded_by_max_cap` | ⚠️ |
| 19 | Booking / reminder / cancellation emails | `providers/email_provider.py`, `workers/notification_worker.py` | `RealEmailProvider` (SMTP) / `MockEmailProvider` | `test_notifications.py` | ⚠️ |
| 20 | Google Calendar create/update/delete on booking/reschedule/cancellation | `services/calendar_service.py`, `providers/calendar_provider.py` | armed post-commit, pushed by `workers/calendar_worker.py` | `test_calendar.py` (15 tests), `test_e2e_reschedule_workflow`, `test_e2e_cancellation_workflow` | ⚠️ |
| 21 | Google OAuth 2.0 | `providers/calendar_provider.py::GoogleCalendarProvider` | refresh-token grant against `GOOGLE_TOKEN_URI` | `test_calendar.py::test_google_provider_without_credentials_raises_permanent_error`; see caveat | ⚠️ |
| 22 | Background jobs | `workers/notification_worker.py`, `workers/calendar_worker.py` | polling workers, `run_once()`/`run_forever()` | `test_notifications.py`, `test_calendar.py` (worker claim/no-reprocess tests) | ✅ |
| 23 | Email retries | `repositories/notification_repository.py` (bounded, backoff) | automatic on next `run_once()` | `test_notifications.py::test_transient_email_failure_is_retryable`, `test_retry_eventually_succeeds`, `test_permanent_failure_after_max_attempts_is_bounded` | ✅ |
| 24 | Graceful LLM failure | `services/ai_service.py::_run_generation` | never raises past the API; `AISummaryStatus.FAILED` | `test_ai.py` (timeout, unavailable, malformed JSON, invalid urgency, wrong question count — 5 distinct failure tests) | ✅ |
| 25 | Role-based authorization | `app/dependencies.py` (`require_role`, ownership checks) | every mutating/sensitive route | `test_auth.py`, `test_e2e_authorization_boundaries` | ✅ |
| 26 | Required documentation | this repo's `docs/` + root `README.md` | — | — | ✅ |

## Notes on ⚠️ items

- **#1 Portals** — functionally complete and manually verified end-to-end in a real
  browser against a live backend (Phase 11), but there is no automated frontend test
  suite (not required by AGENT_PHASES.md, but worth naming as a gap for future work).
- **#12 Safe simultaneous booking** — the 100-thread test forces SQLite to serialize
  access (`StaticPool` + an explicit lock in the test itself), so it does not prove true
  concurrent-write safety on its own. The independent, dialect-agnostic proof is the DB
  unique index test (#11) inserting two conflicting rows directly. Neither has been run
  against a live PostgreSQL instance — see `second-brain/05_KNOWN_ISSUES.md`.
- **#18 Medication reminders** — reminder *cadence* is one check-in per day of
  `duration_days` (capped at 30), not a parse of the free-text `frequency` field into
  exact per-dose times, since AGENT_SPEC.md doesn't require that and the input data
  can't reliably support it. Documented in `services/reminder_service.py` and
  `docs/failure-handling.md`.
- **#19 Emails / #20 Calendar / #21 OAuth** — `RealEmailProvider` (SMTP) and
  `GoogleCalendarProvider` (OAuth 2.0 refresh-token grant + Calendar API v3) are fully
  implemented against each provider's documented contract, but **neither has been
  exercised against a real SMTP server or real Google account** — no credentials exist
  in this environment. `MockEmailProvider`/`MockCalendarProvider` (DEMO_MODE, the
  default) are what every test and the Phase 11 browser verification actually exercised.
  This is the single largest gap between "implemented" and "verified against the real
  external service" in the project — see `docs/google-calendar-setup.md` for the setup
  steps an operator would follow to close it.

## Requirements this document deliberately does not claim

- **Hosted application URL** — not created. Deployment requires hosting-provider
  accounts and credentials this environment does not have; see the Deployment section
  of the final Phase 13 report for what would be needed to do it for real.
