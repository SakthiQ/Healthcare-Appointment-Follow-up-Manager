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
    PROCESSING --> PENDING : Transient failure (retries < max)
    PROCESSING --> FAILED : Permanent failure (retries >= max)
```

**State Definitions:**
- **PENDING**: Scheduled for delivery
- **PROCESSING**: In-flight by notification worker
- **SENT**: Successfully delivered via provider
- **FAILED**: Permanent failure after maximum retry attempts (e.g. 3 attempts)

---

## Constraints & Integrity Rules

### Double-Booking Prevention
1. **Database Exclusion Constraint / Index:**
   A partial unique index on `(doctor_id, start_time)` for active appointments:
   ```sql
   CREATE UNIQUE INDEX idx_unique_doctor_active_slot 
   ON appointments (doctor_id, start_time) 
   WHERE status IN ('HELD', 'CONFIRMED');
   ```
2. **Explicit Row Locking:**
   When booking or holding, the transaction acquires a `SELECT ... FOR UPDATE` on the target doctor's working schedule or existing appointments to evaluate conflicts atomically.

### Doctor Leave Constraint
- Doctor leave dates prevent slot generation for the full 24-hour day of the leave date.
- Leave creation executes in a transaction that queries overlapping `CONFIRMED` appointments, updates their status to `CONFLICTED`, and enqueues `NotificationJob` records for affected patients.
