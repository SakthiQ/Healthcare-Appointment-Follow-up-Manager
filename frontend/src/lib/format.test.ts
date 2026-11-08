import { describe, expect, it } from 'vitest';
import {
  bookableSlots,
  formatCountdown,
  formatDate,
  formatDateTime,
  formatTime,
  isValidTimeZone,
  timeZoneName,
} from './format';

// 03:30 UTC is 09:00 in India (UTC+5:30, no daylight saving).
const INSTANT = '2030-01-07T03:30:00Z';

describe('time formatting in the doctor\'s timezone', () => {
  it('shows the clinic-local time with a zone label', () => {
    expect(formatDateTime(INSTANT, 'Asia/Kolkata')).toBe('07 Jan 2030, 09:00 GMT+5:30');
    expect(formatTime(INSTANT, 'Asia/Kolkata')).toBe('09:00');
  });

  it('defaults to UTC, labelled, when there is no timezone', () => {
    expect(formatDateTime(INSTANT)).toBe('07 Jan 2030, 03:30 UTC');
    expect(formatDateTime(INSTANT, null)).toBe('07 Jan 2030, 03:30 UTC');
    expect(formatDateTime(INSTANT, '')).toBe('07 Jan 2030, 03:30 UTC');
  });

  it('falls back to UTC for an unknown zone instead of throwing', () => {
    expect(formatDateTime(INSTANT, 'Mars/Olympus')).toBe('07 Jan 2030, 03:30 UTC');
    expect(formatTime(INSTANT, 'Mars/Olympus')).toBe('03:30');
  });

  it('follows daylight saving: the same clock time maps to different offsets', () => {
    expect(formatDateTime('2030-01-07T16:00:00Z', 'America/New_York')).toBe('07 Jan 2030, 11:00 GMT-5');
    expect(formatDateTime('2030-07-01T16:00:00Z', 'America/New_York')).toBe('01 Jul 2030, 12:00 GMT-4');
  });

  it('moves the calendar date across midnight', () => {
    // 20:00 UTC on the 7th is already the 8th in India.
    expect(formatDate('2030-01-07T20:00:00Z', 'Asia/Kolkata')).toContain('08 Jan 2030');
    expect(formatDate('2030-01-07T20:00:00Z', 'UTC')).toContain('07 Jan 2030');
  });
});

describe('timezone helpers', () => {
  it('recognises real IANA names and rejects nonsense', () => {
    expect(isValidTimeZone('Asia/Kolkata')).toBe(true);
    expect(isValidTimeZone('UTC')).toBe(true);
    expect(isValidTimeZone('Mars/Olympus')).toBe(false);
    expect(isValidTimeZone('not a zone')).toBe(false);
  });

  it('names the zone for labels next to working hours', () => {
    expect(timeZoneName('Asia/Kolkata')).toBe('Asia/Kolkata (GMT+5:30)');
    expect(timeZoneName(undefined)).toBe('UTC (UTC)');
  });
});

describe('bookableSlots', () => {
  const slot = (start: string, is_available = true) => ({ start_time: start, is_available });

  it('keeps only free slots that have not started', () => {
    const now = new Date('2030-01-07T10:00:00Z').getTime();
    const slots = [
      slot('2030-01-07T09:00:00Z'),        // already started
      slot('2030-01-07T10:30:00Z'),        // bookable
      slot('2030-01-07T11:00:00Z', false), // taken
    ];
    expect(bookableSlots(slots, now).map((s) => s.start_time)).toEqual(['2030-01-07T10:30:00Z']);
  });
});

describe('formatCountdown', () => {
  it('pads seconds', () => {
    expect(formatCountdown(597)).toBe('9:57');
    expect(formatCountdown(60)).toBe('1:00');
    expect(formatCountdown(0)).toBe('0:00');
  });
});
