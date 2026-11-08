import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../../api/client';
import type { AuditLogEntry, AuditLogPage } from '../../api/types';
import AuditLog from './AuditLog';

function entry(overrides: Partial<AuditLogEntry> = {}): AuditLogEntry {
  return {
    id: 'e1',
    occurred_at: '2030-01-07T09:30:00Z',
    actor_user_id: 'aaaaaaaa-1111-2222-3333-444444444444',
    actor_role: 'DOCTOR',
    action: 'appointment.view',
    resource_type: 'appointment',
    resource_id: 'bbbbbbbb-1111-2222-3333-444444444444',
    patient_id: 'cccccccc-1111-2222-3333-444444444444',
    ip: '203.0.113.9',
    detail: null,
    ...overrides,
  };
}

function page(items: AuditLogEntry[], total = items.length, offset = 0): AuditLogPage {
  return { items, total, limit: 25, offset };
}

describe('AuditLog', () => {
  it('loads the newest entries and shows who did what, to whom, from where', async () => {
    const spy = vi.spyOn(api, 'listAuditLogs').mockResolvedValue(page([entry()]));
    render(<AuditLog />);

    expect(await screen.findByText('appointment.view')).toBeInTheDocument();
    expect(screen.getByText('DOCTOR')).toBeInTheDocument();
    expect(screen.getByText('203.0.113.9')).toBeInTheDocument();
    expect(screen.getByText('07 Jan 2030, 09:30 UTC')).toBeInTheDocument();
    expect(screen.getByText('1 entry')).toBeInTheDocument();
    expect(spy).toHaveBeenCalledWith({ action: undefined, patient_id: undefined, actor_id: undefined, limit: 25, offset: 0 });
  });

  it('shows a short id with the full one on hover', async () => {
    vi.spyOn(api, 'listAuditLogs').mockResolvedValue(page([entry()]));
    render(<AuditLog />);

    const actor = await screen.findByText('aaaaaaaa');
    expect(actor).toHaveAttribute('title', 'aaaaaaaa-1111-2222-3333-444444444444');
  });

  it('applies trimmed filters and goes back to the first page', async () => {
    const spy = vi.spyOn(api, 'listAuditLogs').mockResolvedValue(page([entry()], 60));
    render(<AuditLog />);
    await screen.findByText('appointment.view');
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: 'Older' })); // now on page 2
    await user.type(screen.getByLabelText('Action'), ' auth. ');
    await user.type(screen.getByLabelText('Patient id'), 'p-1');
    await user.click(screen.getByRole('button', { name: 'Apply filters' }));

    await vi.waitFor(() =>
      expect(spy).toHaveBeenLastCalledWith({ action: 'auth.', patient_id: 'p-1', actor_id: undefined, limit: 25, offset: 0 }),
    );
  });

  it('pages through results', async () => {
    const spy = vi.spyOn(api, 'listAuditLogs').mockResolvedValue(page([entry()], 60));
    render(<AuditLog />);
    await screen.findByText('Page 1 of 3');
    const user = userEvent.setup();

    expect(screen.getByRole('button', { name: 'Newer' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Older' }));
    await screen.findByText('Page 2 of 3');
    expect(spy).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 25 }));

    await user.click(screen.getByRole('button', { name: 'Older' }));
    await screen.findByText('Page 3 of 3');
    expect(screen.getByRole('button', { name: 'Older' })).toBeDisabled();
  });

  it('clears the filters', async () => {
    const spy = vi.spyOn(api, 'listAuditLogs').mockResolvedValue(page([entry()]));
    render(<AuditLog />);
    await screen.findByText('appointment.view');
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Action'), 'auth.');
    await user.click(screen.getByRole('button', { name: 'Apply filters' }));
    await vi.waitFor(() => expect(spy).toHaveBeenLastCalledWith(expect.objectContaining({ action: 'auth.' })));

    await user.click(screen.getByRole('button', { name: 'Clear' }));

    await vi.waitFor(() => expect(spy).toHaveBeenLastCalledWith(expect.objectContaining({ action: undefined })));
    expect(screen.getByLabelText('Action')).toHaveValue('');
  });

  it('says so when nothing matches', async () => {
    vi.spyOn(api, 'listAuditLogs').mockResolvedValue(page([]));
    render(<AuditLog />);
    expect(await screen.findByText('No entries match.')).toBeInTheDocument();
    expect(screen.getByText('0 entries')).toBeInTheDocument();
  });

  it('shows the server error with a retry', async () => {
    const spy = vi
      .spyOn(api, 'listAuditLogs')
      .mockRejectedValueOnce(new ApiError('You are not authorised to perform this action.', 403, 'FORBIDDEN'))
      .mockResolvedValue(page([entry()]));
    render(<AuditLog />);

    expect(await screen.findByText(/not authorised/i)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Retry' }));

    expect(await screen.findByText('appointment.view')).toBeInTheDocument();
    expect(spy).toHaveBeenCalledTimes(2);
  });
});
