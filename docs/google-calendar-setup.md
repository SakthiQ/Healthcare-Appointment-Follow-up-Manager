# Google Calendar Integration & OAuth 2.0 Setup (Phase 10)

## Overview

Calendar sync is fully isolated behind `CalendarProvider`. Nothing in the
appointment transaction ever calls Google:

```
AppointmentService  (transaction commits FIRST)
      │  post-commit, best-effort, swallowed on failure
      ▼
CalendarService.sync_*   →  writes local CalendarEvent rows (pending_operation)
      │
      ▼  (separate process, later)
CalendarWorker.run_once  →  CalendarService.process_pending_row
                                   │
                                   ▼
                          CalendarProvider
                          ├── MockCalendarProvider    (calendar demo mode on)
                          └── GoogleCalendarProvider  (calendar demo mode off)
```

A booking/reschedule/cancellation only ever writes a local row saying "this
needs pushing to the calendar". The actual Google call happens later in
`CalendarWorker`, so Google being slow, down, or misconfigured cannot delay or
invalidate an appointment.

## Environment variables

All credentials come from environment variables (see `.env.example`) — never
hardcoded, never committed.

| Variable | Purpose |
|---|---|
| `GOOGLE_CLIENT_ID` | OAuth 2.0 client id |
| `GOOGLE_CLIENT_SECRET` | OAuth 2.0 client secret |
| `GOOGLE_REFRESH_TOKEN` | Long-lived refresh token from the consent flow |
| `GOOGLE_TOKEN_URI` | Token endpoint (default `https://oauth2.googleapis.com/token`) |
| `GOOGLE_CALENDAR_API_BASE_URL` | Calendar API base (default v3) |
| `GOOGLE_CALENDAR_ID` | Target calendar (default `primary`) |
| `GOOGLE_CALENDAR_TIMEOUT_SECONDS` | Per-request timeout (default 10) |
| `CALENDAR_MAX_ATTEMPTS` | Bounded retries before a sync is marked FAILED (default 5) |

## Obtaining the credentials

1. **Create a Google Cloud project** — <https://console.cloud.google.com/>.
2. **Enable the Google Calendar API** for that project (APIs & Services →
   Library → "Google Calendar API" → Enable).
3. **Configure the OAuth consent screen** (APIs & Services → OAuth consent
   screen). Add the scope `https://www.googleapis.com/auth/calendar.events`.
   While the app is in "Testing", add the Google account whose calendar you
   want to write to as a test user.
4. **Create an OAuth 2.0 Client ID** (APIs & Services → Credentials → Create
   Credentials → OAuth client ID). Choose **Desktop app** for the simplest
   local flow. Copy the client id and client secret into `GOOGLE_CLIENT_ID` /
   `GOOGLE_CLIENT_SECRET`.
5. **Obtain a refresh token** by running the OAuth consent flow once, with
   `access_type=offline` and `prompt=consent` (both required for Google to
   return a refresh token). Google's OAuth 2.0 Playground
   (<https://developers.google.com/oauthplayground/>) is the quickest path:
   enable "Use your own OAuth credentials", enter your client id/secret,
   authorize the `calendar.events` scope, then exchange the authorization code
   for tokens. Copy the resulting refresh token into `GOOGLE_REFRESH_TOKEN`.
6. **Turn off calendar demo mode** to activate `GoogleCalendarProvider`: set
   `CALENDAR_DEMO_MODE=false`. AI and email are unaffected: each follows `DEMO_MODE` only
   while its own `AI_DEMO_MODE` / `EMAIL_DEMO_MODE` is unset, and a value set there always
   takes precedence. Alternatively, set `DEMO_MODE=false` to switch every integration
   that has no override of its own.

`GoogleCalendarProvider` exchanges the refresh token for a short-lived access
token on demand and caches it in memory until ~60s before expiry, so the
consent flow only ever runs once, out-of-band.

## Operations

| Trigger | Local effect | Worker pushes |
|---|---|---|
| Booking confirmed | Two `CalendarEvent` rows (PATIENT + DOCTOR), `pending_operation=CREATE` | `POST /calendars/{id}/events` |
| Reschedule | Both rows re-armed as `UPDATE` (or `CREATE` if never created) | `PATCH /calendars/{id}/events/{eventId}` |
| Cancellation | Both rows re-armed as `DELETE` | `DELETE /calendars/{id}/events/{eventId}` |

Separate rows are kept per side (`recipient_type` = `PATIENT` / `DOCTOR`) so
each participant's calendar entry is tracked independently, and the external
event id for each is persisted in `external_event_id`.

## Duplicate prevention

Two independent guards, because retries are expected:

1. **DB level** — `UniqueConstraint(appointment_id, recipient_type)` on
   `calendar_events` makes a second row for the same appointment+side
   impossible. Re-syncing re-arms the existing row instead of inserting.
2. **Provider level** — each row carries a stable `idempotency_key`, supplied
   to Google as the event's own `id` on create. A retried create therefore
   returns HTTP 409 ("duplicate"), which `GoogleCalendarProvider` treats as
   success and returns the same id — rather than inserting a second event.

## Failure handling

| Failure | Classification | Result |
|---|---|---|
| Timeout / connection error | `CalendarProviderTransientError` | Row stays `PENDING_SYNC`, `attempts += 1`, `next_retry_at` set with exponential backoff (capped 60 min) |
| HTTP 429 / 5xx | `CalendarProviderTransientError` | Same as above |
| HTTP 4xx (bad request, forbidden), missing credentials | `CalendarProviderPermanentError` | Row marked `FAILED` immediately — no retry burn |
| HTTP 404 on update | `CalendarEventNotFoundError` | **Reconciled**: event is recreated so the appointment stays represented |
| HTTP 404 on delete | `CalendarEventNotFoundError` | Treated as success — already gone |
| Retries exhausted (`CALENDAR_MAX_ATTEMPTS`) | — | Row marked `FAILED` (terminal; worker skips it) |

In every case the appointment row is untouched. `CalendarService` never writes
to `appointments`, and `AppointmentService` wraps its calendar call in
`try/except: log and continue`.

## DEMO_MODE

With calendar demo mode on — `CALENDAR_DEMO_MODE=true`, or unset with `DEMO_MODE=true`
(the default) — `get_calendar_provider()` returns `MockCalendarProvider`, which keeps
events in memory and never makes a network call. The complete booking → reschedule →
cancel calendar flow is therefore exercisable by an evaluator with no Google account and
no credentials.

## Running the worker

```bash
python -m workers.calendar_worker
```

Polls every 30s by default. `CalendarWorker.run_once(db)` is synchronous and
directly testable — that is what the Phase 10 test suite drives.
