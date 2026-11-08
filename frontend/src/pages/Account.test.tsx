import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { makeAuth, makeUser } from '../test/helpers';
import Account from './Account';

vi.mock('../auth/AuthContext', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../auth/AuthContext')>()),
  useAuth: vi.fn(),
}));

async function submitChange(current: string, next: string, confirm: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Current password'), current);
  await user.type(screen.getByLabelText('New password'), next);
  await user.type(screen.getByLabelText('Confirm new password'), confirm);
  await user.click(screen.getByRole('button', { name: 'Change password' }));
}

describe('Account: profile and email status', () => {
  it('shows a verified user without a resend prompt', () => {
    vi.mocked(useAuth).mockReturnValue(makeAuth({ user: makeUser({ email_verified: true }) }));
    render(<Account />);
    expect(screen.getByText('Verified')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send the link again' })).not.toBeInTheDocument();
  });

  it('lets an unverified user ask for the link again', async () => {
    vi.mocked(useAuth).mockReturnValue(makeAuth({ user: makeUser({ email_verified: false }) }));
    const spy = vi.spyOn(api, 'resendVerification').mockResolvedValue({ message: 'sent' });
    render(<Account />);
    expect(screen.getByText('Not verified')).toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole('button', { name: 'Send the link again' }));

    expect(await screen.findByText('A new link is on its way.')).toBeInTheDocument();
    expect(spy).toHaveBeenCalledWith('pat@example.com');
  });

  it('shows a resend failure (for example a rate limit)', async () => {
    vi.mocked(useAuth).mockReturnValue(makeAuth({ user: makeUser({ email_verified: false }) }));
    vi.spyOn(api, 'resendVerification').mockRejectedValue(new ApiError('Too many requests.', 429, 'TOO_MANY_REQUESTS'));
    render(<Account />);

    await userEvent.setup().click(screen.getByRole('button', { name: 'Send the link again' }));

    expect(await screen.findByText('Too many requests.')).toBeInTheDocument();
  });
});

describe('Account: changing the password', () => {
  it.each([
    ['mismatched confirmation', 'old-password', 'new-password-1', 'new-password-2', 'The two passwords do not match.'],
    ['same as the current one', 'old-password', 'old-password', 'old-password', /different from your current one/i],
    ['too short', 'old-password', 'abc', 'abc', /at least 6 characters/i],
  ])('refuses a %s without calling the API', async (_label, current, next, confirm, message) => {
    const auth = makeAuth();
    vi.mocked(useAuth).mockReturnValue(auth);
    render(<Account />);

    await submitChange(current, next, confirm);

    expect(screen.getByText(message)).toBeInTheDocument();
    expect(auth.changePassword).not.toHaveBeenCalled();
  });

  it('requires the current password', async () => {
    const auth = makeAuth();
    vi.mocked(useAuth).mockReturnValue(auth);
    render(<Account />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('New password'), 'new-password-1');
    await user.type(screen.getByLabelText('Confirm new password'), 'new-password-1');
    await user.click(screen.getByRole('button', { name: 'Change password' }));

    expect(screen.getByText('Enter your current password.')).toBeInTheDocument();
    expect(auth.changePassword).not.toHaveBeenCalled();
  });

  it('changes the password, says other devices were signed out, and clears the fields', async () => {
    const auth = makeAuth();
    vi.mocked(useAuth).mockReturnValue(auth);
    render(<Account />);

    await submitChange('old-password', 'new-password-1', 'new-password-1');

    expect(await screen.findByText(/other signed-in devices were signed out/i)).toBeInTheDocument();
    expect(auth.changePassword).toHaveBeenCalledWith('old-password', 'new-password-1');
    expect(screen.getByLabelText('Current password')).toHaveValue('');
    expect(screen.getByLabelText('New password')).toHaveValue('');
  });

  it('shows the server\'s message for a wrong current password and keeps what was typed', async () => {
    const auth = makeAuth({
      changePassword: vi.fn().mockRejectedValue(new ApiError('Current password is incorrect.', 422, 'VALIDATION_ERROR')),
    });
    vi.mocked(useAuth).mockReturnValue(auth);
    render(<Account />);

    await submitChange('wrong-password', 'new-password-1', 'new-password-1');

    expect(await screen.findByText('Current password is incorrect.')).toBeInTheDocument();
    expect(screen.getByLabelText('Current password')).toHaveValue('wrong-password');
    expect(screen.queryByText(/other signed-in devices/i)).not.toBeInTheDocument();
  });
});
