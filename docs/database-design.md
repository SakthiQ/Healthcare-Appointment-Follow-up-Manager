# Database Design

## Overview

The database uses PostgreSQL with SQLAlchemy ORM and Alembic migrations.
The relational design enforces data integrity, appointment state consistency, and double-booking prevention.
All tables are created from zero via Alembic migrations.

---

## Entity Relationship Diagram

```mermaid
erDiagram
    User ||--o| Doctor : "has profile (if DOCTOR)"
    Doctor ||--o{ DoctorWorkingHours : "has"
    Doctor ||--o{ DoctorLeave : "has"
    User ||--o{ Appointment : "patient books"
    Doctor ||--o{ Appointment : "doctor attends"
    User ||--o{ AppointmentHold : "patient holds"
    Doctor ||--o{ AppointmentHold : "for doctor"
    Appointment ||--o| SymptomReport : "has"
    Appointment ||--o{ AISummary : "has"
    Appointment ||--o| Consultation : "has"
    Consultation ||--o| Prescription : "has"
    Prescription ||--o{ Medication : "contains"
    Appointment ||--o{ NotificationJob : "triggers"
    Appointment ||--o{ CalendarEvent : "syncs with"

    User {
        string id PK "UUID str"
        string email UK
        string password_hash
        string full_name
        enum role "PATIENT | DOCTOR | ADMIN"
        boolean is_active
        timestamp created_at
        timestamp updated_at
    }

    Doctor {
        string id PK "UUID str"
        string user_id FK, UK
        string specialization
        int slot_duration_minutes
        boolean is_active
        timestamp created_at
        timestamp updated_at
    }

    DoctorWorkingHours {
        string id PK "UUID str"
        string doctor_id FK
        int day_of_week "0=Mon, 6=Sun"
        time start_time
        time end_time
        boolean is_active
    }

    DoctorLeave {
        string id PK "UUID str"
        string doctor_id FK
        date leave_date
        string reason
        timestamp created_at
    }

    AppointmentHold {
        string id PK "UUID str"
        string doctor_id FK
        string patient_id FK
        timestamp start_time
        timestamp end_time
        timestamp expires_at
        boolean is_active
        timestamp created_at
    }

    Appointment {
        string id PK "UUID str"
        string patient_id FK
        string doctor_id FK
        string doctor_profile_id FK
        timestamp start_time
        timestamp end_time
        enum status "HELD | CONFIRMED | RESCHEDULED | CANCELLED | CONFLICTED | COMPLETED"
        timestamp created_at
        timestamp updated_at
    }

    SymptomReport {
        string id PK "UUID str"
        string appointment_id FK, UK
        text symptoms
        timestamp created_at
    }

    AISummary {
        string id PK "UUID str"
        string appointment_id FK
        enum type "PRE_VISIT | POST_VISIT"
        enum status "PENDING | SUCCESS | FAILED"
        json payload
        text error_message
        timestamp created_at
    }

    Consultation {
        string id PK "UUID str"
        string appointment_id FK, UK
        text notes
        timestamp created_at
    }

    Prescription {
        string id PK "UUID str"
        string consultation_id FK, UK
        text instructions
        timestamp created_at
    }

    Medication {
        string id PK "UUID str"
        string prescription_id FK
        string name
        string dosage
        string frequency
        int duration_days
        timestamp created_at
    }

    NotificationJob {
        string id PK "UUID str"
        string appointment_id FK
        string recipient_id FK
        enum notification_type "BOOKING_CONFIRMATION | APPOINTMENT_REMINDER | CANCELLATION | DOCTOR_LEAVE_CONFLICT | MEDICATION_REMINDER"
        enum status "PENDING | PROCESSING | SENT | FAILED"
        int attempts
        timestamp next_retry_at
        text last_error
        timestamp created_at
        timestamp updated_at
    }

    CalendarEvent {
        string id PK "UUID str"
        string appointment_id FK
        string recipient_type "PATIENT | DOCTOR"
        string external_event_id
        enum status "SYNCED | PENDING_SYNC | FAILED"
        timestamp created_at
        timestamp updated_at
    }
```


---

## State Machines

### 1. Appointment State Machine

```mermaid
stateDiagram-v2
    [*] --> HELD : Hold created
    HELD --> CONFIRMED : Patient confirms hold
    HELD --> CANCELLED : Hold expires / Patient releases
    CONFIRMED --> RESCHEDULED : Patient/Admin reschedules
    CONFIRMED --> CANCELLED : Patient/Doctor/Admin cancels
    CONFIRMED --> CONFLICTED : Doctor leave added
    CONFIRMED --> COMPLETED : Consultation completed
    RESCHEDULED --> COMPLETED : Consultation completed
    RESCHEDULED --> CONFIRMED : Reschedule confirmed
    RESCHEDULED --> CANCELLED : Cancelled during reschedule
    CONFLICTED --> RESCHEDULED : Patient re-books slot
    CONFLICTED --> CANCELLED : Patient cancels conflicted appt
```

**State Definitions:**
- **HELD**: Slot temporarily reserved for patient (temporary state before confirmation)
- **CONFIRMED**: Booking finalized and active
- **RESCHEDULED**: Moved to a new time slot
- **CANCELLED**: Booking terminated; slot released
- **CONFLICTED**: Doctor leave overlaps this booking; requires patient action
- **COMPLETED**: Consultation finished by doctor

### 2. Slot State Machine

```mermaid
stateDiagram-v2
    [*] --> AVAILABLE : Working hours minus leave & existing bookings
    AVAILABLE --> HELD : Hold created by patient
    HELD --> AVAILABLE : Hold expires (after 10 mins)
    HELD --> BOOKED : Appointment confirmed
    BOOKED --> AVAILABLE : Appointment cancelled
```

**State Definitions:**
- **AVAILABLE**: Slot exists in working hours, no active hold, no booking, no leave
- **HELD**: Temporarily held by a patient (blocks other holds/bookings)
- **BOOKED**: Occupied by a CONFIRMED appointment

### 3. Notification Job State Machine

```mermaid
stateDiagram-v2
    [*] --> PENDING : Job created
    PENDING --> PROCESSING : Picked up by worker
    PROCESSING --> SENT : Delivery success
    PROCESSING --> PENDING : Transient failure, or worker died (retries < max)
    PROCESSING --> FAILED : Permanent failure (retries >= max)
```

**State Definitions:**
- **PENDING**: Scheduled for delivery
- **PROCESSING**: In-flight by notification worker. A job still here after `NOTIFICATION_PROCESSING_TIMEOUT_MINUTES` had its worker die and is requeued, so delivery is at-least-once
- **SENT**: Successfully delivered via provider
- **FAILED**: Permanent failure after maximum retry attempts (e.g. 3 attempts)

---

## Constraints & Integrity Rules

### Double-Booking Prevention
1. **Partial unique index** on `(doctor_profile_id, start_time)` for active appointments (same start time):
   ```sql
   CREATE UNIQUE INDEX uq_doctor_profile_start_time_active
   ON appointments (doctor_profile_id, start_time)
   WHERE status IN ('HELD', 'CONFIRMED', 'RESCHEDULED');
   ```
2. **Exclusion constraint** (PostgreSQL, migration `a3c5d7e9f1b2`; needs `btree_gist`) for any overlap, whatever the start times:
   ```sql
   ALTER TABLE appointments ADD CONSTRAINT ex_doctor_profile_no_overlap_active
   EXCLUDE USING gist (doctor_profile_id WITH =, tstzrange(start_time, end_time) WITH &&)
   WHERE (status IN ('HELD', 'CONFIRMED', 'RESCHEDULED'));
   ```
   SQLite (tests, local dev) enforces the same rule with `BEFORE INSERT` / `BEFORE UPDATE` triggers. The migration fails if existing data already has overlapping active appointments for a doctor; cancel or move one of each pair first.
3. **Explicit Row Locking:**
   Booking and rescheduling run `SELECT ... FOR UPDATE` on the overlap query and on the appointment being rescheduled or cancelled. This reduces conflict churn but is not relied on for correctness: a free slot returns no rows to lock. Constraints 1 and 2 are the final authority.

### Other tables and columns (added later)
- `doctors.timezone` (varchar(64), default `'UTC'`): IANA zone the doctor's working hours and leave dates are written in.
- `users.token_version` (int, default 0): bumped by logout; access tokens carry it and are rejected on mismatch.
- `login_throttles(key PK, failed_count, window_started_at, locked_until)`: failed-login counters, `key` = SHA-256 of `email|client IP`.
- `appointment_holds`: partial unique index `uq_active_hold_doctor_start_time` on `(doctor_id, start_time) WHERE is_active`.
- `users.email_verified` (bool, not null): false until the emailed link is followed. Pre-existing rows and admin-created doctors are true.
- `rate_limits(key PK, count, window_started_at)`: fixed-window request counters; `key` = SHA-256 of `bucket|identity`.
- `auth_tokens(id PK, user_id FK, purpose, token_hash UNIQUE, expires_at, used_at, created_at)`: single-use password-reset and email-verification tokens; only the hash is stored.
- `audit_logs(id PK, occurred_at, actor_user_id, actor_role, action, resource_type, resource_id, patient_id, ip, detail)`: append-only, deliberately no foreign keys, indexed on time, actor, action, resource and patient.
- `notificationtype` enum gained `PASSWORD_RESET` and `EMAIL_VERIFICATION`. On PostgreSQL the migration runs `ALTER TYPE ... ADD VALUE` outside a transaction block; PostgreSQL cannot remove an enum value, so a downgrade leaves them (unused).

### Doctor Leave Constraint
- Doctor leave dates prevent slot generation for the full 24-hour day of the leave date.
- Leave creation executes in a transaction that queries overlapping `CONFIRMED` appointments, updates their status to `CONFLICTED`, and enqueues `NotificationJob` records for affected patients.
