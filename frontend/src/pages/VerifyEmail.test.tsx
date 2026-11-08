import { render, screen, waitFor } from '@testing-library/react';
import { StrictMode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { makeAuth } from '../test/helpers';
import VerifyEmail from './VerifyEmail';

vi.mock('../auth/AuthContext', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../auth/AuthContext')>()),
  useAuth: vi.fn(),
}));

function renderPage(url: string, strict = false) {
  const page = (
    <MemoryRouter initialEntries={[url]}>
      <VerifyEmail />
    </MemoryRouter>
  );
  return render(strict ? <StrictMode>{page}</StrictMode> : page);
}

describe('VerifyEmail', () => {
  it('confirms the address and offers to continue to sign in', async () => {
    vi.mocked(useAuth).mockReturnValue(makeAuth({ user: null }));
    const spy = vi.spyOn(api, 'verifyEmail').mockResolvedValue(undefined);

    renderPage('/verify-email?token=abcdefghijklmnop');

    expect(await screen.findByText(/your email address is confirmed/i)).toBeInTheDocument();
    expect(spy).toHaveBeenCalledWith('abcdefghijklmnop');
    expect(screen.getByRole('link', { name: 'Go to sign in' })).toHaveAttribute('href', '/login');
  });

  it('spends the one-time link exactly once, even though StrictMode runs effects twice', async () => {
    vi.mocked(useAuth).mockReturnValue(makeAuth({ user: null }));
    const spy = vi.spyOn(api, 'verifyEmail').mockResolvedValue(undefined);

    renderPage('/verify-email?token=abcdefghijklmnop', true);

    expect(await screen.findByText(/your email address is confirmed/i)).toBeInTheDocument();
    expect(spy).toHaveBeenCalledTimes(1); // a second call would burn the token and show a false failure
  });

  it('refreshes a signed-in user so the "not verified" banner goes away', async () => {
    const auth = makeAuth();
    vi.mocked(useAuth).mockReturnValue(auth);
    vi.spyOn(api, 'verifyEmail').mockResolvedValue(undefined);

    renderPage('/verify-email?token=abcdefghijklmnop');

    await waitFor(() => expect(auth.refreshUser).toHaveBeenCalledTimes(1));
    expect(screen.getByRole('link', { name: 'Continue' })).toHaveAttribute('href', '/');
  });

  it('shows the server\'s message when the link is invalid or expired', async () => {
    vi.mocked(useAuth).mockReturnValue(makeAuth({ user: null }));
    vi.spyOn(api, 'verifyEmail').mockRejectedValue(
      new ApiError('This link is invalid or has expired. Please request a new one.', 422, 'VALIDATION_ERROR'),
    );

    renderPage('/verify-email?token=abcdefghijklmnop');

    expect(await screen.findByText(/invalid or has expired/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /sign in to request a new link/i })).toBeInTheDocument();
  });

  it('does not call the API for an incomplete link', () => {
    vi.mocked(useAuth).mockReturnValue(makeAuth());
    const spy = vi.spyOn(api, 'verifyEmail');

    renderPage('/verify-email');

    expect(screen.getByText(/this link is incomplete/i)).toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
  });
});
