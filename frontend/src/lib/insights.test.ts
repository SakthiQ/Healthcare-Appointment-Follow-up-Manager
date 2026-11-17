import { describe, expect, it } from 'vitest';
import { scrubUrl } from './insights';

const SITE = 'https://clinic.example.com';

describe('scrubUrl', () => {
  it('drops query strings, which can hold single-use tokens', () => {
    expect(scrubUrl(`${SITE}/register?invite=Zk3x9QwErTy12345abcd`)).toBe(`${SITE}/register`);
    expect(scrubUrl(`${SITE}/reset-password?token=abc123def456ghi789`)).toBe(`${SITE}/reset-password`);
    expect(scrubUrl(`${SITE}/verify-email?token=abc123def456ghi789#top`)).toBe(`${SITE}/verify-email`);
  });

  it('replaces record IDs in the path', () => {
    expect(scrubUrl(`${SITE}/patient/appointments/3f2c8a7e-1b2d-4c5e-9f00-1234567890ab`)).toBe(
      `${SITE}/patient/appointments/:id`,
    );
    expect(scrubUrl(`${SITE}/admin/doctors/a1b2c3d4e5f6a7b8c9d0`)).toBe(`${SITE}/admin/doctors/:id`);
  });

  it('keeps ordinary page paths as they are', () => {
    expect(scrubUrl(`${SITE}/patient/doctors`)).toBe(`${SITE}/patient/doctors`);
    expect(scrubUrl(`${SITE}/forgot-password`)).toBe(`${SITE}/forgot-password`);
    expect(scrubUrl(`${SITE}/`)).toBe(`${SITE}/`);
  });

  it('returns an empty string for something that is not a URL', () => {
    expect(scrubUrl('not a url')).toBe('');
  });
});
