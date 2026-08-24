Healthcare Appointment & Follow-up Manager
Objective:
• A clinic needs more than a basic booking form. Patients want to share symptoms in advance
and get reminders, doctors want a quick summary before each visit, and both sides expect timely
confirmations on email and their calendar. Build a healthcare appointment platform with separate
portals for patients, doctors, and an admin. It should let patients book appointments, give the
doctor an AI symptom summary before the visit, produce a patient-friendly summary after the
visit, and keep both sides informed through email and Google Calendar.
Scope of Work:
• Input: Patient symptoms, appointment details
• Output: Booked appointment, AI symptom summary, post-visit summary, email, calendar
events
• Admin creates and manages doctor profiles (specialisation, working hours, slot duration, leave
days)
• Patient can register, log in, search doctors by specialisation, and book a slot
• System must prevent double-booking and handle simultaneous booking attempts safely
• When a doctor is marked on leave for a date with existing bookings, affected patients must be
notified
• Patient fills a symptom form before confirming; LLM generates a pre-visit summary with
urgency level for the doctor
• Doctor submits post-visit notes and prescription; LLM generates a patient-friendly post-visit
summary
• System sends medication reminders based on prescription frequency
• Email notifications to both patient and doctor: booking confirmation, reminder, cancellation
• Google Calendar event created for both on booking; updated or deleted on reschedule or
cancellation
Technical Expectations:
• Backend API, Frontend, Database with role-based auth (patient / doctor / admin)
• LLM integration for pre-visit summary and post-visit summary; outputs stored in DB
• Background job for medication reminders and email retries
• Email service (SendGrid, Mailgun, Nodemailer, or similar)
• Google Calendar API with OAuth 2.0
• LLM failures must be handled gracefully, system should not break
LLM Usage Guidance:
• Pre-visit summary: "Analyse these symptoms and return: urgency level (Low / Medium /
High), chief complaint, and three suggested questions for the doctor. Symptoms: <symptoms>"
• Post-visit summary: "Convert these clinical notes into a patient-friendly summary with
medication schedule and follow-up steps: <notes>"
Deliverables:
1. Zip file with complete source code
2. README with setup guide, .env.example, API docs, DB schema, LLM prompts, and Google
Calendar setup steps
3. Hosted application URL (deploy on any free hosting service, Vercel, Render, Railway, etc.)
4. System design write-up (800 words max) covering double-booking prevention, doctor leave
conflict handling, slot hold mechanism, notification failure handling
Evaluation Focus:
• Problem-solving approach for slot conflicts, leave management, and notification reliability
• LLM prompt quality and failure handling
• Database schema design
• API design and code structure
• Email and Google Calendar integration
• Documentation