import type {
  Appointment,
  AISummary,
  Consultation,
  Doctor,
  DoctorLeave,
  Hold,
  MedicationItem,
  SlotGenerationResponse,
  SymptomReport,
  TokenResponse,
  User,
  UserRole,
  WorkingHours,
  WorkingHoursInput,
} from './types';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '';
const API = `${BASE_URL}/api/v1`;

const TOKEN_KEY = 'healthcare.token';

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

/** Normalised API error — surfaces the backend's real message and error_code. */
export class ApiError extends Error {
  status: number;
  errorCode: string | null;

  constructor(message: string, status: number, errorCode: string | null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.errorCode = errorCode;
  }
}

/** Pull a human-readable message out of whatever shape the backend returned. */
function extractMessage(body: unknown, status: number): string {
  if (body && typeof body === 'object') {
    const b = body as Record<string, unknown>;
    if (typeof b.detail === 'string') return b.detail;
    // FastAPI request-validation errors: detail is an array of {loc,msg,type}
    if (Array.isArray(b.detail)) {
      const parts = b.detail
        .map((d) => {
          const item = d as Record<string, unknown>;
          const loc = Array.isArray(item.loc) ? item.loc.slice(1).join('.') : '';
          const msg = typeof item.msg === 'string' ? item.msg : 'invalid value';
          return loc ? `${loc}: ${msg}` : msg;
        })
        .filter(Boolean);
      if (parts.length) return parts.join('; ');
    }
  }
  if (status === 401) return 'Your session has expired. Please log in again.';
  if (status === 403) return 'You are not authorised to perform this action.';
  if (status === 404) return 'Not found.';
  return `Request failed (HTTP ${status}).`;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> | undefined),
  };
  if (options.body) headers['Content-Type'] = 'application/json';

  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(`${API}${path}`, { ...options, headers });
  } catch {
    throw new ApiError(
      'Could not reach the server. Check that the backend is running.',
      0,
      'NETWORK_ERROR',
    );
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }

  if (!response.ok) {
    const errorCode =
      body && typeof body === 'object' && typeof (body as Record<string, unknown>).error_code === 'string'
        ? ((body as Record<string, unknown>).error_code as string)
        : null;
    // An expired/invalid token should not leave the app in a half-authed state.
    if (response.status === 401) clearToken();
    throw new ApiError(extractMessage(body, response.status), response.status, errorCode);
  }

  return body as T;
}

const get = <T>(path: string) => request<T>(path);
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) });
const put = <T>(path: string, body: unknown) =>
  request<T>(path, { method: 'PUT', body: JSON.stringify(body) });
const patch = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'PATCH', body: body === undefined ? undefined : JSON.stringify(body) });
const del = <T>(path: string) => request<T>(path, { method: 'DELETE' });

export const api = {
  // --- Auth ---
  register: (data: {
    email: string;
    password: string;
    full_name: string;
    role?: UserRole;
    specialization?: string;
  }) => post<User>('/auth/register', data),

  login: (data: { email: string; password: string }) => post<TokenResponse>('/auth/login', data),

  me: () => get<User>('/auth/me'),

  // --- Doctors (public / patient) ---
  searchDoctors: (specialization?: string) =>
    get<Doctor[]>(`/doctors${specialization ? `?specialization=${encodeURIComponent(specialization)}` : ''}`),

  getDoctor: (doctorId: string) => get<Doctor>(`/doctors/${doctorId}`),

  getDoctorSchedule: (doctorId: string) => get<WorkingHours[]>(`/doctors/${doctorId}/schedule`),

  getDoctorLeaves: (doctorId: string) => get<DoctorLeave[]>(`/doctors/${doctorId}/leaves`),

  getSlots: (doctorId: string, date: string) =>
    get<SlotGenerationResponse>(`/doctors/${doctorId}/slots?date=${date}`),

  // --- Holds ---
  createHold: (data: { doctor_id: string; start_time: string; end_time: string }) =>
    post<Hold>('/slots/holds', data),

  getHold: (holdId: string) => get<Hold>(`/slots/holds/${holdId}`),

  releaseHold: (holdId: string) => post<void>(`/slots/holds/${holdId}/release`),

  // --- Appointments ---
  createAppointment: (data: {
    doctor_id: string;
    hold_id?: string;
    start_time?: string;
    end_time?: string;
    notes?: string;
  }) => post<Appointment>('/appointments', data),

  listAppointments: (params?: { status?: string; doctor_id?: string; patient_id?: string }) => {
    const q = new URLSearchParams();
    if (params?.status) q.set('status', params.status);
    if (params?.doctor_id) q.set('doctor_id', params.doctor_id);
    if (params?.patient_id) q.set('patient_id', params.patient_id);
    const qs = q.toString();
    return get<Appointment[]>(`/appointments${qs ? `?${qs}` : ''}`);
  },

  getAppointment: (id: string) => get<Appointment>(`/appointments/${id}`),

  rescheduleAppointment: (id: string, data: { new_start_time: string; new_end_time: string }) =>
    post<Appointment>(`/appointments/${id}/reschedule`, data),

  cancelAppointment: (id: string, reason?: string) =>
    post<Appointment>(`/appointments/${id}/cancel`, { cancellation_reason: reason ?? null }),

  // --- Symptoms & AI ---
  submitSymptomReport: (appointmentId: string, symptoms: string) =>
    post<SymptomReport>(`/appointments/${appointmentId}/symptom-report`, { symptoms }),

  generatePreVisitSummary: (appointmentId: string) =>
    post<AISummary>(`/appointments/${appointmentId}/ai/pre-visit-summary`),

  getPreVisitSummary: (appointmentId: string) =>
    get<AISummary>(`/appointments/${appointmentId}/ai/pre-visit-summary`),

  generatePostVisitSummary: (appointmentId: string) =>
    post<AISummary>(`/appointments/${appointmentId}/ai/post-visit-summary`),

  getPostVisitSummary: (appointmentId: string) =>
    get<AISummary>(`/appointments/${appointmentId}/ai/post-visit-summary`),

  // --- Consultation ---
  submitConsultation: (
    appointmentId: string,
    data: { notes: string; prescription_instructions?: string; medications: MedicationItem[] },
  ) => post<Consultation>(`/appointments/${appointmentId}/consultation`, data),

  getConsultation: (appointmentId: string) => get<Consultation>(`/appointments/${appointmentId}/consultation`),

  // --- Admin ---
  createDoctor: (data: {
    email: string;
    password: string;
    full_name: string;
    specialization: string;
    slot_duration_minutes: number;
  }) => post<Doctor>('/admin/doctors', data),

  updateDoctor: (
    doctorId: string,
    data: { specialization?: string; slot_duration_minutes?: number; is_active?: boolean },
  ) => put<Doctor>(`/admin/doctors/${doctorId}`, data),

  setDoctorStatus: (doctorId: string, isActive: boolean) =>
    patch<Doctor>(`/admin/doctors/${doctorId}/status?is_active=${isActive}`),

  configureWorkingHours: (doctorId: string, workingHours: WorkingHoursInput[]) =>
    post<WorkingHours[]>(`/admin/doctors/${doctorId}/schedule`, { working_hours: workingHours }),

  createLeave: (doctorId: string, data: { leave_date: string; reason?: string }) =>
    post<DoctorLeave>(`/admin/doctors/${doctorId}/leaves`, data),

  deleteLeave: (doctorId: string, leaveId: string) =>
    del<void>(`/admin/doctors/${doctorId}/leaves/${leaveId}`),
};
