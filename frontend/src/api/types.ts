// Mirrors the backend Pydantic schemas (backend/schemas/*.py).
// Keep in sync with /api/v1/openapi.json.

export type UserRole = 'PATIENT' | 'DOCTOR' | 'ADMIN';

export type AppointmentStatus =
  | 'HELD'
  | 'CONFIRMED'
  | 'RESCHEDULED'
  | 'CANCELLED'
  | 'CONFLICTED'
  | 'COMPLETED';

export type AISummaryType = 'PRE_VISIT' | 'POST_VISIT';
export type AISummaryStatus = 'PENDING' | 'SUCCESS' | 'FAILED';

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  /** False until the user follows the link emailed to them. */
  email_verified: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type?: string;
  user: User;
}

export interface Doctor {
  id: string;
  user_id: string;
  email: string;
  full_name: string;
  specialization: string;
  slot_duration_minutes: number;
  /** IANA zone the doctor's working hours and leave dates are written in. */
  timezone: string;
  is_active: boolean;
  created_at: string;
}

export interface WorkingHours {
  id: string;
  doctor_id: string;
  day_of_week: number; // 0=Monday .. 6=Sunday
  start_time: string; // HH:MM:SS
  end_time: string;
  is_active: boolean;
}

export interface WorkingHoursInput {
  day_of_week: number;
  start_time: string;
  end_time: string;
  is_active: boolean;
}

export interface DoctorLeave {
  id: string;
  doctor_id: string;
  leave_date: string; // YYYY-MM-DD
  reason: string | null;
  created_at: string;
}

export interface SlotItem {
  start_time: string;
  end_time: string;
  is_available: boolean;
}

export interface SlotGenerationResponse {
  doctor_id: string;
  target_date: string;
  slot_duration_minutes: number;
  timezone: string;
  total_slots: number;
  available_slots: number;
  slots: SlotItem[];
}

export interface Hold {
  id: string;
  doctor_id: string;
  patient_id: string;
  start_time: string;
  end_time: string;
  expires_at: string;
  is_active: boolean;
  created_at: string;
}

export interface Appointment {
  id: string;
  patient_id: string;
  doctor_id: string;
  doctor_profile_id: string | null;
  start_time: string;
  end_time: string;
  status: AppointmentStatus;
  created_at: string;
  updated_at: string;
  patient_name: string | null;
  doctor_name: string | null;
  doctor_specialization: string | null;
  /** The doctor's IANA timezone: appointment times are shown in it. */
  doctor_timezone: string | null;
}

export interface PreVisitPayload {
  urgency: 'Low' | 'Medium' | 'High';
  chief_complaint: string;
  suggested_questions: string[];
}

export interface PostVisitPayload {
  summary: string;
  medication_schedule: string;
  follow_up_steps: string;
}

export interface AISummary {
  id: string;
  appointment_id: string;
  type: AISummaryType;
  status: AISummaryStatus;
  payload: PreVisitPayload | PostVisitPayload | null;
  error_message: string | null;
  created_at: string;
}

export interface SymptomReport {
  id: string;
  appointment_id: string;
  symptoms: string;
  created_at: string;
}

export interface MedicationItem {
  name: string;
  dosage: string;
  frequency: string;
  duration_days: number | null;
}

export interface MedicationResponse extends MedicationItem {
  id: string;
}

export interface Consultation {
  id: string;
  appointment_id: string;
  notes: string;
  created_at: string;
  medications: MedicationResponse[];
}

export interface MessageResponse {
  message: string;
}

export interface AuditLogEntry {
  id: string;
  occurred_at: string;
  actor_user_id: string | null;
  actor_role: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  patient_id: string | null;
  ip: string | null;
  detail: string | null;
}

export type StaffRole = 'DOCTOR' | 'ADMIN';
export type InvitationStatus = 'PENDING' | 'ACCEPTED' | 'REVOKED' | 'EXPIRED';

export interface Invitation {
  id: string;
  email: string;
  role: StaffRole;
  full_name: string | null;
  specialization: string | null;
  slot_duration_minutes: number | null;
  timezone: string | null;
  status: InvitationStatus;
  expires_at: string;
  created_at: string;
  invited_by: string | null;
}

export interface InvitationCreated {
  invitation: Invitation;
  /** Shown once: only a hash is stored, so it cannot be fetched again. */
  invite_link: string;
  email_queued: boolean;
}

/** What the signup page learns from an invitation link. */
export interface InvitationLookup {
  email: string;
  role: StaffRole;
  full_name: string | null;
  expires_at: string;
}

export interface AuditLogPage {
  items: AuditLogEntry[];
  total: number;
  limit: number;
  offset: number;
}
