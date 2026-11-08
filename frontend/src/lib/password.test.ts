import { describe, expect, it } from 'vitest';
import { MAX_PASSWORD_BYTES, MIN_PASSWORD_LENGTH, validateNewPassword } from './password';

describe('validateNewPassword', () => {
  it('accepts a normal password', () => {
    expect(validateNewPassword('correct horse')).toBeUndefined();
  });

  it('requires something', () => {
    expect(validateNewPassword('')).toMatch(/required/i);
  });

  it('enforces the minimum length', () => {
    expect(validateNewPassword('a'.repeat(MIN_PASSWORD_LENGTH - 1))).toMatch(/at least/i);
    expect(validateNewPassword('a'.repeat(MIN_PASSWORD_LENGTH))).toBeUndefined();
  });

  it('counts bytes, not characters, against the 72-byte bcrypt limit', () => {
    expect(validateNewPassword('a'.repeat(MAX_PASSWORD_BYTES))).toBeUndefined();
    expect(validateNewPassword('a'.repeat(MAX_PASSWORD_BYTES + 1))).toMatch(/at most/i);
    // 19 emoji are only 19 characters but 76 bytes, which the API would refuse.
    expect(validateNewPassword('😀'.repeat(19))).toMatch(/at most/i);
    expect(validateNewPassword('😀'.repeat(18))).toBeUndefined();
  });
});
