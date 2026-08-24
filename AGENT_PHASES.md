# Healthcare Appointment & Follow-up Manager
## Agent-Driven Refactoring & Build Phases

This document contains the 14-phase implementation sequence for building/refactoring the Healthcare Appointment & Follow-up Manager.

The phases are intentionally separated so each agent works on one specific subsystem, keeps code simple, and leaves the repository in a working state before the next phase.

The original assignment requirements are the authoritative product scope.

---

# Global Engineering Rules

Use these rules for every phase.

```text
Read AGENT_SPEC.md before making changes.

1. Inspect existing code before rewriting it.
2. Implement only the current phase.
3. Do not modify unrelated modules.
4. Preserve working functionality.
5. Prefer simple code over clever code.
6. Prefer a modular monolith.
7. Keep API routes thin.
8. Put business rules in services.
9. Put persistence operations behind repositories where useful.
10. Keep external providers behind interfaces/abstractions.
11. Never hardcode secrets.
12. Never fabricate test results.
13. Every bug fix requires a regression test.
14. Every phase must leave the repository runnable.
15. Run relevant tests before declaring the phase complete.
16. Do not introduce microservices, Kafka, Kubernetes, RAG,
    multi-agent systems, or other unnecessary infrastructure.
17. Do not expand product scope beyond AGENT_SPEC.md.
18. Do not mark a requirement complete unless it is implemented
    and testable.
19. When uncertain, prefer the simplest implementation that
    satisfies the requirement.
20. At the end of every phase, report:
    - files changed
    - functionality implemented
    - tests added
    - tests executed
    - test results
    - known issues
    - remaining requirements
```

---

You are the lead software architect starting a new Healthcare Appointment & Follow-up Manager project from zero.

There is NO existing implementation.

Read:
- AGENT_SPEC.md
- AGENT_PHASES.md
- the original assignment requirements available in the project

Treat AGENT_SPEC.md as the authoritative project specification.

Your task is ARCHITECTURE AND PLANNING ONLY.

Do NOT implement application features yet.
Do NOT create business logic.
Do NOT build the frontend.
Do NOT integrate external APIs.

First understand the complete assignment.

The system must support:

- separate patient, doctor, and admin portals
- patient registration and login
- doctor search by specialization
- admin-managed doctor profiles
- doctor specialization
- doctor working hours
- slot duration
- doctor leave days
- appointment booking
- slot holding
- double-booking prevention
- safe simultaneous booking
- doctor leave conflict handling
- patient notifications
- AI pre-visit summary
- AI post-visit summary
- prescription
- medication reminders
- booking/reminder/cancellation emails
- Google Calendar create/update/delete
- Google OAuth 2.0
- background jobs
- email retries
- graceful LLM failure
- role-based authorization
- required documentation

Use this technology stack:

Frontend:
React + TypeScript

Backend:
Python + FastAPI

Database:
PostgreSQL

ORM:
SQLAlchemy

Migrations:
Alembic

Validation:
Pydantic

Authentication:
JWT

Testing:
pytest

External services:
LLM provider
Email provider
Google Calendar API

Background processing:
simple Python worker/scheduler

Architecture requirement:

Use a modular monolith.

Do NOT introduce:
- microservices
- Kafka
- Kubernetes
- RAG
- multi-agent architecture
- unnecessary distributed infrastructure

Design the following:

1. Overall system architecture
2. Backend module structure
3. Frontend structure
4. Database entities and relationships
5. Authentication and RBAC model
6. Appointment lifecycle
7. Slot lifecycle
8. Slot hold mechanism
9. Doctor leave conflict workflow
10. AI provider abstraction
11. Email provider abstraction
12. Calendar provider abstraction
13. Background-job architecture
14. Notification lifecycle
15. Error-handling strategy
16. Transaction boundaries
17. Concurrency strategy
18. Security boundaries
19. Testing strategy
20. DEMO_MODE strategy
21. Deployment architecture

Define these state machines explicitly.

Appointment states:

HELD
CONFIRMED
RESCHEDULED
CANCELLED
CONFLICTED
COMPLETED

Slot states:

AVAILABLE
HELD
BOOKED

Notification states:

PENDING
PROCESSING
SENT
FAILED

Define how each state transition occurs and what conditions are required.

For double-booking, design a database-level strategy.

The frontend availability check must never be considered the final authority.

The database must be the final authority for appointment consistency.

For external services, design the system so:

LLM failure
→ appointment remains valid

Email failure
→ appointment remains valid + notification retry

Calendar failure
→ appointment remains valid + Calendar retry/reconciliation

Create the following files:

docs/architecture.md
docs/database-design.md
docs/engineering-decisions.md
docs/system-design.md
docs/requirement-map.md

Create a clean initial project directory structure.

The requirement map must map every assignment requirement to:
- planned module
- planned API/functionality
- planned test/evidence

The engineering decisions document must explain:
- why FastAPI
- why PostgreSQL
- why modular monolith
- how double-booking is prevented
- why external services are isolated
- why AI is non-critical to appointment creation
- why mock providers are needed for evaluation/demo mode

The system design must specifically cover:
- double-booking prevention
- doctor leave conflict handling
- slot hold mechanism
- notification failure handling

Do not implement features during this phase.

Acceptance criteria:

- architecture is documented
- database entities are identified
- module boundaries are defined
- appointment state machine is defined
- slot/hold state machine is defined
- notification state machine is defined
- concurrency strategy is defined
- provider abstractions are defined
- security model is defined
- testing strategy is defined
- complete requirement map exists
- initial repository structure exists
- no business functionality has been implemented

Stop after completing this phase.

Do NOT proceed to Phase 1.


# Phase 1 — Project Foundation

## Goal

Create a clean Python backend foundation.

## Prompt

```text
Implement only the backend foundation.

Read:
- AGENT_SPEC.md
- docs/REFACTOR_PLAN.md
- docs/REQUIREMENT_MAP.md

Target stack:

Backend:
- Python
- FastAPI
- SQLAlchemy
- PostgreSQL
- Alembic
- Pydantic

Implement:

1. FastAPI application structure
2. Configuration management
3. Environment variable loading
4. PostgreSQL connection
5. SQLAlchemy setup
6. Alembic migrations
7. Base model configuration
8. Dependency injection structure
9. Common exception handling
10. Structured application logging
11. Health endpoint
12. OpenAPI configuration
13. Test configuration

Use a clean modular-monolith structure.

Keep route handlers thin.
Business logic must not be placed directly in API routes.

Suggested structure:

backend/
  app/
    main.py
    config.py
    database.py
    dependencies.py
  models/
  schemas/
  repositories/
  services/
  api/
  workers/
  tests/

Do not implement:
- authentication
- appointments
- AI
- notifications
- Calendar
- frontend

Add tests for:
- application startup
- health endpoint
- database connection
- configuration loading

Run all tests before finishing.

Acceptance criteria:
- application starts successfully
- database connection works
- migrations work
- tests pass
- project structure is simple and understandable

Do not introduce microservices, Kafka, Kubernetes, Redis, or other infrastructure not required by the assignment.
```

## Gate

Application starts, migrations work, and foundation tests pass.

---

# Phase 2 — Database & Domain Models

## Goal

Create the relational model correctly before business logic grows.

## Prompt

```text
Implement ONLY the database/domain model layer.

Read AGENT_SPEC.md and docs/REFACTOR_PLAN.md.

Create SQLAlchemy models and migrations for the core domain:

User
Doctor
DoctorWorkingHours
DoctorLeave

Appointment
AppointmentHold

SymptomReport
AISummary

Consultation
Prescription
Medication

NotificationJob
CalendarEvent

Use appropriate:
- primary keys
- foreign keys
- indexes
- uniqueness constraints
- enums
- timestamps
- nullable/non-nullable fields
- relationships

Define the appointment status model explicitly.

Recommended statuses:

HELD
CONFIRMED
RESCHEDULED
CANCELLED
CONFLICTED
COMPLETED

Define hold fields including expiration.

Define notification job fields including:
- status
- attempt count
- next retry time
- last error

Define Calendar event persistence including external event identifiers.

Do not implement:
- business services
- API endpoints
- frontend
- AI calls
- email calls
- Google API calls

Create:
docs/database-design.md

The document must explain the relationships and the constraints that protect appointment integrity.

Add model-level/database tests where appropriate.

Acceptance criteria:
- migrations apply cleanly
- database can be recreated from zero
- relationships are valid
- required constraints exist
- tests pass

Do not introduce unnecessary database abstractions.
```

## Gate

A fresh database can be created entirely through migrations.

---

# Phase 3 — Authentication & RBAC

## Goal

Implement authentication and role-based authorization cleanly.

## Prompt

```text
Implement authentication and authorization only.

Roles:
PATIENT
DOCTOR
ADMIN

Implement:

- patient registration
- login
- password hashing
- JWT authentication
- authenticated-user dependency
- role-based authorization
- ownership checks
- authentication error handling

Security requirements:

1. Passwords must never be stored in plaintext.
2. Secrets must come from environment variables.
3. Role checks must happen server-side.
4. Patients must not access other patients' private data.
5. Doctors must not access unauthorized patient records.
6. Admin-only operations must be protected.
7. Invalid and expired credentials must be rejected.

Create authentication APIs.

Create tests for:
- successful registration
- duplicate registration
- successful login
- invalid login
- authenticated access
- unauthenticated access
- patient role restriction
- doctor role restriction
- admin role restriction
- cross-user resource access

Do not implement:
- appointment booking
- scheduling
- AI
- email
- Calendar
- frontend

Keep authentication logic isolated under an auth/security module.

Acceptance criteria:
- all auth tests pass
- RBAC is reusable by future modules
- no authorization logic is duplicated across endpoints
```

## Gate

Authentication and RBAC tests pass.

---

# Phase 4 — Doctor & Schedule Management

## Goal

Implement doctor profiles, working hours, slot duration, leave, and specialization search.

## Prompt

```text
Implement the doctor and schedule management subsystem.

Scope:

ADMIN:
- create doctor
- update doctor
- activate/deactivate doctor
- set specialization
- configure working hours
- configure slot duration
- create/manage leave dates

PATIENT:
- search doctors by specialization
- retrieve doctor profile
- retrieve doctor schedule information

Create clean service boundaries:

DoctorService
ScheduleService
LeaveService

Keep API routes thin.

Do not implement appointment creation yet.

Business rules:
- invalid working hours must be rejected
- slot duration must be valid
- leave must belong to the correct doctor
- inactive doctors must not appear as bookable doctors
- leave dates must be represented explicitly

Create tests for:
- doctor creation
- doctor update
- specialization search
- working hours
- invalid schedule
- slot duration validation
- leave creation
- inactive doctor behavior

Do not implement:
- appointment booking
- AI
- notifications
- Calendar
- frontend

Acceptance criteria:
- admin can fully configure a doctor
- patient can search doctors
- schedule data is persisted correctly
- tests pass
```

## Gate

Doctor configuration and specialization search work independently.

---

# Phase 5 — Slot Engine & Slot Holds

## Goal

Separate scheduling logic from appointment logic.

## Prompt

```text
Implement the slot-generation and slot-hold subsystem only.

Create:

SlotService
HoldService

Responsibilities of SlotService:
- generate slots from working hours
- apply slot duration
- exclude leave
- determine available slots
- validate slot boundaries

Responsibilities of HoldService:
- create hold
- retrieve hold
- confirm hold
- release hold
- expire hold

Hold requirements:
- hold belongs to one doctor, one patient, and one slot
- hold has an expiration time
- expired holds cannot be confirmed
- expired holds must no longer block the slot
- only the correct patient can confirm their hold

Do not implement final appointment booking.

Do not put notification, AI, email, or Calendar logic here.

Add tests for:
- slot generation
- slots outside working hours
- leave exclusion
- valid hold
- duplicate hold
- expired hold
- successful hold confirmation
- invalid hold confirmation

The system must keep scheduling logic deterministic and database-backed.

Acceptance criteria:
- slots can be generated correctly
- holds can be created/expired/confirmed
- tests pass
- slot logic is independent of appointment creation
```

## Gate

Slots and holds work without appointment creation.

---

# Phase 6 — Appointment Booking, Rescheduling, Cancellation & Concurrency

## Goal

Implement the appointment lifecycle and guarantee safe concurrent booking.

This is the most important reliability phase.

## Prompt

```text
Implement the appointment lifecycle.

This is a reliability-critical subsystem.

Implement:

AppointmentService

Operations:
- create/confirm appointment
- reschedule appointment
- cancel appointment
- retrieve appointment
- list appointments

Appointment lifecycle:

HELD
→ CONFIRMED
→ COMPLETED

CONFIRMED
→ RESCHEDULED
→ CANCELLED
→ CONFLICTED

Requirements:

1. Booking must be transactional.
2. The database must be the final authority for slot availability.
3. Frontend availability checks must never be trusted as final protection.
4. Two simultaneous booking attempts for the same doctor and slot must not both succeed.
5. A cancelled appointment must release the booking.
6. Rescheduling must validate the new slot again.
7. Rescheduling must not create a second booking.
8. An expired hold must not be confirmable.
9. Patient and doctor access must be authorized.

Use appropriate PostgreSQL transaction and locking/constraint mechanisms.

Do not solve concurrency only with application-level checks.

Create a real concurrency test using 100 simultaneous booking attempts for the same doctor and slot.

Required result:
- exactly 1 successful booking
- all other requests fail safely with a conflict

Also test:
- normal booking
- booking unavailable slot
- expired hold
- reschedule
- cancel
- repeated cancellation
- reschedule to unavailable slot
- unauthorized appointment access

Do not implement email, AI, or Calendar behavior inside this service.

The appointment transaction must create the core appointment reliably without waiting for external services.

Acceptance criteria:
- concurrency test passes
- appointment state transitions are valid
- no double booking is possible
- all appointment tests pass
```

## Gate

**Do not proceed if the 100-request concurrency test fails.**

---

# Phase 7 — AI Pre-Visit & Post-Visit System

## Goal

Implement structured, isolated, testable AI behavior.

## Prompt

```text
Implement the AI subsystem.

Create these abstractions:

AIProvider
RealAIProvider
MockAIProvider
AIService

Pre-visit output must contain exactly:

{
  "urgency": "Low | Medium | High",
  "chief_complaint": "string",
  "suggested_questions": [
    "string",
    "string",
    "string"
  ]
}

Requirements:
- urgency must be one of Low/Medium/High
- exactly 3 suggested questions
- response validated with Pydantic
- result stored in database
- result associated with the appointment
- doctor can view the pre-visit summary

Post-visit output must provide:
- patient-friendly summary
- medication schedule
- follow-up steps

Create prompt constants/templates and document them.

AI failure handling:
- timeout
- provider unavailable
- malformed response
- invalid schema

If AI fails:
- appointment must remain valid
- AI status becomes FAILED or equivalent
- failure is recorded
- retry/fallback path exists

Do not allow the AI provider to directly modify appointment state.

Do not implement diagnosis or autonomous clinical decision-making.

Create tests for:
- valid pre-visit output
- invalid JSON
- invalid urgency
- wrong number of questions
- provider timeout
- provider failure
- valid post-visit output
- output persistence

Support DEMO_MODE with MockAIProvider.

Acceptance criteria:
- strict output contract
- outputs stored in DB
- doctor can retrieve summary
- AI failure does not break appointment workflow
- tests pass
```

## Gate

AI failure cannot break the appointment workflow.

---

# Phase 8 — Doctor Leave & Conflict Handling

## Goal

Handle existing appointments when a doctor is marked on leave.

## Prompt

```text
Implement doctor leave conflict handling.

When an admin creates a leave period/date:

1. Validate the leave.
2. Find all existing appointments overlapping the leave.
3. Mark affected appointments as CONFLICTED.
4. Preserve the original appointment information.
5. Create notification jobs for affected patients.
6. Allow the affected appointments to be inspected by admin.
7. Do not silently delete affected appointments.

The operation must be transactional.

Create:

DoctorLeaveService

Keep leave logic out of controllers.

Test:
- leave with no appointments
- leave with one appointment
- leave with multiple appointments
- multiple leave dates
- repeated leave creation
- affected appointment identification
- conflicted appointment status
- notification job creation
- unrelated appointments remain unchanged

Do not implement actual email delivery here.
Only create notification jobs for the notification subsystem.

Acceptance criteria:
- every affected appointment is detected
- unaffected appointments remain unchanged
- conflict state is persisted
- notification jobs are generated correctly
- tests pass
```

## Gate

Leave conflict detection is deterministic and tested.

---

# Phase 9 — Notifications, Email Retries & Medication Reminders

## Goal

Build one simple notification subsystem for email and reminders.

## Prompt

```text
Implement the notification subsystem.

Create:

NotificationService
NotificationJobRepository
NotificationWorker
EmailProvider
RealEmailProvider
MockEmailProvider
ReminderService

Notification types:

BOOKING_CONFIRMATION
APPOINTMENT_REMINDER
CANCELLATION
DOCTOR_LEAVE_CONFLICT
MEDICATION_REMINDER

Recipients:
PATIENT
DOCTOR

Every notification job must store:
- appointment or related resource
- recipient
- notification type
- status
- attempts
- next_retry_at
- last_error
- timestamps

States:

PENDING
PROCESSING
SENT
FAILED

Requirements:
1. appointment success must not depend on email success
2. failed email must be retryable
3. retry attempts must be bounded
4. failures must be persisted
5. duplicate job processing must be minimized
6. booking confirmation goes to patient and doctor
7. reminders go to patient and doctor where applicable
8. cancellation goes to patient and doctor
9. leave-conflict notifications go to affected patients

Implement medication reminders based on prescription frequency using the same notification system.

Medication data must include enough information to determine:
- medication
- dosage
- frequency
- duration/instructions

Add tests for:
- successful email
- transient email failure
- retry
- permanent failure
- booking notifications
- reminder notifications
- cancellation notifications
- leave-conflict notifications
- patient recipient
- doctor recipient
- medication reminder generation

Support DEMO_MODE using MockEmailProvider.

Do not implement Google Calendar here.

Acceptance criteria:
- background notification processing works
- failed jobs retry
- notification state is observable
- appointment transaction is independent of email
- tests pass
```

## Gate

Email failure never invalidates an already-committed appointment.

---

# Phase 10 — Google Calendar Integration

## Goal

Isolate Google Calendar operations from appointment business logic.

## Prompt

```text
Implement Google Calendar integration through a provider abstraction.

Create:

CalendarProvider
GoogleCalendarProvider
MockCalendarProvider
CalendarService

Requirements:

1. Google OAuth 2.0
2. create Calendar event on booking
3. create events for both patient and doctor where the design requires separate calendars
4. update Calendar events on reschedule
5. delete Calendar events on cancellation
6. persist external Calendar event identifiers
7. handle Google API failures without invalidating the appointment
8. support retry/reconciliation
9. prevent uncontrolled duplicate event creation on retry

Use environment variables for Google credentials.

Do not hardcode OAuth secrets.

Create DEMO_MODE using MockCalendarProvider.

Calendar operations must be initiated through the CalendarService/provider abstraction, not directly from route handlers.

Tests:
- create event
- update event
- delete event
- Calendar provider unavailable
- retry
- repeated create operation
- reschedule synchronization
- cancellation synchronization

Do not modify the core appointment transaction to wait for Google Calendar success.

Acceptance criteria:
- real Google provider exists
- OAuth configuration is documented
- mock provider allows local/evaluator execution
- Calendar failures do not corrupt appointment state
- tests pass
```

## Gate

Core appointment flow works even when Calendar is unavailable.

---

# Phase 11 — Frontend: Patient, Doctor & Admin Portals

## Goal

Build the required workflows without overcomplicating the UI.

## Prompt

```text
Implement the frontend using React + TypeScript.

Build three role-specific portal experiences.

PATIENT:
- register
- login
- dashboard
- doctor search by specialization
- doctor profile
- available slot display
- slot selection/hold
- symptom form
- pre-visit AI summary review
- booking confirmation
- appointment list
- appointment details
- reschedule
- cancellation

DOCTOR:
- login
- dashboard
- appointment list
- appointment details
- pre-visit AI summary
- consultation notes
- prescription
- post-visit AI summary

ADMIN:
- login
- dashboard
- doctor management
- specialization
- working hours
- slot duration
- leave management
- conflicted appointment view

Requirements:
- role-based navigation
- clear loading states
- clear API errors
- form validation
- confirmation states
- no fabricated backend data
- use actual APIs
- responsive layout

Prioritize functional clarity over animations and visual complexity.

Do not add unrelated product features.

Backend remains the source of truth for:
- authorization
- slot availability
- appointment state
- AI state
- notification state

Acceptance criteria:
- each role can complete its required workflow
- frontend uses real backend APIs
- invalid operations display useful errors
- no critical broken workflow remains
```

## Gate

Patient, doctor, and admin can complete their core workflows.

---

# Phase 12 — Integration & End-to-End Testing

## Goal

Verify that the complete system works across modules.

## Prompt

```text
Do not add new product functionality unless required to repair a broken workflow.

Perform complete end-to-end validation.

Test the following exact workflows.

PATIENT BOOKING:

register
→ login
→ search doctor
→ select slot
→ hold slot
→ enter symptoms
→ generate pre-visit AI summary
→ confirm appointment
→ notification jobs created
→ Calendar jobs/events created

DOCTOR WORKFLOW:

login
→ view appointment
→ view pre-visit AI summary
→ submit consultation
→ submit prescription
→ generate post-visit AI summary
→ create medication reminder jobs

ADMIN WORKFLOW:

login
→ create/manage doctor
→ configure working hours
→ configure slot duration
→ create leave
→ detect conflicting appointments
→ create notification jobs

RESCHEDULE:

existing appointment
→ select new slot
→ revalidate availability
→ update appointment
→ update Calendar
→ create required notifications

CANCELLATION:

existing appointment
→ cancel
→ release slot
→ update appointment state
→ delete Calendar event
→ create cancellation notifications

FAILURE TESTS:

LLM unavailable
Email unavailable
Calendar unavailable
invalid AI response
expired hold
simultaneous booking attempts

For every workflow verify:
- HTTP response
- database state
- authorization
- background jobs
- provider interaction
- resulting state

Fix integration issues.

Every discovered bug must receive a regression test.

Acceptance criteria:
- all critical end-to-end workflows pass
- no module bypasses the service/business layer
- no external service is required for core appointment integrity
```

## Gate

All critical workflows pass end-to-end.

---

# Phase 13 — Final Audit, Documentation, Security & Deployment

## Goal

Prepare the repository for submission and automated/human review.

## Prompt

```text
Act as the final release engineer and evaluator.

Do not add unnecessary features.

Perform a complete final audit of the repository against AGENT_SPEC.md and the original assignment.

FIRST:
Audit every requirement.

For each requirement record:
- implementation
- file/module
- API
- test/evidence
- status

No requirement may be marked complete without evidence.

SECOND:
Perform a code-quality audit.

Check for:
- duplicated logic
- oversized functions
- route handlers containing business logic
- unnecessary abstractions
- dead code
- debug code
- hardcoded secrets
- inconsistent naming
- poor error handling
- missing validation
- unsafe authorization
- race conditions
- unnecessary dependencies

THIRD:
Perform a security audit.

Check:
- authentication
- authorization
- resource ownership
- password handling
- secret handling
- CORS
- input validation
- role isolation

FOURTH:
Perform a reliability audit.

Check:
- double-booking
- simultaneous booking
- slot holds
- hold expiry
- doctor leave conflicts
- notification retries
- LLM failures
- Calendar failures
- idempotency
- rescheduling
- cancellation

FIFTH:
Run all tests from a clean environment.

Do not fabricate test results.

SIXTH:
Create/update:

README.md
.env.example
docs/architecture.md
docs/database-design.md
docs/ai-design.md
docs/failure-handling.md
docs/requirement-mapping.md
docs/system-design.md

README must contain:
- project overview
- stack
- architecture
- setup instructions
- environment variables
- API documentation
- database schema overview
- LLM prompts
- Google OAuth 2.0 setup
- DEMO_MODE
- test instructions
- deployment information
- demo credentials where appropriate
- known limitations

The system-design write-up must be no more than 800 words and explicitly cover:
- double-booking prevention
- doctor leave conflict handling
- slot hold mechanism
- notification failure handling

SEVENTH:
Verify deployment.

Confirm:
- frontend hosted
- backend hosted
- database connected
- DEMO_MODE works if external credentials are absent
- critical workflows work in the hosted environment

FINAL OUTPUT:

1. Requirement coverage summary
2. Tests executed and results
3. Remaining known issues
4. Security findings
5. Reliability findings
6. Deployment status
7. Final readiness assessment

Do not claim production readiness if evidence does not support it.
```

## Gate

Nothing should be considered final until the requirement audit, tests, documentation, and hosted application have been checked.

---

# Recommended Execution Order

```text
PHASE 0  → Audit
PHASE 1  → Foundation
PHASE 2  → Database
PHASE 3  → Auth/RBAC
PHASE 4  → Doctors/Schedules
PHASE 5  → Slots/Holds
PHASE 6  → Appointments/Concurrency
PHASE 7  → AI
PHASE 8  → Leave Conflicts
PHASE 9  → Notifications/Reminders
PHASE 10 → Google Calendar
PHASE 11 → Frontend
PHASE 12 → Integration Testing
PHASE 13 → Final Audit/Docs/Deployment
```

## Important operating rule

Do not give the agent all 14 prompts at once.

Run:

```text
Phase 0
↓
inspect result
↓
Phase 1
↓
test
↓
Phase 2
↓
test
...
```

This keeps the codebase clean and prevents one agent session from making uncontrolled changes across the entire application.
