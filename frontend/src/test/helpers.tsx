import { vi } from 'vitest';
import type { useAuth } from '../auth/AuthContext';
import type { User } from '../api/types';

export type AuthState = ReturnType<typeof useAuth>;

export function makeUser(overrides: Partial<User> = {}): User {
  return {
    id: 'user-1',
    email: 'pat@example.com',
    full_name: 'Pat Patient',
    role: 'PATIENT',
    is_active: true,
    email_verified: true,
    created_at: '2030-01-01T00:00:00Z',
    ...overrides,
  };
}

/** A complete fake of what useAuth() returns, with every action a spy. */
export function makeAuth(overrides: Partial<AuthState> = {}): AuthState {
  return {
    user: makeUser(),
    loading: false,
    login: vi.fn(),
    logout: vi.fn(),
    changePassword: vi.fn().mockResolvedValue(undefined),
    refreshUser: vi.fn().mockResolvedValue(undefined),
    hasRole: vi.fn().mockReturnValue(true),
    ...overrides,
  };
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
