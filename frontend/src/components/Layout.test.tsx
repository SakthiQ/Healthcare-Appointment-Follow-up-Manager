import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { useAuth } from '../auth/AuthContext';
import type { UserRole } from '../api/types';
import { makeAuth, makeUser } from '../test/helpers';
import Layout from './Layout';

vi.mock('../auth/AuthContext', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../auth/AuthContext')>()),
  useAuth: vi.fn(),
}));

function renderLayout(auth = makeAuth()) {
  vi.mocked(useAuth).mockReturnValue(auth);
  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<p>page body</p>} />
          <Route path="/login" element={<p>login page</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
  return auth;
}

describe('Layout: email verification banner', () => {
  it('nudges a user whose email is not verified, linking to the account page', () => {
    renderLayout(makeAuth({ user: makeUser({ email_verified: false }) }));
    expect(screen.getByText(/your email address is not verified yet/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open your account' })).toHaveAttribute('href', '/account');
    expect(screen.getByText('page body')).toBeInTheDocument(); // it never blocks the page
  });

  it('shows nothing for a verified user', () => {
    renderLayout(makeAuth({ user: makeUser({ email_verified: true }) }));
    expect(screen.queryByText(/not verified yet/i)).not.toBeInTheDocument();
  });
});

describe('Layout: navigation', () => {
  it.each([
    ['PATIENT', ['Dashboard', 'Find a doctor', 'My appointments', 'Account']],
    ['DOCTOR', ['Dashboard', 'Appointments', 'Account']],
    ['ADMIN', ['Dashboard', 'Doctors', 'Invitations', 'Conflicted appointments', 'Audit log', 'Account']],
  ] as [UserRole, string[]][])('%s sees their own links, including Account', (role, labels) => {
    renderLayout(makeAuth({ user: makeUser({ role }) }));
    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(Array.from(nav.querySelectorAll('a')).map((a) => a.textContent)).toEqual(labels);
    expect(screen.getByRole('link', { name: 'Account' })).toHaveAttribute('href', '/account');
  });

  it('only admins get the audit log link', () => {
    renderLayout(makeAuth({ user: makeUser({ role: 'DOCTOR' }) }));
    expect(screen.queryByRole('link', { name: 'Audit log' })).not.toBeInTheDocument();
  });

  it('logs out and returns to sign in', async () => {
    const auth = renderLayout();

    await userEvent.setup().click(screen.getByRole('button', { name: 'Log out' }));

    expect(auth.logout).toHaveBeenCalledTimes(1);
    expect(await screen.findByText('login page')).toBeInTheDocument();
  });
});
