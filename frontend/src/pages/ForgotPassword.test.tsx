import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../api/client';
import ForgotPassword from './ForgotPassword';

const SENT = 'If that address belongs to an account, we have sent it an email with a link.';

function renderPage() {
  return render(
    <MemoryRouter>
      <ForgotPassword />
    </MemoryRouter>,
  );
}

describe('ForgotPassword', () => {
  it('rejects an obviously invalid email without calling the API', async () => {
    const spy = vi.spyOn(api, 'forgotPassword');
    renderPage();

    await userEvent.setup().type(screen.getByLabelText('Email'), 'not-an-email');
    await userEvent.setup().click(screen.getByRole('button', { name: 'Send reset link' }));

    expect(screen.getByText('Enter a valid email address.')).toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
  });

  it('sends the trimmed email and shows the same confirmation for any address', async () => {
    const spy = vi.spyOn(api, 'forgotPassword').mockResolvedValue({ message: SENT });
    renderPage();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText('Email'), '  pat@example.com ');
    await user.click(screen.getByRole('button', { name: 'Send reset link' }));

    expect(await screen.findByText(/we have sent it an email/i)).toBeInTheDocument();
    expect(spy).toHaveBeenCalledWith('pat@example.com');
    expect(screen.getByRole('button', { name: 'Send it again' })).toBeEnabled();
  });

  it('shows the rate-limit message from the server', async () => {
    vi.spyOn(api, 'forgotPassword').mockRejectedValue(
      new ApiError('Too many requests. Please try again in about 30 minute(s).', 429, 'TOO_MANY_REQUESTS'),
    );
    renderPage();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText('Email'), 'pat@example.com');
    await user.click(screen.getByRole('button', { name: 'Send reset link' }));

    expect(await screen.findByText(/too many requests/i)).toBeInTheDocument();
  });

  it('links back to sign in', () => {
    renderPage();
    expect(screen.getByRole('link', { name: 'Back to sign in' })).toHaveAttribute('href', '/login');
  });
});
