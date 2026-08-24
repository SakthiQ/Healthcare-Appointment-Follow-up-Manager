# Failure Handling (Phase 13)

Every external integration (LLM, email, Google Calendar) follows the same shape: the
appointment transaction commits first and never waits on or depends on any of them: a
failure is recorded on its own row, never on the appointment. This document is the single
place all three are compared side by side; each has a deeper per-subsystem writeup
(`docs/ai-design.md`, `docs/google-calendar-setup.md`) and its own test file
(`test_ai.py`, `test_notifications.py`, `test_calendar.py`), plus `test_e2e.py`'s
`test_e2e_no_external_service_required_for_appointment_integrity`, which runs a full
book → reschedule → cancel lifecycle with all three providers failing at once.

## The shared pattern

```
AppointmentService (commits the appointment)
      │  post-commit, best-effort, wrapped in try/except: log and continue
      ▼
{Notification, Calendar} rows created with status PENDING / PENDING_SYNC
      │
      ▼  (separate process, later — never inline)
{NotificationWorker, CalendarWorker}.run_once()
      │
      ▼
Provider.send() / .create_event() / etc.
      │
   success ──────────────► row marked SENT / SYNCED
      │
   transient failure ────► attempts += 1; if attempts < MAX: PENDING again,
   │                       next_retry_at = now + backoff (capped, exponential)
   │                       else: FAILED (terminal)
      │
   permanent failure ────► FAILED immediately, no retry burned
```

AI summaries follow the same shape minus the worker: `AIService` calls the provider
synchronously (the user is waiting for a result to review), but the failure handling is
identical — a failed call never raises past the API boundary, it produces a `FAILED`
`AISummary` row and returns 200.

## Per-provider comparison

| | **AI** (`ai_service.py`) | **Email** (`notification_service.py`) | **Calendar** (`calendar_service.py`) |
|---|---|---|---|
| Trigger | Patient/doctor explicitly requests a summary | Booking, reschedule, cancellation, leave conflict, medication schedule | Booking, reschedule, cancellation |
| When the provider is called | Synchronously, in the request | `NotificationWorker.run_once()`, polling | `CalendarWorker.run_once()`, polling |
| Transient exception | `AIProviderTimeoutError`, `AIProviderUnavailableError` | `EmailProviderTransientError`, any unexpected exception | `CalendarProviderTransientError`, timeouts, 5xx, 429 |
| Permanent exception | — (no separate class; malformed/invalid responses always retry-eligible on the next explicit request) | `EmailProviderPermanentError` (e.g. invalid recipient) | `CalendarProviderPermanentError` (bad credentials, 4xx) |
| Not-found handling | — | — | `CalendarEventNotFoundError`: recreates on UPDATE (reconciliation), treated as success on DELETE |
| Schema validation | Pydantic `PreVisitAIOutput`/`PostVisitAIOutput`; a syntactically valid but schema-violating response (wrong urgency, wrong question count) fails the same way as a provider error | — | — |
| Max attempts | N/A (no auto-retry; retry = user calls the endpoint again) | `NOTIFICATION_MAX_ATTEMPTS` (default 5) | `CALENDAR_MAX_ATTEMPTS` (default 5) |
| Backoff | N/A | `min(2**attempts, 60)` minutes | `min(2**attempts, 60)` minutes |
| Terminal state | `AISummaryStatus.FAILED`, `error_message` set | `NotificationStatus.FAILED`, `last_error` set | `CalendarSyncStatus.FAILED`, `last_error` set |
| Duplicate prevention | New row per attempt (audit trail); `GET` resolves to latest by `created_at` | Job created once per (appointment, recipient, type); `get_due_jobs` claims with `SELECT ... FOR UPDATE SKIP LOCKED` on Postgres | DB `UniqueConstraint(appointment_id, recipient_type)` **and** provider-level idempotency key (Google returns 409 on a duplicate id, treated as success) |
| Obsolete-work handling | N/A | Reschedule/cancel supersede still-PENDING reminders for the old time (`supersede_pending_notifications`) so a patient is never reminded about a time that no longer applies | Reschedule re-arms existing rows as UPDATE; cancel re-arms as DELETE — never creates new rows |
| DEMO_MODE provider | `MockAIProvider` — keyword-based urgency, always schema-valid | `MockEmailProvider` — records sends in memory, never touches network | `MockCalendarProvider` — in-memory event store |
| Test coverage | `test_ai.py` (11), `test_e2e.py` failure cases | `test_notifications.py` (14), `test_e2e.py` failure cases | `test_calendar.py` (15), `test_e2e.py` failure cases |

## Doctor leave conflicts (Phase 8) — a related but distinct failure path

This isn't an *external*-service failure, but it's the other place the system must not
silently break existing state: when a doctor is marked on leave, `DoctorLeaveService`
must find every overlapping appointment, mark it `CONFLICTED` (never delete it), and
queue a notification — all inside one transaction (`db.flush()` per step, one
`db.commit()` at the end). If any step raises, `db.rollback()` discards the whole
attempt: no leave row, no `CONFLICTED` status, no notification job survives a partial
failure. See `docs/system-design.md` §2 and `test_leave_conflicts.py::test_leave_creation_is_transactional_on_partial_failure`.

## Concurrency (Phase 6) — the other "must not corrupt state" guarantee

Double-booking prevention is the one place the system does **not** rely on
best-effort/retry — it must be correct on the first attempt, atomically. See
`docs/system-design.md` §1: a partial unique index
(`uq_doctor_profile_start_time_active`) is the actual final authority, independent of
any application-level lock; `IntegrityError` on violation is translated to a 409. Proven
by `test_appointment_double_booking_db_constraint` (inserts two conflicting rows
directly, bypassing the app lock) and `test_100_simultaneous_booking_concurrency` (100
concurrent requests, exactly 1 succeeds).

## What is NOT covered by retry

- **Stale calendar/reminder work for a cancelled or superseded appointment.** Reminders
  are explicitly superseded on reschedule/cancel (see table above). Calendar events are
  explicitly deleted on cancel and updated on reschedule. There is no scenario where
  external state silently drifts from the appointment's actual status once a worker has
  run — but until that next worker run, stale rows exist in `PENDING`/`PENDING_SYNC`
  state, which is the expected eventually-consistent window inherent to a polling worker
  design (see Deployment Architecture in `docs/architecture.md` for polling interval).
- **A provider that is down for longer than `MAX_ATTEMPTS × backoff`.** The job becomes
  `FAILED` (terminal) and is not automatically retried further. An operator would need to
  reset `status`/`attempts` manually (no admin endpoint for this exists — recorded as a
  known limitation, see `second-brain/05_KNOWN_ISSUES.md`).
