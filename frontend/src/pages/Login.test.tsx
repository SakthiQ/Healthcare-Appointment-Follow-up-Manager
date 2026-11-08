import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { makeAuth, makeUser } from '../test/helpers';
import Login from './Login';

vi.mock('../auth/AuthContext', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../auth/AuthContext')>()),
  useAuth: vi.fn(),
}));

function renderPage(auth = makeAuth({ user: null })) {
  vi.mocked(useAuth).mockReturnValue(auth);
  render(
    <MemoryRouter>
      <Login />
    </MemoryRouter>,
  );
  return auth;
}

async function signIn(email = 'pat@example.com', password = 'password123') {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Email'), email);
  await user.type(screen.getByLabelText('Password'), password);
  await user.click(screen.getByRole('button', { name: 'Sign in' }));
}

describe('Login', () => {
  it('links to password recovery and registration', () => {
    renderPage();
    expect(screen.getByRole('link', { name: 'Forgot your password?' })).toHaveAttribute('href', '/forgot-password');
    expect(screen.getByRole('link', { name: 'Create an account' })).toHaveAttribute('href', '/register');
  });

  it('validates before calling the API', async () => {
    const auth = renderPage();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Sign in' }));

    expect(screen.getByText('Email is required.')).toBeInTheDocument();
    expect(screen.getByText('Password is required.')).toBeInTheDocument();
    expect(auth.login).not.toHaveBeenCalled();
  });

  it('signs in with the trimmed email', async () => {
    const auth = makeAuth({ user: null, login: vi.fn().mockResolvedValue(makeUser()) });
    renderPage(auth);

    await signIn('  pat@example.com ');

    expect(auth.login).toHaveBeenCalledWith('pat@example.com', 'password123');
  });

  it('shows a lockout message from the server', async () => {
    renderPage(makeAuth({
      user: null,
      login: vi.fn().mockRejectedValue(new ApiError('Too many failed login attempts. Please try again later.', 429, 'TOO_MANY_REQUESTS')),
    }));

    await signIn();

    expect(await screen.findByText(/too many failed login attempts/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /new verification email/i })).not.toBeInTheDocument();
  });

  it('offers to resend the verification email when sign-in is refused for an unverified address', async () => {
    const spy = vi.spyOn(api, 'resendVerification').mockResolvedValue({
      message: 'If that address belongs to an account, we have sent it an email with a link.',
    });
    renderPage(makeAuth({
      user: null,
      login: vi.fn().mockRejectedValue(new ApiError('Please verify your email address before signing in.', 403, 'FORBIDDEN')),
    }));

    await signIn('  pat@example.com ');
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Send me a new verification email' }));

    expect(spy).toHaveBeenCalledWith('pat@example.com');
    expect(await screen.findByText(/we have sent it an email/i)).toBeInTheDocument();
  });
});
