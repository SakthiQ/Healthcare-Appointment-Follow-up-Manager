import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { api } from './api/client';
import App from './App';
import { useAuth } from './auth/AuthContext';
import { makeAuth, makeUser } from './test/helpers';

vi.mock('@vercel/analytics/react', () => ({ Analytics: () => null }));
vi.mock('./auth/AuthContext', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./auth/AuthContext')>()),
  useAuth: vi.fn(),
}));

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <App />
    </MemoryRouter>,
  );
}

describe('routes that need no account', () => {
  it.each([
    ['/forgot-password', 'Forgot your password?'],
    ['/reset-password?token=abcdefghijklmnop', 'Choose a new password'],
    ['/login', 'Sign in'],
  ])('%s is reachable while signed out', (url, heading) => {
    vi.mocked(useAuth).mockReturnValue(makeAuth({ user: null }));
    renderAt(url);
    expect(screen.getByRole('heading', { name: heading })).toBeInTheDocument();
  });

  it('/verify-email is reachable while signed out and verifies the address', async () => {
    vi.mocked(useAuth).mockReturnValue(makeAuth({ user: null }));
    const spy = vi.spyOn(api, 'verifyEmail').mockResolvedValue(undefined);

    renderAt('/verify-email?token=abcdefghijklmnop');

    expect(await screen.findByText(/your email address is confirmed/i)).toBeInTheDocument();
    expect(spy).toHaveBeenCalledWith('abcdefghijklmnop');
  });
});

describe('routes that need a session', () => {
  it.each(['/account', '/admin/audit'])('%s sends a signed-out visitor to sign in', (url) => {
    vi.mocked(useAuth).mockReturnValue(makeAuth({ user: null }));
    renderAt(url);
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
  });

  it('/account is available to every role', () => {
    for (const role of ['PATIENT', 'DOCTOR', 'ADMIN'] as const) {
      vi.mocked(useAuth).mockReturnValue(makeAuth({ user: makeUser({ role }) }));
      const { unmount } = renderAt('/account');
      expect(screen.getByRole('heading', { name: 'Your account' })).toBeInTheDocument();
      unmount();
    }
  });

  it('the audit log is for admins only: a doctor is sent to their own portal', async () => {
    vi.mocked(useAuth).mockReturnValue(makeAuth({ user: makeUser({ role: 'DOCTOR' }) }));
    vi.spyOn(api, 'listAppointments').mockResolvedValue([]);

    renderAt('/admin/audit');

    expect(screen.queryByRole('heading', { name: 'Audit log' })).not.toBeInTheDocument();
    expect(await screen.findByText(/welcome/i)).toBeInTheDocument(); // the doctor dashboard
  });

  it('an admin reaches the audit log', async () => {
    vi.mocked(useAuth).mockReturnValue(makeAuth({ user: makeUser({ role: 'ADMIN' }) }));
    vi.spyOn(api, 'listAuditLogs').mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 });

    renderAt('/admin/audit');

    expect(await screen.findByRole('heading', { name: 'Audit log' })).toBeInTheDocument();
  });
});
