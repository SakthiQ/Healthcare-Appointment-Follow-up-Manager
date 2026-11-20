import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../../api/client';
import type { Appointment } from '../../api/types';
import DoctorAppointments from './DoctorAppointments';

function appt(n: number, overrides: Partial<Appointment> = {}): Appointment {
  const start = new Date(Date.UTC(2030, 0, 7, 9, 0) + n * 86_400_000).toISOString();
  return {
    id: `a${n}`,
    patient_id: `p${n}`,
    doctor_id: 'u1',
    doctor_profile_id: 'd1',
    start_time: start,
    end_time: start,
    status: 'CONFIRMED',
    created_at: start,
    updated_at: start,
    patient_name: `Patient Number ${n}`,
    doctor_name: 'Dr Doc',
    doctor_specialization: 'Cardiology',
    doctor_timezone: 'UTC',
    ...overrides,
  };
}

function renderList() {
  return render(
    <MemoryRouter>
      <DoctorAppointments />
    </MemoryRouter>,
  );
}

describe('DoctorAppointments', () => {
  it('shows the patient, status and a link to open each appointment', async () => {
    vi.spyOn(api, 'listAppointmentsPage').mockResolvedValue({
      items: [appt(1), appt(2, { status: 'CONFLICTED' })],
      total: 2,
    });
    renderList();

    expect(await screen.findByText(/Patient Number 1 ·/)).toBeInTheDocument();
    const rows = screen.getAllByRole('listitem');
    expect(rows).toHaveLength(2);

    expect(within(rows[0]).getByText(/Patient Number 1 ·/)).toBeInTheDocument();
    expect(within(rows[0]).getByText('CONFIRMED')).toBeInTheDocument();
    expect(within(rows[0]).getByRole('link', { name: 'Open' })).toHaveAttribute('href', '/doctor/appointments/a1');

    expect(within(rows[1]).getByText(/Patient Number 2 ·/)).toBeInTheDocument();
    expect(within(rows[1]).getByText('CONFLICTED')).toBeInTheDocument();
    expect(within(rows[1]).getByRole('link', { name: 'Open' })).toHaveAttribute('href', '/doctor/appointments/a2');
  });

  it('shows one page at a time and pages through the rest', async () => {
    const spy = vi.spyOn(api, 'listAppointmentsPage').mockImplementation(async ({ offset }) => ({
      items: offset === 0 ? Array.from({ length: 25 }, (_, i) => appt(i + 1)) : [appt(26), appt(27)],
      total: 27,
    }));
    const user = userEvent.setup();
    renderList();

    expect(await screen.findByText(/Patient Number 1 ·/)).toBeInTheDocument();
    expect(spy).toHaveBeenNthCalledWith(1, { status: undefined, limit: 25, offset: 0 });
    expect(screen.getByText('Showing 1–25 of 27')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled();

    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(await screen.findByText(/Patient Number 27 ·/)).toBeInTheDocument();
    expect(spy).toHaveBeenLastCalledWith({ status: undefined, limit: 25, offset: 25 });
    expect(screen.getByText('Showing 26–27 of 27')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
  });

  it('shows no pager when everything fits on one page', async () => {
    vi.spyOn(api, 'listAppointmentsPage').mockResolvedValue({ items: [appt(1)], total: 1 });
    renderList();

    expect(await screen.findByText(/Patient Number 1 ·/)).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Pages' })).not.toBeInTheDocument();
  });

  it('goes back to the first page with the new status when the filter changes', async () => {
    const spy = vi.spyOn(api, 'listAppointmentsPage').mockResolvedValue({
      items: Array.from({ length: 25 }, (_, i) => appt(i + 1)),
      total: 60,
    });
    const user = userEvent.setup();
    renderList();

    await screen.findByText('Showing 1–25 of 60');
    await user.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByText('Showing 26–50 of 60');
    await user.click(screen.getByRole('button', { name: 'Conflicted' }));

    expect(spy).toHaveBeenLastCalledWith({ status: 'CONFLICTED', limit: 25, offset: 0 });
    expect(await screen.findByText('Showing 1–25 of 60')).toBeInTheDocument();
  });

  it('says so when there are no appointments', async () => {
    vi.spyOn(api, 'listAppointmentsPage').mockResolvedValue({ items: [], total: 0 });
    renderList();

    expect(await screen.findByText('No appointments.')).toBeInTheDocument();
    expect(screen.queryByRole('listitem')).not.toBeInTheDocument();
  });

  it('shows the error and no empty state when loading fails', async () => {
    vi.spyOn(api, 'listAppointmentsPage').mockRejectedValue(
      new ApiError('Could not load appointments.', 500, null),
    );
    renderList();

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load appointments.');
    expect(screen.queryByText('No appointments.')).not.toBeInTheDocument();
  });
});
