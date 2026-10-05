# Requirement Map

This document maps every requirement from `AGENT_SPEC.md` to its planned backend/frontend implementation modules, API endpoints, and verification tests.

| Requirement ID | Requirement Description | Planned Module | Planned API / Functionality | Planned Verification Test |
|----------------|-------------------------|----------------|-----------------------------|---------------------------|
| **REQ-01** | Role-Based Authentication (Patient, Doctor, Admin) | `auth`, `user` | `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me` | `tests/test_auth.py::test_rbac_permissions` |
| **REQ-02** | Doctor Profile & Specialization Management | `doctor`, `admin` | `POST /api/admin/doctors`, `PUT /api/admin/doctors/{id}` | `tests/test_doctors.py::test_admin_doctor_crud` |
| **REQ-03** | Working Hours & Slot Duration Config | `doctor`, `schedule` | `POST /api/admin/doctors/{id}/schedule` | `tests/test_doctors.py::test_working_hours_config` |
| **REQ-04** | Doctor Leave Management | `doctor`, `leave` | `POST /api/admin/doctors/{id}/leave` | `tests/test_doctors.py::test_doctor_leave` |
| **REQ-05** | Doctor Search by Specialization | `doctor` | `GET /api/doctors?specialization=...` | `tests/test_doctors.py::test_search_by_specialization` |
| **REQ-06** | Slot Generation Engine | `slot` | `GET /api/doctors/{id}/slots?date=...` | `tests/test_slots.py::test_slot_generation` |
| **REQ-07** | Slot Hold Mechanism | `hold` | `POST /api/appointments/hold` | `tests/test_slots.py::test_slot_hold_and_expiry` |
| **REQ-08** | Appointment Booking | `appointment` | `POST /api/appointments/confirm` | `tests/test_appointments.py::test_book_appointment` |
| **REQ-09** | Double-Booking & Concurrency Control | `appointment` | DB Exclusion Index + `SELECT FOR UPDATE` | `tests/test_concurrency.py::test_100_simultaneous_bookings` |
| **REQ-10** | Doctor Leave Conflict Resolution | `leave`, `appointment` | `POST /api/admin/doctors/{id}/leave` | `tests/test_appointments.py::test_leave_conflict_handling` |
| **REQ-11** | Pre-Visit Symptom Form & AI Summary | `ai`, `appointment` | `POST /api/appointments/{id}/symptoms` | `tests/test_ai.py::test_pre_visit_summary_generation` |
| **REQ-12** | Post-Visit Doctor Notes & AI Summary | `ai`, `consultation` | `POST /api/consultations/{id}/notes` | `tests/test_ai.py::test_post_visit_summary_generation` |
| **REQ-13** | Prescription & Medication Reminders | `consultation`, `reminder` | `POST /api/consultations/{id}/prescription` | `tests/test_notifications.py::test_medication_reminder_jobs` |
| **REQ-14** | Email Notifications (Booking, Reminder, Cancellation) | `notification`, `providers` | `NotificationWorker` + `EmailProvider` | `tests/test_notifications.py::test_email_notifications_and_retries` |
| **REQ-15** | Google Calendar Integration | `calendar`, `providers` | `CalendarService` + `GoogleCalendarProvider` | `tests/test_calendar.py::test_calendar_sync_and_retry` |
| **REQ-16** | Background Job Processing & Retries | `workers` | `NotificationWorker`, `HoldExpiryWorker` | `tests/test_notifications.py::test_worker_job_processing` |
| **REQ-17** | Graceful LLM Failure | `ai`, `providers` | Fallback error state in `AISummary` | `tests/test_ai.py::test_llm_failure_graceful_handling` |
| **REQ-18** | DEMO_MODE Configuration | `config`, `providers` | `MockAIProvider`, `MockEmailProvider`, `MockCalendarProvider` | `tests/test_config.py::test_provider_factories_respect_per_integration_switches`, `tests/test_health.py::test_health_reports_each_integrations_effective_provider` |
