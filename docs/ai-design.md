# AI Subsystem Design (Phase 7)

## Overview

The AI subsystem generates three summaries during an appointment's lifecycle:

- **Pre-visit summary** — generated from the patient's submitted symptoms, before the visit, so the doctor has an urgency level, chief complaint, and suggested questions ready.
- **Post-visit summary** — generated from the doctor's consultation notes and prescription, after the visit, so the patient gets a plain-language summary, medication schedule, and follow-up steps.
- **History summary** (#73) — generated on demand by the appointment's doctor (or an admin) from the patient's earlier completed visits with the clinic, so the doctor sees past complaints, medications and recurring issues in a few lines before the visit.

The AI is **advisory only**. It never creates, modifies, or cancels an appointment, and it never produces a diagnosis — it summarizes and triages tone/urgency from patient-reported text.

## Architecture

```
AIProvider (abstract)
├── MockAIProvider   — deterministic, offline, used when AI mode is demo (see below)
└── RealAIProvider   — calls an OpenAI-compatible /chat/completions endpoint

AIService
├── depends only on AIProvider (never imports a concrete provider directly)
├── owns the generate → validate → persist pipeline
└── never touches Appointment rows
```

`AIService` resolves its provider via `providers.ai_provider.get_ai_provider()`, which reads `settings.ai_demo_mode` (`AI_DEMO_MODE`, falling back to `DEMO_MODE`) at call time — so switching either off/on takes effect without a restart-sensitive cache. Tests inject a fake `AIProvider` directly into `AIService(provider=...)` to simulate timeouts, unavailability, and malformed output without any network dependency.

## Prompt templates

Taken verbatim from the original project brief's "LLM Usage Guidance" (`backend/providers/ai_provider.py`):

**Pre-visit:**
> Analyse these symptoms and return: urgency level (Low / Medium / High), chief complaint, and three suggested questions for the doctor. Symptoms: `<symptoms>`

**Post-visit:**
> Convert these clinical notes into a patient-friendly summary with medication schedule and follow-up steps: `<notes>`
>
> Prescription:
> `- <name> <dosage>, <frequency>, for <n> days` (one line per medication, or "No medications prescribed.")
> `Instructions: <prescription instructions>`

The prescription block is appended so the medication schedule is built from what the doctor actually prescribed rather than guessed from free-text notes; the system prompt tells the model to copy every medication exactly and never add, remove or change one.

**History** (#73, not in the original brief, so the wording is ours):
> Summarise this patient's previous visits to the clinic for their doctor: for each visit, the date, the complaint and the medications prescribed; then any issues that come up at more than one visit. Use only what is written below.
>
> Previous visits, newest first:
> `Visit on <YYYY-MM-DD>` / `Notes: <consultation notes>` / `Medications: <name> <dosage>, <frequency>, for <n> days; ...` (or "None") / `Instructions: <prescription instructions>`, one block per visit

Its system prompt tells the model to summarise only what the notes say: no diagnosis, no new treatment or advice, nothing the notes don't contain, medications exactly as prescribed and dates exactly as given.

**Input to the history summary.** The patient's **completed** appointments that have a recorded consultation and started before this appointment, newest first. This appointment itself, later visits, other patients' visits and cancelled or no-show appointments are left out. The input is capped at `HISTORY_MAX_VISITS` (10) visits and `HISTORY_MAX_NOTES_CHARS` (2,000) characters of notes per visit, so the prompt stays a sensible size however long the record is. Each visit's date is taken in its doctor's time zone. **A patient with no earlier visits** gets a stored `SUCCESS` summary saying so (`recent_visits: []`) **without calling the model**: there is nothing to summarise, and nothing for it to invent.

Each is paired with a system prompt instructing the model to return *only* a JSON object of the exact required shape, with no diagnosis and no text outside the JSON. `RealAIProvider` also sets `response_format: {"type": "json_object"}` on the request as a second layer of enforcement, on top of the Pydantic validation described below.

## Strict output contract

**Pre-visit** (`schemas.ai.PreVisitAIOutput`):
```json
{
  "urgency": "Low | Medium | High",
  "chief_complaint": "string",
  "suggested_questions": ["string", "string", "string"]
}
```
`urgency` is a `Literal["Low","Medium","High"]`; `suggested_questions` is constrained to exactly 3 items. Any deviation (wrong urgency value, wrong question count, missing field) fails Pydantic validation.

**Post-visit** (`schemas.ai.PostVisitAIOutput`):
```json
{
  "summary": "string",
  "medication_schedule": "string",
  "follow_up_steps": "string"
}
```

**History** (`schemas.ai.HistoryAIOutput`):
```json
{
  "recent_visits": [{"date": "YYYY-MM-DD", "complaint": "string", "medications": ["string"]}],
  "recurring_issues": ["string"],
  "notes_for_doctor": "string"
}
```
`date` must be a real date, `complaint` and `notes_for_doctor` must be non-empty, and the lists are capped (10 visits, 10 recurring issues, 20 medications per visit).

The provider's raw response is never trusted or stored directly — it always passes through the corresponding Pydantic model before persistence.

## Failure handling

`AIService._run_generation` wraps every provider call and validation step. Nothing it does can raise past the API boundary as a 500 — instead every outcome (success or failure) is persisted as an `AISummary` row and returned as a normal `200 OK`:

| Failure | Where it's caught | Result |
|---|---|---|
| Provider timeout | `AIProviderTimeoutError` | `AISummary(status=FAILED, error_message=...)` |
| Provider unreachable / non-2xx | `AIProviderUnavailableError` | `AISummary(status=FAILED, error_message=...)` |
| Provider response isn't valid JSON | `AIProviderMalformedResponseError` | `AISummary(status=FAILED, error_message=...)` |
| JSON parses but violates the schema (bad urgency, wrong question count, missing field) | `pydantic.ValidationError` on `model_validate` | `AISummary(status=FAILED, error_message="Invalid AI response schema: ...")` |
| Post-visit `medication_schedule` omits a prescribed medication, or doesn't follow its name with its own dosage (so doses swapped between two drugs fail, and `500mg` doesn't match inside `1500mg`; case and whitespace are ignored, so `500 mg` matches `500mg`). The dosage must come after the name, as in the prompt's `Name dosage, frequency` lines; `500mg of Amoxicillin` fails | `_schedule_mismatch` via `_run_generation`'s `verify` hook | `AISummary(status=FAILED, error_message="AI medication schedule does not match the prescription (mismatched: ...)")` |
| History summary lists a visit on a date it was not given (an invented visit) | `_history_mismatch` via the `verify` hook | `AISummary(status=FAILED, error_message="AI history summary lists visits that are not in the records (...)")` |
| A provider that doesn't implement the history summary (a custom `AIProvider` written before #73) | the base class's default `generate_history_summary` raises `AIProviderUnavailableError` | `AISummary(status=FAILED, error_message="This AI provider does not support history summaries.")` |
| Any other unexpected exception from the provider | generic `Exception` catch | `AISummary(status=FAILED, error_message=...)` |
| Success | — | `AISummary(status=SUCCESS, payload=<validated dict>)` |

The appointment row is never read for write, never locked, and never touched by this pipeline — AI failure and appointment integrity are fully decoupled. Each generation attempt inserts a **new** `AISummary` row rather than overwriting the previous one, so failed attempts remain in the audit trail; `GET` endpoints always return the most recent row by `created_at`, giving a natural "retry" path (regenerate → new row → latest is now SUCCESS).

`error_message` is technical detail for clinic staff: API responses to a patient return `null` in its place, while doctors and admins see it. A provider's non-2xx response body goes to the logs only, never into `error_message`.

## Persistence & retrieval

- `AISummary` (from Phase 2's schema) stores `appointment_id`, `type` (`PRE_VISIT`/`POST_VISIT`/`HISTORY`; `HISTORY` was added to the PostgreSQL enum by migration `f6b8d0e2a4c6`), `status` (`PENDING`/`SUCCESS`/`FAILED`), `payload` (JSON, null on failure), `error_message` (null on success), `created_at`.
- Generation endpoints (`POST /appointments/{id}/ai/pre-visit-summary`, `POST /appointments/{id}/ai/post-visit-summary`) are restricted to the resource owner (patient for pre-visit, treating doctor for post-visit).
- Retrieval endpoints (`GET .../ai/pre-visit-summary`, `GET .../ai/post-visit-summary`) are open to any participant on the appointment — patient, treating doctor, or admin — so the doctor can view the pre-visit summary and the patient can view the post-visit summary, per the assignment.
- The history summary (`POST` and `GET /appointments/{id}/ai/history-summary`) is for **the appointment's doctor and admins only**: patients and other doctors get `403`. Every generation and every view is written to the audit log (`ai.history.generate`, `ai.history.view`) with the patient's id.
- All generation endpoints share the per-user `AI_RATE_LIMIT_PER_HOUR` bucket, and each summary type is capped at `AI_MAX_SUMMARIES_PER_APPOINTMENT` attempts per appointment (both answer `429` when reached).

## DEMO_MODE

The AI provider is chosen by `AI_DEMO_MODE` when it is set, and by `DEMO_MODE` when `AI_DEMO_MODE` is unset or blank. So `DEMO_MODE=true` with `AI_DEMO_MODE=false` uses the real LLM (while email and calendar stay mocked), and `DEMO_MODE=false` with `AI_DEMO_MODE=true` keeps the AI mocked. `GET /health` reports the result as `ai_provider: "mock" | "real"`.

When the AI is in demo mode (the default: both unset → `DEMO_MODE=true`), `get_ai_provider()` returns `MockAIProvider`, which:
- never makes a network call,
- derives urgency from simple keyword matching in the symptom text (e.g. "chest pain", "severe" → High; "mild", "slight" → Low; otherwise Medium),
- for the history summary, lists each visit with the first line of its notes as the complaint and its prescribed medications, and reports a medication prescribed at more than one visit as recurring,
- always returns a schema-valid response, so the happy path is fully exercisable without any LLM credentials.

When the AI is not in demo mode (`AI_DEMO_MODE=false`, or `DEMO_MODE=false` with `AI_DEMO_MODE` unset), `get_ai_provider()` returns `RealAIProvider`, which requires `AI_PROVIDER_API_KEY` and calls the OpenAI-compatible endpoint configured by `AI_PROVIDER_BASE_URL` / `AI_PROVIDER_MODEL` (see `.env.example`). Any provider that exposes an OpenAI-compatible `/chat/completions` API works without code changes.

## Explicitly out of scope

- No diagnosis or autonomous clinical decision-making — the AI only summarizes and triages tone/urgency from patient-reported text, and summarises the clinic's own records for the doctor. The doctor's page marks the history summary as AI-generated and says to check the records.
- The AI provider cannot modify appointment state, directly or indirectly — `AIService` has no reference to `AppointmentService` or the appointment repository's write paths.
- Notification delivery and Google Calendar sync are separate subsystems (Phases 9–10) and are not touched here.
