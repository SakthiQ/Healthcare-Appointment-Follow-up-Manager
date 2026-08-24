# System Design

This document details the core reliability mechanisms of the Healthcare Appointment & Follow-up Manager.

---

## 1. Double-Booking Prevention Strategy

Preventing double-booking requires a multi-layered defence where the database is the final authority.

```mermaid
sequenceDiagram
    autonumber
    actor Patient
    participant API as API Layer
    participant ApptSvc as Appointment Service
    participant DB as PostgreSQL Database

    Patient->>API: POST /api/appointments/confirm
    API->>ApptSvc: confirm_booking(patient_id, hold_id)
    ApptSvc->>DB: BEGIN TRANSACTION
    ApptSvc->>DB: SELECT * FROM appointment_holds WHERE id = hold_id FOR UPDATE
    alt Hold is expired or invalid
        ApptSvc->>DB: ROLLBACK
        ApptSvc-->>API: Error: Hold Expired / Invalid
        API-->>Patient: 400 Bad Request / 409 Conflict
    else Hold is valid
        ApptSvc->>DB: SELECT * FROM appointments WHERE doctor_id = doc_id AND start_time = slot_time AND status IN ('HELD', 'CONFIRMED') FOR UPDATE
        alt Existing active booking found
            ApptSvc->>DB: ROLLBACK
            ApptSvc-->>API: Error: Slot Already Booked
            API-->>Patient: 409 Conflict
        else Slot is free
            ApptSvc->>DB: INSERT INTO appointments (status='CONFIRMED', ...)
            ApptSvc->>DB: UPDATE appointment_holds SET is_active=false WHERE id = hold_id
            ApptSvc->>DB: COMMIT (Triggers DB Unique Index check)
            ApptSvc-->>API: Success (Appointment Confirmed)
            API-->>Patient: 200 OK
        end
    end
```

### Key Controls:
1. **Row-Level Locking:** `FOR UPDATE` lock prevents concurrent transactions from reading stale slot states.
2. **Database Constraint:** Partial unique index `idx_unique_doctor_active_slot` acts as the final guard against race conditions.

---

## 2. Doctor Leave Conflict Workflow

When an admin marks a doctor as on leave for a specific date:

```mermaid
flowchart TD
    A[Admin submits Leave Date] --> B[Begin DB Transaction]
    B --> C[Validate Leave Period]
    C --> D[Insert DoctorLeave Record]
    D --> E[Query CONFIRMED Appointments for Doctor on Leave Date]
    E --> F{Any Appointments Found?}
    F -- Yes --> G[Update Appointment Status to CONFLICTED]
    G --> H[Create NotificationJobs for Affected Patients]
    F -- No --> I[Commit Transaction]
    H --> I
    I --> J[Return Leave Creation Summary to Admin]
```

### Key Controls:
- **Atomicity:** Leave creation and appointment status conversion to `CONFLICTED` occur within the same database transaction.
- **Data Preservation:** Appointments are marked `CONFLICTED`, preserving historical details for rescheduling without data loss.

---

## 3. Slot Hold Mechanism

To prevent race conditions while a patient fills out symptom forms:

1. **Hold Request:** Patient selects a slot; `HoldService` creates an `AppointmentHold` record with `expires_at = now() + 10 minutes`.
2. **Hold Exclusions:** Slot generation logic ignores slots with active, non-expired holds.
3. **Automatic Expiry:** Background `HoldExpiryWorker` periodically deactivates expired holds.
4. **Confirmation Guard:** Attempting to confirm an expired hold rejects the transaction and forces slot re-selection.

---

## 4. Notification Failure Handling & Retries

Notifications must never break appointment creation or state transitions.

```mermaid
flowchart TD
    A[Appointment Event Created] --> B[Insert NotificationJob status=PENDING]
    B --> C[Commit Main Transaction]
    C --> D[Worker Polls PENDING Jobs]
    D --> E[Worker Calls EmailProvider]
    E --> F{Delivery Success?}
    F -- Yes --> G[Update Job status=SENT]
    F -- No --> H{Attempts < Max 3?}
    H -- Yes --> I[Update Job status=PENDING, next_retry_at = now + backoff]
    H -- No --> J[Update Job status=FAILED, log last_error]
```

### Key Controls:
- **Decoupled Delivery:** Email provider calls happen asynchronously via workers.
- **Exponential Backoff:** Retries are delayed (e.g., 1 min, 5 min, 15 min).
- **Idempotency:** Jobs are locked during processing (`PROCESSING` state) to prevent duplicate delivery by parallel worker loops.
