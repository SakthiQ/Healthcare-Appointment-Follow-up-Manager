# 01 - Context

## Project Overview
Healthcare Appointment & Follow-up Manager with role-based portals (Patient, Doctor, Admin).
Features patient registration/booking, doctor schedule & leave management, AI pre-visit symptom summaries & post-visit notes, email notifications, Google Calendar sync, and medication reminders.

## Tech Stack
- **Frontend:** React 18 + TypeScript + Vite (Phase 11, in `frontend/`) — React Router, plain `fetch`, no state-management/UI library
- **Backend:** Python + FastAPI (Foundation Phase 1, Domain Models Phase 2, Auth & RBAC Phase 3, Doctor & Schedule Phase 4, Slot Engine & Holds Phase 5, Appointments & Concurrency Phase 6, AI Pre/Post-Visit Phase 7, Doctor Leave Conflict Handling Phase 8, Notifications & Reminders Phase 9, Google Calendar Phase 10)
- **Database:** PostgreSQL + SQLAlchemy ORM + Alembic migrations
- **Validation:** Pydantic & Pydantic-Settings
- **Auth:** JWT (JSON Web Tokens) with bcrypt password hashing (`backend/app/core/security.py`, `backend/services/auth_service.py`)
- **Testing:** pytest & httpx
- **External Integrations:** LLM Provider, Email Provider, Google Calendar API (via provider interfaces)
- **Background Worker:** In-process Python scheduler / background tasks

## Architecture Pattern
- **Modular Monolith:** Clean domain isolation (`backend/app`, `backend/models`, `backend/schemas`, `backend/repositories`, `backend/services`, `backend/api`, `backend/workers`, `backend/providers`).
- **Domain Services:** `DoctorService`, `ScheduleService`, `LeaveService`, `SlotService`, `HoldService`.
- **Scheduling Logic:** Deterministic slot generation from working hours, leave date exclusions, active hold/booking exclusions, boundary validation, and temporary hold expiration.

## Core Principles
1. **Database as Final Authority:** DB constraints and locking prevent double-booking; frontend checks are non-authoritative.
2. **Resilient Integrations:** External API failures (LLM/Email/Calendar) never invalidate or rollback core appointment transactions.
3. **No Unnecessary Infrastructure:** No Redis, Kafka, Kubernetes, or multi-agent frameworks.





