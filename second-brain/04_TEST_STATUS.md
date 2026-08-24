# 04 - Test Status

## Latest Test Suite Run
- **Execution Date:** 2026-08-24 (final red-team audit — this is the official record)
- **Total Tests:** 107 collected — **107 passed, 0 failed, 0 skipped**, 273.95s
- **Command:** fresh SQLite DB via `alembic upgrade head` from empty (re-verified), then `cd backend && python -m pytest tests/ -v`
- **Frontend:** `tsc --noEmit` clean, `vite build` succeeds (223 kB JS / 67 kB gzipped)
- **Coverage tool:** none configured (`pytest-cov` not in `requirements.txt`) — no numeric coverage % is reported anywhere in this project; any such number would be fabricated. Suite breadth is documented qualitatively by suite below instead.
- Caveat: the shared test-DB session leaks committed rows across tests (see `05_KNOWN_ISSUES.md`). **Prefer scoped or delta-based assertions in new tests; avoid absolute whole-table counts.**

## Backend coverage by suite

| Suite | Tests | What it locks down |
|---|---|---|
| `test_e2e.py` | 14 | Phase 12 — the 5 required workflows (patient booking, doctor, admin, reschedule, cancellation) end-to-end through HTTP, plus 6 failure scenarios (LLM/email/calendar unavailable, invalid AI response, expired hold, simultaneous booking), cross-cutting authorization, a full lifecycle with **all three providers dead at once**, and (final audit) `test_e2e_backend_restart_with_pending_jobs` — proves worker state lives entirely in the DB, not in-process |
| `test_calendar.py` | 15 | Phase 10 — create/update/delete events, provider unavailable, retry, bounded retries, repeated create/delete, reconciliation (404-on-update recreates), DEMO_MODE provider selection, calendar failure never invalidates an appointment |
| `test_notifications.py` | 14 | Phase 9 — booking/cancellation/leave-conflict/medication jobs to correct recipients, successful send, transient failure → retry → success, bounded permanent failure, worker due-job claiming and no-reprocessing, booking survives notification outage |
| `test_ai.py` | 11 | Phase 7 — valid pre/post-visit output + persistence, missing-prerequisite validation, unauthorised view rejected, invalid JSON / invalid urgency / wrong question count / timeout / provider unavailable all degrade to FAILED without breaking the appointment |
| `test_auth.py` | 11 | Phase 3 — registration, duplicate rejection, login, invalid credentials, authenticated access, RBAC per role, cross-user ownership; + Phase 13 security-fix regression test (`test_privileged_self_registration_rejected_by_default`); + final audit `test_expired_token_rejected` (an expired-but-correctly-signed JWT, and a tampered one, both rejected) |
| `test_leave_conflicts.py` | 8 | Phase 8 — zero/one/multiple conflicts, unrelated appointments untouched (other date, other doctor, already-cancelled), multiple leave dates, repeated leave rejected, admin inspection, transactional rollback |
| `test_models.py` | 7 | Phase 2 + Phase 6 hardening — entity/relationship integrity, and the DB-level double-booking unique index rejecting a duplicate insert even when the app lock is bypassed |
| `test_slots.py` | 6 | Phase 5 — slot generation, outside-working-hours, leave exclusion, hold creation/duplicate/expiry/confirmation |
| `test_doctors.py` | 6 | Phase 4 — doctor CRUD + permissions, specialisation search, inactive-doctor behaviour, working hours & slot duration validation, leave creation |
| `test_appointments.py` | 6 | Phase 6 — booking from hold, double-booking rejection, reschedule (incl. no duplicate row), cancel + repeat-cancel, unauthorised access, expired hold not confirmable |
| `test_health.py` | 3 | Phase 1 — health endpoints, OpenAPI |
| `test_database.py` | 3 | Phase 1 — connection, session, custom exceptions |
| `test_config.py` | 2 | Phase 1 — settings defaults and overrides |
| `test_concurrency.py` | 1 | Phase 6 gate — 100 simultaneous bookings → exactly 1 success, 99 conflicts (see caveat in `05_KNOWN_ISSUES.md`: SQLite forces serialisation, so the DB unique index is the real proof) |

## Phase 11 frontend verification (2026-08-24)
No automated frontend suite exists (Phase 11 does not require one). Verification was
manual-but-real: live backend on a freshly-migrated DB + Vite dev server, driven through an
actual browser.
- [x] `tsc --noEmit` clean; `vite build` succeeds (223 kB JS / 67 kB gzipped)
- [x] Patient: register/login → doctor search → weekly availability → 8 real slots → hold with live countdown → symptoms → confirm → appointment + pre-visit AI summary (High urgency correctly derived, exactly 3 questions)
- [x] Held slot disappears from the available list
- [x] Doctor: dashboard counts → sees patient's pre-visit summary → submits consultation + prescription (reminders scheduled) → generates post-visit summary
- [x] Admin: dashboard aggregates → doctor config → add leave → appointment auto-CONFLICTED → shown in conflicted view
- [x] Patient sees conflict alert and the doctor's post-visit summary
- [x] Cancel confirm dialog → CANCELLED
- [x] RBAC guard: patient hitting `/admin/doctors` redirected to `/patient`
- [x] Mobile 375px: no horizontal overflow
- [x] Backend suite re-run afterwards: still 91/91

**Bug found and fixed during this pass:** timezone-naive DB timestamps were parsed as local time,
making every hold appear pre-expired and unbookable. Would not have been caught by the build or by
the backend tests — only by driving the UI. See `05_KNOWN_ISSUES.md` Phase 11 note 1.

## Phase 12 architectural audit (2026-08-24)
Verified by inspection, not assumed:
- [x] **No module bypasses the service/business layer** — no file in `app/api/` imports `repositories` or `providers`; every route delegates to a service.
- [x] **Provider isolation** — only `ai_service`, `calendar_service`, and `notification_service` import a provider (1 each). `appointment_service` imports none, so the booking transaction cannot touch an external service.
- [x] **No external service required for core appointment integrity** — proved by `test_e2e_no_external_service_required_for_appointment_integrity`, which runs book → reschedule → cancel with the LLM, email, and calendar providers *all* failing, and asserts the state machine and slot release are unaffected.

## Phase 13 final audit (2026-08-24)
- [x] Clean-environment run: fresh-migrated DB (`alembic upgrade head` from empty, verified) + `pytest tests/ -q` → 105/105
- [x] Frontend: `tsc --noEmit` + `vite build` clean
- [x] Requirement-by-requirement evidence audit — `docs/requirement-mapping.md` (26 rows, real endpoints/tests, no planning-stage placeholders)
- [x] Code-quality audit — no TODO/FIXME/print()/hardcoded secrets found; `requirements.txt` has zero unused deps; largest file is 315 lines (appointment_service.py, justified by complexity)
- [x] Security audit — **found and fixed** a critical privilege-escalation vulnerability (see `05_KNOWN_ISSUES.md`) and a CORS misconfiguration; JWT+bcrypt, RBAC, and ownership checks confirmed correct by existing test coverage
- [x] Reliability audit — re-confirmed via the Phase 12 E2E suite (double-booking, leave conflicts, notification/calendar retries, idempotency all covered)

## Final red-team audit (2026-08-24)
Re-verified empirically rather than trusting prior claims:
- [x] The DB unique index actually exists in a real migrated database — inspected `sqlite_master` directly: `uq_doctor_profile_start_time_active` with the exact `WHERE status IN (...)` clause is present.
- [x] 100-concurrent-booking test re-run standalone: exactly 1 of 100 succeeded, 99 got 409, observed in the actual HTTP response log.
- [x] Whole-repo secret scan (backend, frontend, docs, `.env*`) for API-key-shaped strings — none found.
- [x] Route handlers re-checked for embedded business logic (`db.query`/`db.add`/`db.commit` in `app/api/*.py`) — none found, routes are genuinely thin.
- [x] Test suite scanned for superficial patterns (`assert True`, single-assert tests) — the few single-assert tests checked are legitimate single-condition checks, not vacuous; two tests that looked like "0 asserts" to a naive grep actually use `pytest.raises(...)`, confirmed by reading them.
- [x] Admin self-registration fix verified **live**, both directions: with `ALLOW_PRIVILEGED_SELF_REGISTRATION=True` the documented bootstrap curl command succeeds (201); on a normal startup (flag unset) the same request gets 403.
- [x] `requirements.txt` cross-checked against actual third-party imports in the codebase — complete, no missing or unused dependency.
- [x] Found: SQLite connections never set `PRAGMA foreign_keys=ON`, so FK constraints aren't enforced in dev/test (Postgres enforces them always). **Not fixed** — no code path hard-deletes a row with FK-dependent children, so there's no demonstrated behavioral gap; fixing risked destabilizing 107 passing tests for a parity-only, currently-inert benefit.
- [x] Found: this repository has zero git commits (`git log` → "does not have any commits yet"). Not fixed — committing requires explicit user instruction.

## Nothing else left planned
Phases 0-13 are all complete. Any further test work is either (a) closing the caveats in
`05_KNOWN_ISSUES.md` or (b) new feature work, not a phase deliverable.
