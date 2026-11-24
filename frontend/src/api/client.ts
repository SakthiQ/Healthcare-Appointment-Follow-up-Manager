import type {
  AdminStats,
  Appointment,
  AISummary,
  AuditLogPage,
  MessageResponse,
  Consultation,
  Doctor,
  DoctorLeave,
  FailedJob,
  FailedJobKind,
  FailedJobPage,
  Hold,
  Invitation,
  InvitationCreated,
  InvitationLookup,
  MedicationItem,
  StaffRole,
  SlotGenerationResponse,
  SymptomReport,
  TokenResponse,
  User,
  UserRole,
  WorkingHours,
  WorkingHoursInput,
  HistoryItem,
} from './types';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '';
const API = `${BASE_URL}/api/v1`;

const TOKEN_KEY = 'healthcare.token';

// Cookie mode (build with VITE_AUTH_COOKIES=true, and set AUTH_COOKIE_MODE=True on the
// API): the session lives in an httpOnly cookie that scripts cannot read, so there is
// no token to steal from the page. Needs the app and the API on the same site. All that
// is kept in localStorage is a harmless "signed in" marker.
const COOKIE_MODE = import.meta.env.VITE_AUTH_COOKIES === 'true';
const COOKIE_SESSION_MARKER = 'cookie-session';

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, COOKIE_MODE ? COOKIE_SESSION_MARKER : token);
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

// Lets the auth layer drop the signed-in user when the backend rejects the
// token, so an expired session sends the user back to login.
let unauthorizedHandler: (() => void) | null = null;
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
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

/** How many times a request is sent again after the server answers "busy". */
export const BUSY_RETRIES = 2;
/** Longest wait between busy retries, whatever Retry-After says. */
const MAX_BUSY_WAIT_MS = 5_000;
/** Up to this much random extra wait, so clients turned away together don't all come back at once. */
const BUSY_JITTER_MS = 500;

/** How long to wait before retrying a busy response: Retry-After seconds (default 1), capped, plus jitter. */
function busyDelayMs(headers: Headers): number {
  const seconds = Number(headers.get('Retry-After'));
  const base = Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : 1000;
  return Math.min(base, MAX_BUSY_WAIT_MS) + Math.random() * BUSY_JITTER_MS;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Runs a request and returns the parsed body together with the response headers.
 *
 *  When the API is at capacity it answers 503 with error_code SERVER_BUSY before the
 *  request reaches any endpoint, so nothing was done and it is safe to send again, for
 *  POSTs as well as GETs. Those responses are retried up to BUSY_RETRIES times, so a short
 *  spike shows up as a slower page instead of an error. Any other 503 is not retried. */
async function send<T>(
  path: string,
  options: RequestInit = {},
  as: 'json' | 'text' = 'json',
): Promise<{ body: T; headers: Headers }> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await sendOnce<T>(path, options, as);
    } catch (error) {
      const busy = error instanceof BusyError;
      if (!busy) throw error;
      if (attempt >= BUSY_RETRIES || options.signal?.aborted) throw error.apiError;
      await sleep(busyDelayMs(error.headers));
    }
  }
}

/** Internal: a SERVER_BUSY answer, carrying the error to show if the retries run out. */
class BusyError extends Error {
  constructor(
    readonly apiError: ApiError,
    readonly headers: Headers,
  ) {
    super(apiError.message);
  }
}

async function sendOnce<T>(
  path: string,
  options: RequestInit,
  as: 'json' | 'text' = 'json',
): Promise<{ body: T; headers: Headers }> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> | undefined),
  };
  if (options.body) headers['Content-Type'] = 'application/json';

  const token = getToken();
  if (COOKIE_MODE) {
    // The browser attaches the cookie. The custom header is the CSRF defence: a
    // cross-site page cannot add it without a CORS preflight that the API refuses.
    headers['X-CSRF-Protection'] = '1';
  } else if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(`${API}${path}`, {
      ...options,
      headers,
      credentials: COOKIE_MODE ? 'include' : 'same-origin',
    });
  } catch {
    throw new ApiError(
      'Could not reach the server. Check that the backend is running.',
      0,
      'NETWORK_ERROR',
    );
  }

  if (response.status === 204) return { body: undefined as T, headers: response.headers };

  const text = await response.text();
  // A successful non-JSON download (such as an .ics file) is returned as text; errors stay JSON.
  if (response.ok && as === 'text') return { body: text as T, headers: response.headers };
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
    // Only act if this request's token is still the current one — a stale
    // request finishing after a fresh login must not end the new session.
    if (response.status === 401 && token && getToken() === token) {
      clearToken();
      unauthorizedHandler?.();
    }
    const apiError = new ApiError(extractMessage(body, response.status), response.status, errorCode);
    if (response.status === 503 && errorCode === 'SERVER_BUSY') throw new BusyError(apiError, response.headers);
    throw apiError;
  }

  return { body: body as T, headers: response.headers };
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  return (await send<T>(path, options)).body;
}

export interface AppointmentListParams {
  status?: string;
  doctor_id?: string;
  patient_id?: string;
  /** Only appointments starting at or after this ISO timestamp. */
  from?: string;
}

/** One page of appointments and how many match in total (the API's X-Total-Count header). */
/** Filters for the admin CSV export (GET /admin/appointments/export.csv). */
export interface AppointmentExportFilters {
  status?: string;
  doctor_id?: string;
  /** ISO timestamps: appointments starting at or after `from` and before `until`. */
  from?: string;
  until?: string;
}

export interface AppointmentPage {
  items: Appointment[];
  total: number;
}

function appointmentQuery(params?: AppointmentListParams & { limit?: number; offset?: number }): string {
  const q = new URLSearchParams();
  if (params?.status) q.set('status', params.status);
  if (params?.doctor_id) q.set('doctor_id', params.doctor_id);
  if (params?.patient_id) q.set('patient_id', params.patient_id);
  if (params?.from) q.set('from', params.from);
  if (params?.limit !== undefined) q.set('limit', String(params.limit));
  if (params?.offset) q.set('offset', String(params.offset));
  const qs = q.toString();
  return `/appointments${qs ? `?${qs}` : ''}`;
}

/**
 * For "fetch it if it exists" reads: a 404 means there is nothing yet and
 * resolves to null; every other failure (network, auth, server) still throws.
 */
export function nullIfNotFound<T>(promise: Promise<T>): Promise<T | null> {
  return promise.catch((err) => {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  });
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
    /** From an invitation link. The invitation decides the role; `role` is then ignored. */
    invite_token?: string;
  }) => post<User>('/auth/register', data),

  /** What the signup page shows for an invitation link. */
  lookupInvitation: (token: string) => post<InvitationLookup>('/auth/invitations/lookup', { token }),

  login: (data: { email: string; password: string }) => post<TokenResponse>('/auth/login', data),

  me: () => get<User>('/auth/me'),

  /** Invalidates every token issued to this user, not just this browser's copy. */
  logout: () => post<void>('/auth/logout'),

  /** Signs every OTHER session out; the response carries a fresh token for this one. */
  changePassword: (data: { current_password: string; new_password: string }) =>
    post<TokenResponse>('/auth/change-password', data),

  /** Always succeeds the same way, whether or not the address has an account. */
  forgotPassword: (email: string) => post<MessageResponse>('/auth/forgot-password', { email }),

  resetPassword: (token: string, new_password: string) =>
    post<void>('/auth/reset-password', { token, new_password }),

  verifyEmail: (token: string) => post<void>('/auth/verify-email', { token }),

  resendVerification: (email: string) =>
    post<MessageResponse>('/auth/resend-verification', { email }),

  // --- Doctors (public / patient) ---
  searchDoctors: (filters: { specialization?: string; name?: string } = {}) => {
    const params = new URLSearchParams();
    if (filters.specialization?.trim()) params.set('specialization', filters.specialization.trim());
    if (filters.name?.trim()) params.set('name', filters.name.trim());
    const query = params.toString();
    return get<Doctor[]>(`/doctors${query ? `?${query}` : ''}`);
  },

  getDoctor: (doctorId: string) => get<Doctor>(`/doctors/${doctorId}`),

  /** The signed-in doctor's own profile (doctors only). */
  getMyDoctorProfile: () => get<Doctor>('/doctors/me'),

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

  listAppointments: (params?: AppointmentListParams) => get<Appointment[]>(appointmentQuery(params)),

  /** A page of appointments, earliest first, with the total number that match. */
  listAppointmentsPage: async (
    params: AppointmentListParams & { limit: number; offset: number },
  ): Promise<AppointmentPage> => {
    const { body, headers } = await send<Appointment[]>(appointmentQuery(params));
    const total = Number(headers.get('X-Total-Count'));
    return { items: body, total: Number.isFinite(total) && total >= body.length ? total : body.length };
  },

  /** The signed-in patient's completed visits, newest first (patients only; audited). */
  getMyHistory: async ({ limit, offset }: { limit: number; offset: number }): Promise<{ items: HistoryItem[]; total: number }> => {
    const { body, headers } = await send<HistoryItem[]>(`/patients/me/history?limit=${limit}&offset=${offset}`);
    const total = Number(headers.get('X-Total-Count'));
    return { items: body, total: Number.isFinite(total) && total >= body.length ? total : body.length };
  },

  getAppointment: (id: string) => get<Appointment>(`/appointments/${id}`),

  rescheduleAppointment: (id: string, data: { new_start_time: string; new_end_time: string }) =>
    post<Appointment>(`/appointments/${id}/reschedule`, data),

  /** Appointments as CSV text for a spreadsheet (admin only; audited, capped at 10,000 rows). */
  exportAppointmentsCsv: async (filters: AppointmentExportFilters = {}): Promise<string> => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
    const query = params.toString();
    return (await send<string>(`/admin/appointments/export.csv${query ? `?${query}` : ''}`, {}, 'text')).body;
  },

  /** The appointment as an iCalendar (.ics) file, for Apple Calendar, Outlook and others. */
  getAppointmentCalendar: async (id: string): Promise<string> =>
    (await send<string>(`/appointments/${id}/calendar.ics`, {}, 'text')).body,

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
    timezone: string;
  }) => post<Doctor>('/admin/doctors', data),

  updateDoctor: (
    doctorId: string,
    data: { specialization?: string; slot_duration_minutes?: number; is_active?: boolean; timezone?: string },
  ) => put<Doctor>(`/admin/doctors/${doctorId}`, data),

  setDoctorStatus: (doctorId: string, isActive: boolean) =>
    patch<Doctor>(`/admin/doctors/${doctorId}/status?is_active=${isActive}`),

  configureWorkingHours: (doctorId: string, workingHours: WorkingHoursInput[]) =>
    post<WorkingHours[]>(`/admin/doctors/${doctorId}/schedule`, { working_hours: workingHours }),

  listAuditLogs: (params: {
    action?: string;
    actor_id?: string;
    patient_id?: string;
    limit?: number;
    offset?: number;
  }) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== '') q.set(key, String(value));
    });
    const qs = q.toString();
    return get<AuditLogPage>(`/admin/audit-logs${qs ? `?${qs}` : ''}`);
  },

  /** A page of failed email or calendar jobs, newest first, with the total (X-Total-Count). */
  listFailedJobs: async (params: { kind: FailedJobKind; limit: number; offset: number }): Promise<FailedJobPage> => {
    const q = new URLSearchParams({
      kind: params.kind,
      limit: String(params.limit),
      offset: String(params.offset),
    });
    const { body, headers } = await send<FailedJob[]>(`/admin/failed-jobs?${q.toString()}`);
    const total = Number(headers.get('X-Total-Count'));
    return { items: body, total: Number.isFinite(total) && total >= body.length ? total : body.length };
  },

  /** Put a failed job back in the queue. 409 when it can no longer be retried. */
  retryFailedJob: (job: Pick<FailedJob, 'id' | 'kind'>) =>
    post<FailedJob>(
      job.kind === 'calendar'
        ? `/admin/calendar-events/${encodeURIComponent(job.id)}/retry`
        : `/admin/notifications/${encodeURIComponent(job.id)}/retry`,
    ),

  createInvitation: (data: {
    email: string;
    role: StaffRole;
    full_name?: string;
    specialization?: string;
    slot_duration_minutes?: number;
    timezone?: string;
  }) => post<InvitationCreated>('/admin/invitations', data),

  listInvitations: () => get<Invitation[]>('/admin/invitations'),

  getAdminStats: () => get<AdminStats>('/admin/stats'),

  revokeInvitation: (invitationId: string) => del<void>(`/admin/invitations/${invitationId}`),

  createLeave: (doctorId: string, data: { leave_date: string; reason?: string }) =>
    post<DoctorLeave>(`/admin/doctors/${doctorId}/leaves`, data),

  deleteLeave: (doctorId: string, leaveId: string) =>
    del<void>(`/admin/doctors/${doctorId}/leaves/${leaveId}`),
};
