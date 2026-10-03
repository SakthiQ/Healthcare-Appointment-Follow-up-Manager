# AI Subsystem Design (Phase 7)

## Overview

The AI subsystem generates two summaries during an appointment's lifecycle:

- **Pre-visit summary** — generated from the patient's submitted symptoms, before the visit, so the doctor has an urgency level, chief complaint, and suggested questions ready.
- **Post-visit summary** — generated from the doctor's consultation notes and prescription, after the visit, so the patient gets a plain-language summary, medication schedule, and follow-up steps.

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

Taken verbatim from AGENT_SPEC.md's "LLM Usage Guidance" (`backend/providers/ai_provider.py`):

**Pre-visit:**
> Analyse these symptoms and return: urgency level (Low / Medium / High), chief complaint, and three suggested questions for the doctor. Symptoms: `<symptoms>`

**Post-visit:**
> Convert these clinical notes into a patient-friendly summary with medication schedule and follow-up steps: `<notes>`
>
> Prescription:
> `- <name> <dosage>, <frequency>, for <n> days` (one line per medication, or "No medications prescribed.")
> `Instructions: <prescription instructions>`

The prescription block is appended so the medication schedule is built from what the doctor actually prescribed rather than guessed from free-text notes; the system prompt tells the model to copy every medication exactly and never add, remove or change one.

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

The provider's raw response is never trusted or stored directly — it always passes through the corresponding Pydantic model before persistence.

## Failure handling

`AIService._run_generation` wraps every provider call and validation step. Nothing it does can raise past the API boundary as a 500 — instead every outcome (success or failure) is persisted as an `AISummary` row and returned as a normal `200 OK`:

| Failure | Where it's caught | Result |
|---|---|---|
| Provider timeout | `AIProviderTimeoutError` | `AISummary(status=FAILED, error_message=...)` |
| Provider unreachable / non-2xx | `AIProviderUnavailableError` | `AISummary(status=FAILED, error_message=...)` |
| Provider response isn't valid JSON | `AIProviderMalformedResponseError` | `AISummary(status=FAILED, error_message=...)` |
| JSON parses but violates the schema (bad urgency, wrong question count, missing field) | `pydantic.ValidationError` on `model_validate` | `AISummary(status=FAILED, error_message="Invalid AI response schema: ...")` |
| Post-visit `medication_schedule` omits a prescribed medication's name or dosage (compared ignoring case and whitespace, so `500 mg` matches `500mg`) | `_schedule_mismatch` via `_run_generation`'s `verify` hook | `AISummary(status=FAILED, error_message="AI medication schedule does not match the prescription (missing: ...)")` |
| Any other unexpected exception from the provider | generic `Exception` catch | `AISummary(status=FAILED, error_message=...)` |
| Success | — | `AISummary(status=SUCCESS, payload=<validated dict>)` |

The appointment row is never read for write, never locked, and never touched by this pipeline — AI failure and appointment integrity are fully decoupled. Each generation attempt inserts a **new** `AISummary` row rather than overwriting the previous one, so failed attempts remain in the audit trail; `GET` endpoints always return the most recent row by `created_at`, giving a natural "retry" path (regenerate → new row → latest is now SUCCESS).

## Persistence & retrieval

- `AISummary` (from Phase 2's schema) stores `appointment_id`, `type` (`PRE_VISIT`/`POST_VISIT`), `status` (`PENDING`/`SUCCESS`/`FAILED`), `payload` (JSON, null on failure), `error_message` (null on success), `created_at`.
- Generation endpoints (`POST /appointments/{id}/ai/pre-visit-summary`, `POST /appointments/{id}/ai/post-visit-summary`) are restricted to the resource owner (patient for pre-visit, treating doctor for post-visit).
- Retrieval endpoints (`GET .../ai/pre-visit-summary`, `GET .../ai/post-visit-summary`) are open to any participant on the appointment — patient, treating doctor, or admin — so the doctor can view the pre-visit summary and the patient can view the post-visit summary, per the assignment.

## DEMO_MODE

The AI provider is chosen by `AI_DEMO_MODE` when it is set, and by `DEMO_MODE` when `AI_DEMO_MODE` is unset or blank. So `DEMO_MODE=true` with `AI_DEMO_MODE=false` uses the real LLM (while email and calendar stay mocked), and `DEMO_MODE=false` with `AI_DEMO_MODE=true` keeps the AI mocked. `GET /health` reports the result as `ai_provider: "mock" | "real"`.

When the AI is in demo mode (the default: both unset → `DEMO_MODE=true`), `get_ai_provider()` returns `MockAIProvider`, which:
- never makes a network call,
- derives urgency from simple keyword matching in the symptom text (e.g. "chest pain", "severe" → High; "mild", "slight" → Low; otherwise Medium),
- always returns a schema-valid response, so the happy path is fully exercisable without any LLM credentials.

When the AI is not in demo mode (`AI_DEMO_MODE=false`, or `DEMO_MODE=false` with `AI_DEMO_MODE` unset), `get_ai_provider()` returns `RealAIProvider`, which requires `AI_PROVIDER_API_KEY` and calls the OpenAI-compatible endpoint configured by `AI_PROVIDER_BASE_URL` / `AI_PROVIDER_MODEL` (see `.env.example`). Any provider that exposes an OpenAI-compatible `/chat/completions` API works without code changes.

## Explicitly out of scope

- No diagnosis or autonomous clinical decision-making — the AI only summarizes and triages tone/urgency from patient-reported text.
- The AI provider cannot modify appointment state, directly or indirectly — `AIService` has no reference to `AppointmentService` or the appointment repository's write paths.
- Notification delivery and Google Calendar sync are separate subsystems (Phases 9–10) and are not touched here.
