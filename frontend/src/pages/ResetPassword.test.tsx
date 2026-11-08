import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../api/client';
import ResetPassword from './ResetPassword';

function renderPage(url = '/reset-password?token=abcdefghijklmnop') {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <ResetPassword />
    </MemoryRouter>,
  );
}

async function fill(password: string, confirm: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('New password'), password);
  await user.type(screen.getByLabelText('Confirm new password'), confirm);
  await user.click(screen.getByRole('button', { name: 'Change password' }));
}

describe('ResetPassword', () => {
  it('explains an incomplete link and offers a new one', () => {
    renderPage('/reset-password');
    expect(screen.getByText(/this link is incomplete/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Request a new link' })).toHaveAttribute('href', '/forgot-password');
    expect(screen.queryByLabelText('New password')).not.toBeInTheDocument();
  });

  it('catches mismatched passwords before calling the API', async () => {
    const spy = vi.spyOn(api, 'resetPassword');
    renderPage();
    await fill('first-password', 'second-password');
    expect(screen.getByText('The two passwords do not match.')).toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
  });

  it('catches a too-short password before calling the API', async () => {
    const spy = vi.spyOn(api, 'resetPassword');
    renderPage();
    await fill('abc', 'abc');
    expect(screen.getByText(/at least 6 characters/i)).toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
  });

  it('sends the token from the link with the new password, then points to sign in', async () => {
    const spy = vi.spyOn(api, 'resetPassword').mockResolvedValue(undefined);
    renderPage();

    await fill('brand-new-pass', 'brand-new-pass');

    expect(await screen.findByText(/password has been changed/i)).toBeInTheDocument();
    expect(spy).toHaveBeenCalledWith('abcdefghijklmnop', 'brand-new-pass');
    expect(screen.getByRole('link', { name: 'Go to sign in' })).toHaveAttribute('href', '/login');
  });

  it('shows the server\'s message for an expired or used link, and keeps the form', async () => {
    vi.spyOn(api, 'resetPassword').mockRejectedValue(
      new ApiError('This link is invalid or has expired. Please request a new one.', 422, 'VALIDATION_ERROR'),
    );
    renderPage();

    await fill('brand-new-pass', 'brand-new-pass');

    expect(await screen.findByText(/invalid or has expired/i)).toBeInTheDocument();
    expect(screen.getByLabelText('New password')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Request a new one' })).toHaveAttribute('href', '/forgot-password');
  });
});
