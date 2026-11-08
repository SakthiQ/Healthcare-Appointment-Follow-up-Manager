import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { makeAuth, makeUser } from '../test/helpers';
import Register from './Register';

vi.mock('../auth/AuthContext', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../auth/AuthContext')>()),
  useAuth: vi.fn(),
}));

const TOKEN = 'invite-token-abcdefghijklmnop';

function renderPage(url = '/register', auth = makeAuth({ user: null, login: vi.fn().mockResolvedValue(makeUser()) })) {
  vi.mocked(useAuth).mockReturnValue(auth);
  render(
    <MemoryRouter initialEntries={[url]}>
      <Register />
    </MemoryRouter>,
  );
  return auth;
}

async function fillPasswords(password = 'password123') {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Password'), password);
  await user.type(screen.getByLabelText('Confirm password'), password);
  await user.click(screen.getByRole('button', { name: 'Create account' }));
}

describe('Register', () => {
  it('is patient self-registration without an invitation, and never looks one up', async () => {
    const lookup = vi.spyOn(api, 'lookupInvitation');
    const register = vi.spyOn(api, 'register').mockResolvedValue(makeUser());
    renderPage();
    const user = userEvent.setup();

    expect(screen.getByText(/register as a patient/i)).toBeInTheDocument();
    await user.type(screen.getByLabelText('Full name'), 'Pat Patient');
    await user.type(screen.getByLabelText('Email'), 'pat@example.com');
    await fillPasswords();

    expect(lookup).not.toHaveBeenCalled();
    expect(register).toHaveBeenCalledWith({
      email: 'pat@example.com',
      password: 'password123',
      full_name: 'Pat Patient',
      role: 'PATIENT',
    });
  });

  it('shows what an invitation is for and locks the email to the invited address', async () => {
    vi.spyOn(api, 'lookupInvitation').mockResolvedValue({
      email: 'dr.new@example.com',
      role: 'DOCTOR',
      full_name: 'Dr New',
      expires_at: '2030-01-08T00:00:00Z',
    });
    renderPage(`/register?invite=${TOKEN}`);

    expect(await screen.findByText(/invited to join as/i)).toHaveTextContent('a doctor');
    expect(screen.getByLabelText('Email')).toHaveValue('dr.new@example.com');
    expect(screen.getByLabelText('Email')).toHaveAttribute('readonly');
    expect(screen.getByLabelText('Full name')).toHaveValue('Dr New');
  });

  it('sends the invitation token with the signup, then signs in', async () => {
    vi.spyOn(api, 'lookupInvitation').mockResolvedValue({
      email: 'boss@example.com',
      role: 'ADMIN',
      full_name: null,
      expires_at: '2030-01-08T00:00:00Z',
    });
    const register = vi.spyOn(api, 'register').mockResolvedValue(makeUser({ role: 'ADMIN' }));
    const auth = renderPage(`/register?invite=${TOKEN}`);
    await screen.findByText(/invited to join as/i);

    await userEvent.setup().type(screen.getByLabelText('Full name'), 'The Boss');
    await fillPasswords();

    await vi.waitFor(() =>
      expect(register).toHaveBeenCalledWith(
        expect.objectContaining({ email: 'boss@example.com', full_name: 'The Boss', invite_token: TOKEN }),
      ),
    );
    await vi.waitFor(() => expect(auth.login).toHaveBeenCalledWith('boss@example.com', 'password123'));
  });

  it('explains a bad invitation instead of showing a signup form', async () => {
    vi.spyOn(api, 'lookupInvitation').mockRejectedValue(
      new ApiError('This invitation is invalid, expired or already used.', 422, 'VALIDATION_ERROR'),
    );
    renderPage(`/register?invite=${TOKEN}`);

    expect(await screen.findByText(/invalid, expired or already used/i)).toBeInTheDocument();
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login');
  });

  it('shows the server error when signing up with an invitation fails', async () => {
    vi.spyOn(api, 'lookupInvitation').mockResolvedValue({
      email: 'late@example.com',
      role: 'DOCTOR',
      full_name: null,
      expires_at: '2030-01-08T00:00:00Z',
    });
    vi.spyOn(api, 'register').mockRejectedValue(new ApiError('A user with this email already exists.', 409, 'CONFLICT'));
    const auth = renderPage(`/register?invite=${TOKEN}`);
    await screen.findByText(/invited to join as/i);

    await userEvent.setup().type(screen.getByLabelText('Full name'), 'Late Person');
    await fillPasswords();

    expect(await screen.findByText(/already exists/i)).toBeInTheDocument();
    expect(auth.login).not.toHaveBeenCalled();
  });
});
