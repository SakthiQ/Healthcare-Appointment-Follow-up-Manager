# 02 - Technical Decisions

## Key Design & Architecture Decisions

1. **Modular Monolith over Microservices**
   - *Rationale:* Eliminates network latency, deployment complexity, and distributed transaction management while maintaining domain boundary isolation.

2. **Clean Domain Service Separation for Scheduling**
   - *Rationale:* `SlotService` handles slot interval calculation, boundary validation, and leave exclusions. `HoldService` manages hold creation, hold confirmation validation, manual release, and automatic expiration. Scheduling logic is completely decoupled from final appointment booking.

3. **Deterministic & Database-Backed Slot Generation**
   - *Rationale:* Slot availability is calculated on-the-fly from active working hours, excluding doctor leave dates, active holds (`is_active = True`, `expires_at > now`), and confirmed appointments.

4. **Timezone-Aware UTC Normalization**
   - *Rationale:* Utility `ensure_utc` standardizes all datetime operations and comparisons across PostgreSQL/SQLite ORM queries to prevent offset-naive vs offset-aware comparison errors.

5. **DB-Level Partial Unique Index as Final Double-Booking Authority (2026-08-23)**
   - *Rationale:* The original Phase 6 implementation relied only on a Python `threading.Lock` (single-process only) and `SELECT FOR UPDATE` (a no-op on SQLite), which does not satisfy the spec's requirement that "the database must be the final authority." Added `uq_doctor_profile_start_time_active`, a partial unique index on `appointments(doctor_profile_id, start_time)` filtered to active statuses (`HELD`/`CONFIRMED`/`RESCHEDULED`), implemented as a dialect-portable `sqlite_where`/`postgresql_where` SQLAlchemy `Index`. `IntegrityError` from a constraint violation is translated to `ConflictError` (409) in the repository layer.

6. **AI Provider as an OpenAI-Compatible HTTP Client, No New SDK Dependency (2026-08-23)**
   - *Rationale:* `RealAIProvider` speaks the OpenAI-compatible `/chat/completions` REST shape directly via `httpx` (already a dependency) instead of adding a provider-specific SDK. Any LLM vendor exposing that shape works by changing `AI_PROVIDER_BASE_URL` alone — keeps the external provider fully behind the `AIProvider` interface per the global engineering rules.

7. **Every AI Generation Attempt Persists a New `AISummary` Row (2026-08-23)**
   - *Rationale:* Rather than overwriting a single row per appointment+type, each call to generate a pre/post-visit summary inserts a new `AISummary` (success or `FAILED` with `error_message`). This preserves a full audit trail of retries and failures; `GET` endpoints resolve to the latest row by `created_at`, so regenerating after a failure is just "call the generate endpoint again."

8. **Symptom-Report and Consultation/Prescription Intake Live in the AI Module (2026-08-23)**
   - *Rationale:* AGENT_PHASES.md has no dedicated phase for a patient submitting symptoms or a doctor submitting consultation notes/prescription — but both are the direct input the AI subsystem needs (Phase 7) and the direct input Phase 9's medication reminders will need (`Prescription`/`Medication` rows). Implemented as thin endpoints in `app/api/ai.py` (`POST .../symptom-report`, `POST .../consultation`) rather than as a separate service/phase, since the requirement doesn't justify its own subsystem.

9. **Single-Commit (Flush-Then-Commit) Pattern for Leave-Creation Transactionality (2026-08-23)**
   - *Rationale:* Phase 8 explicitly requires leave creation + conflict detection + status update + notification job creation to be one atomic transaction. Earlier phases' repository methods (`create_leave`, `update_status`, etc.) each auto-commit individually, which does not compose into one transaction. Rather than changing those (used elsewhere, already tested), `DoctorLeaveService.create_leave` uses new no-commit repository variants (`add_leave_no_commit`, `update_status_no_commit`, `create_job_no_commit`) that only `db.flush()`, wrapped in a single `try/except` with one `db.commit()` at the end and `db.rollback()` on any failure — so a failure partway through (e.g. the 3rd of 5 affected appointments) leaves nothing persisted, not even the leave row itself.

10. **`LeaveService.create_leave` Removed, Superseded by `DoctorLeaveService` (2026-08-23)**
    - *Rationale:* Phase 8 requires every leave-creation call to also run conflict detection — there is no valid code path where a leave should be created without it. Rather than keeping two ways to create a leave (one with conflict handling, one without) and risking a call site using the wrong one, the old `LeaveService.create_leave` was deleted and `POST /admin/doctors/{id}/leaves` now calls `DoctorLeaveService.create_leave` exclusively. `LeaveService` still owns `get_leaves`/`delete_leave` (unaffected by Phase 8, no conflict-handling implications).

11. **Notification Jobs Created Directly by `DoctorLeaveService`, Not a Full `NotificationService` (2026-08-23)**
    - *Rationale:* Phase 8 says "only create notification jobs for the notification subsystem" — no email delivery, no worker, no retry logic yet (that's Phase 9). Added a deliberately minimal `repositories/notification_repository.py` with just `create_job_no_commit`, used directly by `DoctorLeaveService`. Each job is queued `PENDING` with a JSON `payload` (appointment id, leave date/reason, original start_time) so Phase 9's worker has what it needs to render a notification without re-deriving it.

12. **`EmailProvider` as SMTP via stdlib `smtplib`, No Vendor SDK (2026-08-23)**
    - *Rationale:* Same reasoning as the AI provider (decision 6): `RealEmailProvider` speaks plain SMTP (`smtplib`, zero new dependency) instead of a SendGrid/Mailgun-specific SDK. Every mainstream provider (SendGrid, Mailgun, SES, Gmail) offers SMTP relay, so this works with any of them via env vars alone (`SMTP_HOST`/`PORT`/`USERNAME`/`PASSWORD`), keeping the provider abstraction genuinely swappable per the engineering-decisions doc's "why external services are isolated" rationale.

13. **`next_retry_at` Doubles as "Scheduled Send Time", Not Just Retry Time (2026-08-23)**
    - *Rationale:* Rather than adding a new column for "send no earlier than X" (appointment reminders, medication reminders), reused `NotificationJob.next_retry_at` — `NULL` means "eligible immediately", a future timestamp means "not due yet". `NotificationJobRepository.get_due_jobs` treats both the same way (`next_retry_at IS NULL OR next_retry_at <= now`). Avoids a schema change; the field already existed in the Phase 2 model specifically for this kind of time-gating.

14. **Notification Queueing Is a Best-Effort Side Effect of Appointment Operations, Swallowed on Failure (2026-08-23)**
    - *Rationale:* `AppointmentService.create_appointment`/`cancel_appointment` queue notification jobs (separate commit, after the appointment's own commit) wrapped in `try/except: log and continue`. This is the Phase 9 gate requirement made concrete: "email failure never invalidates an already-committed appointment" — extended here to "notification *queueing* failure" too, since queueing is not part of the appointment's own transaction. Covered by `test_booking_succeeds_even_if_notification_queueing_raises`.

15. **Medication Reminder Cadence: One Job Per Medication Per Day of `duration_days`, Bounded at 30 (2026-08-23)**
    - *Rationale:* `Medication.frequency` is free text (e.g. "twice daily") with no structured times-of-day, so exact per-dose scheduling isn't derivable. Chose one daily check-in reminder per medication for `min(duration_days or 1, 30)` days instead — `frequency` is still carried into the job payload for the notification content. Documented explicitly in `services/reminder_service.py` so a future phase doesn't mistake this for parsed-frequency scheduling.

16. **`DoctorLeaveService` Refactored to Queue Through `NotificationService` (2026-08-23)**
    - *Rationale:* Now that Phase 9 established the canonical `NotificationService`, Phase 8's direct repository calls (`notification_repository.create_job_no_commit`) were replaced with `notification_service.queue_notification_no_commit` for a single consistent code path creating `NotificationJob` rows. Pure refactor — behavior and Phase 8 tests unchanged (test monkeypatch target updated to match).

17. **Calendar Sync Is Two-Phase: Arm Locally Post-Commit, Push Later in a Worker (2026-08-24)**
    - *Rationale:* Phase 10 requires "keep Calendar logic outside the appointment transaction" and "do not modify the core appointment transaction to wait for Google Calendar success." `AppointmentService` therefore never calls a provider — after its own commit it calls `CalendarService.sync_*`, which only writes local `CalendarEvent` rows with a `pending_operation` (CREATE/UPDATE/DELETE). `CalendarWorker` pushes them to Google later. This means Google latency/outage cannot affect booking response time or success at all, and the provider call site is a single well-defined place (`process_pending_row`).

18. **Two Independent Duplicate-Prevention Guards for Calendar Events (2026-08-24)**
    - *Rationale:* Requirement 9 ("prevent uncontrolled duplicate event creation on retry") needs protection at both layers. (a) DB: `UniqueConstraint(appointment_id, recipient_type)` makes a second row per appointment-side impossible — re-syncing re-arms the existing row. (b) Provider: each row carries a stable `idempotency_key` passed to Google as the event's own `id`, so a retried create returns 409 (treated as success, same id returned) instead of inserting a second event. Mirrors decision 5's "DB is the final authority" philosophy.

19. **Separate `CalendarEvent` Row Per Participant (2026-08-24)**
    - *Rationale:* The assignment requires a calendar event "for both" patient and doctor. Kept as two independently-tracked rows (`recipient_type` PATIENT/DOCTOR), each with its own `external_event_id`, `attempts`, and sync state — so one side failing to sync doesn't block or corrupt the other, and each participant's event can be reconciled separately.

20. **404-on-Update Reconciles by Recreating; 404-on-Delete Is Success (2026-08-24)**
    - *Rationale:* Requirement 8 asks for "retry/reconciliation". An externally-deleted event would otherwise leave a booked appointment invisible on the calendar forever, so `CalendarEventNotFoundError` during UPDATE recreates the event. During DELETE the same error means the desired end state already holds, so it settles as SYNCED rather than burning retries on an impossible delete.

21. **Frontend: Plain Vite + React Router + `fetch`, No State-Management or UI Library (2026-08-24)**
    - *Rationale:* Phase 11 says "prioritise functional clarity over animations and visual complexity" and "do not add unrelated product features." The app's data needs are per-screen fetches with loading/error states, which a ~40-line `useAsync` hook covers — Redux/React Query/Tailwind/MUI would all be weight without a matching requirement. Total production bundle is 223 kB (67 kB gzipped) with only three runtime dependencies.

22. **Frontend Renders All Times in Explicit UTC (2026-08-24)**
    - *Rationale:* The backend generates working hours, slots, and appointments in UTC. Rendering in the viewer's local timezone would make the displayed slot differ from the slot actually booked (and from what the doctor sees in a different timezone). Every timestamp is formatted with `timeZone: 'UTC'` and labelled "UTC". `parseServerDate()` additionally normalises the backend's timezone-naive DB-read timestamps — see `05_KNOWN_ISSUES.md` Phase 11 note 1 for the underlying defect.

23. **Symptoms Collected Before Confirm, Submitted After Appointment Creation (2026-08-24)**
    - *Rationale:* AGENT_PHASES describes the patient flow as "enter symptoms → generate pre-visit AI summary → confirm appointment", but the backend keys both the symptom report and the AI summary to an `appointment_id`, so neither can exist before the appointment. The UI therefore collects symptoms as a pre-confirm step (matching the intended experience) and fires create → symptom-report → generate-summary in the order the API requires. An AI failure at that point does not present as a failed booking, since the appointment is already committed.





24. **Reschedule Reuses `BOOKING_CONFIRMATION` Rather Than a New Notification Type (2026-08-24)**
    - *Rationale:* Phase 12 requires reschedule to "create required notifications", but AGENT_PHASES' authoritative Phase 9 type list has no RESCHEDULED value, and adding an enum value means a migration. A confirmation announcing the *new* time is semantically accurate and keeps us inside the specified type set. Both parties are notified and the reminder is re-armed for the new time.

25. **Superseded Notification Jobs Are Marked FAILED With an Explanatory `last_error` (2026-08-24)**
    - *Rationale:* On reschedule/cancel, reminders already queued for the old time must not fire. `NotificationStatus` has only PENDING/PROCESSING/SENT/FAILED, so FAILED is the available terminal state; `last_error` records "Superseded: appointment rescheduled/cancelled." so the distinction from a genuine delivery failure stays observable. Chosen over deleting the rows (loses the audit trail) and over adding a CANCELLED enum value (schema migration for a bookkeeping nuance).

26. **Privileged Self-Registration Gated Behind a Settings Flag, Not a Test-File Rewrite (2026-08-24)**
    - *Rationale:* Phase 13's security audit found `POST /auth/register` would create an ADMIN account for any unauthenticated caller who set `"role": "ADMIN"`. The correct fix (restrict to PATIENT-only) had a 9-file blast radius because nearly every test file's setup helper self-registers an admin fixture this way. Rather than rewriting all 9, added `ALLOW_PRIVILEGED_SELF_REGISTRATION` (default `False`, secure) and set it `True` in exactly one place — `tests/conftest.py` — for the whole suite. Deliberately NOT tied to `DEMO_MODE`: an evaluator's default `DEMO_MODE=True` deployment must still be secure against this, so the two concerns (mock providers vs. auth security) stay independent settings.

27. **CORS: Explicit Origin Allow-List, `allow_credentials=False` (2026-08-24)**
    - *Rationale:* Found `allow_origins=["*"]` + `allow_credentials=True` during the same audit — a real misconfiguration (Starlette reflects the specific request Origin instead of a literal wildcard when credentials are on, so any site could make a credentialed cross-origin request). Auth here is Bearer-token-only (`Authorization` header via explicit fetch, no cookies), so credentials were never actually needed. Switched to `CORS_ALLOWED_ORIGINS` (explicit allow-list, defaults to local Vite dev origins) with `allow_credentials=False`. Verified inert for tests: `TestClient` doesn't send an `Origin` header, so CORS middleware doesn't engage during the suite.
