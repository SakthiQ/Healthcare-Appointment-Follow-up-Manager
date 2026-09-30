import type { AppointmentStatus } from '../api/types';

// The backend generates and stores all slot/appointment times in UTC.
// We render them in UTC too, explicitly labelled, so what the user sees always
// matches what the backend holds — no silent local-timezone shifting.
const DATE_TIME: Intl.DateTimeFormatOptions = {
  timeZone: 'UTC',
  year: 'numeric',
  month: 'short',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
};

const TIME_ONLY: Intl.DateTimeFormatOptions = {
  timeZone: 'UTC',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
};

const DATE_ONLY: Intl.DateTimeFormatOptions = {
  timeZone: 'UTC',
  weekday: 'short',
  year: 'numeric',
  month: 'short',
  day: '2-digit',
};

/**
 * Parse a timestamp coming from the API.
 *
 * The backend stores everything in UTC, but values read back out of the
 * database serialise WITHOUT a timezone designator (e.g. "2026-08-31T10:00:00"),
 * while values built in memory carry one ("...+00:00"). JavaScript interprets
 * the former as *local* time, which silently shifts every DB-sourced timestamp
 * by the viewer's UTC offset — making holds look expired and appointments look
 * hours off. Treat a missing designator as UTC, which is what it actually is.
 */
export function parseServerDate(iso: string): Date {
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso);
  return new Date(hasZone ? iso : `${iso}Z`);
}

export function formatDateTime(iso: string): string {
  return `${parseServerDate(iso).toLocaleString('en-GB', DATE_TIME)} UTC`;
}

export function formatTime(iso: string): string {
  return parseServerDate(iso).toLocaleString('en-GB', TIME_ONLY);
}

export function formatDate(iso: string): string {
  return parseServerDate(iso).toLocaleString('en-GB', DATE_ONLY);
}

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
  return slots.filter((s) => s.is_available && parseServerDate(s.start_time).getTime() > now);
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
  return Math.max(0, Math.floor((parseServerDate(iso).getTime() - Date.now()) / 1000));
}

export function formatCountdown(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}
