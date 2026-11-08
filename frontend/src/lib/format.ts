import type { AppointmentStatus } from '../api/types';

// The backend stores every appointment time as a UTC instant. Working hours and
// leave dates are written in the DOCTOR's timezone, so times are shown in that
// zone, labelled, wherever they appear: a patient in another zone sees the
// clinic's local time, which is the time they actually have to turn up.
// `tz` is an IANA name; blank or unknown falls back to UTC.

/** True if `tz` is an IANA timezone name this browser knows. */
export function isValidTimeZone(tz: string): boolean {
  try {
    new Intl.DateTimeFormat('en-GB', { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}

function safeZone(tz?: string | null): string {
  if (!tz) return 'UTC';
  try {
    new Intl.DateTimeFormat('en-GB', { timeZone: tz });
    return tz;
  } catch {
    return 'UTC';
  }
}

function zoneLabel(date: Date, tz: string): string {
  const part = new Intl.DateTimeFormat('en-GB', { timeZone: tz, timeZoneName: 'short' })
    .formatToParts(date)
    .find((p) => p.type === 'timeZoneName');
  return part?.value ?? tz;
}

export function formatDateTime(iso: string, tz?: string | null): string {
  const zone = safeZone(tz);
  const date = new Date(iso);
  const text = date.toLocaleString('en-GB', {
    timeZone: zone,
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
  return `${text} ${zoneLabel(date, zone)}`;
}

export function formatTime(iso: string, tz?: string | null): string {
  return new Date(iso).toLocaleString('en-GB', {
    timeZone: safeZone(tz),
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

export function formatDate(iso: string, tz?: string | null): string {
  return new Date(iso).toLocaleString('en-GB', {
    timeZone: safeZone(tz),
    weekday: 'short',
    year: 'numeric',
    month: 'short',
    day: '2-digit',
  });
}

/** Short zone name such as "UTC" or "GMT+5:30", for labels next to working hours. */
export function timeZoneName(tz?: string | null): string {
  const zone = safeZone(tz);
  return `${zone} (${zoneLabel(new Date(), zone)})`;
}

/** Suggestions for the doctor-timezone field; any IANA name is accepted. */
export const COMMON_TIMEZONES = [
  'UTC',
  'Asia/Kolkata',
  'Asia/Dubai',
  'Asia/Singapore',
  'Asia/Tokyo',
  'Australia/Sydney',
  'Europe/London',
  'Europe/Paris',
  'Europe/Berlin',
  'Africa/Johannesburg',
  'America/Sao_Paulo',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
];

/** YYYY-MM-DD in the viewer's own calendar, for <input type="date"> and the slots endpoint. */
export function toDateInputValue(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

export function todayInputValue(): string {
  return toDateInputValue(new Date());
}

/** Slots the patient can actually pick: free and not already started as of `now` (ms). */
export function bookableSlots<T extends { is_available: boolean; start_time: string }>(
  slots: T[],
  now: number,
): T[] {
  return slots.filter((s) => s.is_available && new Date(s.start_time).getTime() > now);
}

export const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

export function statusTone(status: AppointmentStatus): string {
  switch (status) {
    case 'CONFIRMED':
    case 'COMPLETED':
      return 'ok';
    case 'RESCHEDULED':
      return 'info';
    case 'HELD':
      return 'warn';
    case 'CONFLICTED':
      return 'danger';
    case 'CANCELLED':
      return 'muted';
    default:
      return 'muted';
  }
}

export function urgencyTone(urgency: string): string {
  if (urgency === 'High') return 'danger';
  if (urgency === 'Medium') return 'warn';
  return 'ok';
}

/** Seconds remaining until an ISO timestamp, floored at 0. */
export function secondsUntil(iso: string): number {
  return Math.max(0, Math.floor((new Date(iso).getTime() - Date.now()) / 1000));
}

export function formatCountdown(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}
