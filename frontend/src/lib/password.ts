/** Mirrors the API's rules so mistakes are caught before a request is made. */
export const MIN_PASSWORD_LENGTH = 6;
// bcrypt, which the API uses, only reads the first 72 BYTES, so the API refuses longer ones.
export const MAX_PASSWORD_BYTES = 72;

/** An error message for a new password, or undefined if it is acceptable. */
export function validateNewPassword(password: string): string | undefined {
  if (!password) return 'Password is required.';
  if (password.length < MIN_PASSWORD_LENGTH)
    return `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
  if (new TextEncoder().encode(password).length > MAX_PASSWORD_BYTES)
    return `Use at most ${MAX_PASSWORD_BYTES} bytes (long passwords with emoji or accents count extra).`;
  return undefined;
}
