import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../../api/client';
import type { Appointment } from '../../api/types';
import PatientAppointments from './PatientAppointments';
import { expectNoA11yViolations } from '../../test/a11y';

function appt(n: number): Appointment {
  const start = new Date(Date.UTC(2030, 0, 7, 9, 0) + n * 86_400_000).toISOString();
  return {
    id: `a${n}`,
    patient_id: 'p1',
    doctor_id: 'u1',
    doctor_profile_id: 'd1',
    start_time: start,
    end_time: start,
    status: 'CONFIRMED',
    created_at: start,
    updated_at: start,
    doctor_name: `Dr Number ${n}`,
    doctor_timezone: 'UTC',
  } as Appointment;
}

function renderList() {
  return render(
    <MemoryRouter>
      <PatientAppointments />
    </MemoryRouter>,
  );
}

describe('PatientAppointments', () => {
  it('shows one page at a time and pages through the rest', async () => {
    const spy = vi.spyOn(api, 'listAppointmentsPage').mockImplementation(async ({ offset }) => ({
      items: offset === 0 ? Array.from({ length: 25 }, (_, i) => appt(i + 1)) : [appt(26), appt(27)],
      total: 27,
    }));
    const user = userEvent.setup();
    renderList();

    expect(await screen.findByText(/Dr Number 1 ·/)).toBeInTheDocument();
    expect(screen.getByText('Showing 1–25 of 27')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled();
    expect(spy).toHaveBeenLastCalledWith({ status: undefined, limit: 25, offset: 0 });

    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(await screen.findByText(/Dr Number 27 ·/)).toBeInTheDocument();
    expect(screen.getByText('Showing 26–27 of 27')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
    expect(spy).toHaveBeenLastCalledWith({ status: undefined, limit: 25, offset: 25 });
  });

  it('goes back to the first page when the filter changes', async () => {
    const spy = vi.spyOn(api, 'listAppointmentsPage').mockResolvedValue({
      items: Array.from({ length: 25 }, (_, i) => appt(i + 1)),
      total: 60,
    });
    const user = userEvent.setup();
    renderList();

    await screen.findByText('Showing 1–25 of 60');
    await user.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByText('Showing 26–50 of 60');
    await user.click(screen.getByRole('button', { name: 'Cancelled' }));

    expect(spy).toHaveBeenLastCalledWith({ status: 'CANCELLED', limit: 25, offset: 0 });
  });

  it('shows no pager when everything fits on one page', async () => {
    vi.spyOn(api, 'listAppointmentsPage').mockResolvedValue({ items: [appt(1)], total: 1 });
    renderList();
    expect(await screen.findByText(/Dr Number 1 ·/)).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Pages' })).not.toBeInTheDocument();
  });
});

describe('PatientAppointments: accessibility', () => {
  it('has no axe violations', async () => {
    vi.spyOn(api, 'listAppointmentsPage').mockResolvedValue({ items: [appt(1)], total: 1 });
    renderList();
    await screen.findByText(/Dr Number 1 ·/);
    await expectNoA11yViolations(document.body);
  });
});
