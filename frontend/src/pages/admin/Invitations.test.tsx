import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../../api/client';
import type { Invitation, InvitationCreated } from '../../api/types';
import Invitations from './Invitations';

function invitation(overrides: Partial<Invitation> = {}): Invitation {
  return {
    id: 'inv-1',
    email: 'dr.pending@example.com',
    role: 'DOCTOR',
    full_name: null,
    specialization: 'Cardiology',
    slot_duration_minutes: 30,
    timezone: 'UTC',
    status: 'PENDING',
    expires_at: '2030-01-08T09:00:00Z',
    created_at: '2030-01-01T09:00:00Z',
    invited_by: 'admin-1',
    ...overrides,
  };
}

function created(overrides: Partial<InvitationCreated> = {}): InvitationCreated {
  return {
    invitation: invitation(),
    invite_link: 'https://app.example.com/register?invite=secret-token-value',
    email_queued: true,
    ...overrides,
  };
}

describe('Invitations', () => {
  it('lists invitations with their status, and only pending ones can be revoked', async () => {
    vi.spyOn(api, 'listInvitations').mockResolvedValue([
      invitation(),
      invitation({ id: 'inv-2', email: 'used@example.com', status: 'ACCEPTED' }),
      invitation({ id: 'inv-3', email: 'old@example.com', status: 'EXPIRED', role: 'ADMIN', specialization: null }),
    ]);
    render(<Invitations />);

    expect(await screen.findByText('dr.pending@example.com')).toBeInTheDocument();
    expect(screen.getByText('PENDING')).toBeInTheDocument();
    expect(screen.getByText('ACCEPTED')).toBeInTheDocument();
    expect(screen.getByText('EXPIRED')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /^Revoke invitation/ })).toHaveLength(1);
  });

  it('says so when there are none', async () => {
    vi.spyOn(api, 'listInvitations').mockResolvedValue([]);
    render(<Invitations />);
    expect(await screen.findByText('No invitations yet.')).toBeInTheDocument();
  });

  it('validates a doctor invitation before calling the API', async () => {
    vi.spyOn(api, 'listInvitations').mockResolvedValue([]);
    const create = vi.spyOn(api, 'createInvitation');
    render(<Invitations />);
    await screen.findByText('No invitations yet.');

    await userEvent.setup().click(screen.getByRole('button', { name: 'Send invitation' }));

    expect(screen.getByText('Enter a valid email address.')).toBeInTheDocument();
    expect(screen.getByText('Specialisation is required for a doctor.')).toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();
  });

  it('invites a doctor and shows the link once', async () => {
    const list = vi.spyOn(api, 'listInvitations').mockResolvedValue([]);
    const create = vi.spyOn(api, 'createInvitation').mockResolvedValue(created());
    render(<Invitations />);
    await screen.findByText('No invitations yet.');
    const user = userEvent.setup();

    await user.type(screen.getByLabelText('Email'), ' dr.pending@example.com ');
    await user.type(screen.getByLabelText('Specialisation'), 'Cardiology');
    await user.click(screen.getByRole('button', { name: 'Send invitation' }));

    expect(await screen.findByTestId('invite-link')).toHaveTextContent('register?invite=secret-token-value');
    expect(screen.getByText(/email with the link is on its way/i)).toBeInTheDocument();
    expect(create).toHaveBeenCalledWith({
      email: 'dr.pending@example.com',
      role: 'DOCTOR',
      full_name: undefined,
      specialization: 'Cardiology',
      slot_duration_minutes: 30,
      timezone: 'UTC',
    });
    await vi.waitFor(() => expect(list).toHaveBeenCalledTimes(2)); // the list refreshes
    expect(screen.getByLabelText('Email')).toHaveValue('');
  });

  it('leaves the doctor details out of an administrator invitation', async () => {
    vi.spyOn(api, 'listInvitations').mockResolvedValue([]);
    const create = vi.spyOn(api, 'createInvitation').mockResolvedValue(
      created({ invitation: invitation({ role: 'ADMIN', specialization: null }) }),
    );
    render(<Invitations />);
    await screen.findByText('No invitations yet.');
    const user = userEvent.setup();

    await user.selectOptions(screen.getByLabelText('Role'), 'ADMIN');
    expect(screen.queryByLabelText('Specialisation')).not.toBeInTheDocument();
    await user.type(screen.getByLabelText('Email'), 'second.admin@example.com');
    await user.click(screen.getByRole('button', { name: 'Send invitation' }));

    await vi.waitFor(() =>
      expect(create).toHaveBeenCalledWith({ email: 'second.admin@example.com', role: 'ADMIN', full_name: undefined }),
    );
  });

  it('tells the admin to send the link themselves when the email could not be queued', async () => {
    vi.spyOn(api, 'listInvitations').mockResolvedValue([]);
    vi.spyOn(api, 'createInvitation').mockResolvedValue(created({ email_queued: false }));
    render(<Invitations />);
    await screen.findByText('No invitations yet.');
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Email'), 'dr.pending@example.com');
    await user.type(screen.getByLabelText('Specialisation'), 'Cardiology');

    await user.click(screen.getByRole('button', { name: 'Send invitation' }));

    expect(await screen.findByText(/could not be queued/i)).toBeInTheDocument();
  });

  it('shows the server error when inviting fails', async () => {
    vi.spyOn(api, 'listInvitations').mockResolvedValue([]);
    vi.spyOn(api, 'createInvitation').mockRejectedValue(new ApiError('A user with this email already exists.', 409, 'CONFLICT'));
    render(<Invitations />);
    await screen.findByText('No invitations yet.');
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Email'), 'member@example.com');
    await user.type(screen.getByLabelText('Specialisation'), 'Cardiology');

    await user.click(screen.getByRole('button', { name: 'Send invitation' }));

    expect(await screen.findByText(/already exists/i)).toBeInTheDocument();
  });

  it('revokes a pending invitation and refreshes the list', async () => {
    const list = vi.spyOn(api, 'listInvitations').mockResolvedValue([invitation()]);
    const revoke = vi.spyOn(api, 'revokeInvitation').mockResolvedValue(undefined);
    render(<Invitations />);

    await userEvent.setup().click(await screen.findByRole('button', { name: 'Revoke invitation for dr.pending@example.com' }));

    expect(revoke).toHaveBeenCalledWith('inv-1');
    await vi.waitFor(() => expect(list).toHaveBeenCalledTimes(2));
  });
});
