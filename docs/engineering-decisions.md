# Engineering Decisions

## Key Architectural Decisions

### 1. Framework Choice: Python + FastAPI
- **Why FastAPI?** FastAPI provides native asynchronous I/O support, automatic OpenAPI documentation, strict type-checking via Pydantic, and lightweight runtime performance compared to traditional frameworks like Django or Flask.
- **Dependency Injection:** Built-in DI makes mock providers easy to inject for `DEMO_MODE` and unit testing.

### 2. Database Choice: PostgreSQL
- **Why PostgreSQL?** PostgreSQL offers robust transactional support (ACID compliance), fine-grained row-level locking (`SELECT ... FOR UPDATE`), and partial unique indexes needed for concurrency-safe double-booking prevention.

### 3. Architecture Pattern: Modular Monolith
- **Why Modular Monolith?** Avoids unnecessary infrastructure complexity (no microservices, Kafka, Kubernetes, or service meshes) while keeping domain logic clean, encapsulated, and strictly separated into modules (Auth, Doctor, Slot, Appointment, AI, Notification, Calendar).

### 4. Double-Booking & Concurrency Strategy
- Frontend availability checks are treated purely as UI guidance and are **never trusted as authoritative**.
- Concurrency control is enforced at the database level:
  1. Transactional isolation (`READ COMMITTED` or `REPEATABLE READ`).
  2. Database row-level locking (`SELECT ... FOR UPDATE`) during slot hold and confirmation.
  3. Unique partial index on `(doctor_id, start_time)` for active appointment states (`HELD`, `CONFIRMED`).

### 5. Isolation of External Integrations
- All external dependencies (LLM, Email Provider, Google Calendar API) are hidden behind abstract interface layers (`AIProvider`, `EmailProvider`, `CalendarProvider`).
- **Resilience:** Failures in external services NEVER break core appointment creation:
  - **AI Failure:** Appointment remains valid; AI job is logged with status `FAILED`.
  - **Email Failure:** Appointment remains valid; `NotificationJob` is scheduled for retry.
  - **Calendar Failure:** Appointment remains valid; `CalendarEvent` is scheduled for sync reconciliation.

### 6. Background Processing & DEMO_MODE
- **Background Worker:** A lightweight, process-internal Python worker handles retries and async tasks without needing external message queues like Celery or Redis.
- **DEMO_MODE Support:** Switching `DEMO_MODE=true` substitutes external provider implementations with deterministic mock providers, enabling full system evaluation without external API credentials. `AI_DEMO_MODE`, `EMAIL_DEMO_MODE` and `CALENDAR_DEMO_MODE` can override it per integration (unset = follow `DEMO_MODE`).
