import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../../api/client';
import type { Appointment } from '../../api/types';
import { useAuth } from '../../auth/AuthContext';
import { makeAuth, makeUser } from '../../test/helpers';
import DoctorDashboard from './DoctorDashboard';

vi.mock('../../auth/AuthContext', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../auth/AuthContext')>()),
  useAuth: vi.fn(),
}));

function appt(overrides: Partial<Appointment> = {}): Appointment {
  return {
    id: 'a1',
    patient_id: 'p1',
    doctor_id: 'u1',
    doctor_profile_id: 'd1',
    start_time: '2030-01-07T09:00:00Z',
    end_time: '2030-01-07T09:30:00Z',
    status: 'CONFIRMED',
    created_at: '2030-01-01T00:00:00Z',
    updated_at: '2030-01-01T00:00:00Z',
    patient_name: 'Pam Patient',
    doctor_name: 'Dr Doc',
    doctor_specialization: 'Cardiology',
    doctor_timezone: 'UTC',
    ...overrides,
  };
}

function renderDashboard() {
  vi.mocked(useAuth).mockReturnValue(makeAuth({ user: makeUser({ role: 'DOCTOR', full_name: 'Dr Doc' }) }));
  return render(
    <MemoryRouter>
      <DoctorDashboard />
    </MemoryRouter>,
  );
}

describe('DoctorDashboard', () => {
  it('lists upcoming appointments with the patient, status and a link to open them', async () => {
    vi.spyOn(api, 'listAppointments').mockResolvedValue([
      appt({ id: 'a2', start_time: '2030-01-08T09:00:00Z', end_time: '2030-01-08T09:30:00Z', status: 'RESCHEDULED', patient_name: 'Rita Rescheduled' }),
      appt({ id: 'a1' }),
    ]);
    renderDashboard();

    expect(await screen.findByText(/Pam Patient ·/)).toBeInTheDocument();
    const rows = screen.getAllByRole('listitem');
    expect(rows).toHaveLength(2);

    // Earliest first.
    expect(within(rows[0]).getByText(/Pam Patient ·/)).toBeInTheDocument();
    expect(within(rows[0]).getByText('CONFIRMED')).toBeInTheDocument();
    expect(within(rows[0]).getByRole('link', { name: 'Open' })).toHaveAttribute('href', '/doctor/appointments/a1');

    expect(within(rows[1]).getByText(/Rita Rescheduled ·/)).toBeInTheDocument();
    expect(within(rows[1]).getByText('RESCHEDULED')).toBeInTheDocument();
    expect(within(rows[1]).getByRole('link', { name: 'Open' })).toHaveAttribute('href', '/doctor/appointments/a2');
  });

  it('leaves cancelled and past appointments out of the upcoming list', async () => {
    vi.spyOn(api, 'listAppointments').mockResolvedValue([
      appt({ id: 'a1' }),
      appt({ id: 'a2', status: 'CANCELLED', patient_name: 'Carl Cancelled' }),
      appt({ id: 'a3', start_time: '2020-01-07T09:00:00Z', end_time: '2020-01-07T09:30:00Z', patient_name: 'Pete Past' }),
    ]);
    renderDashboard();

    expect(await screen.findByText(/Pam Patient ·/)).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(1);
    expect(screen.queryByText(/Carl Cancelled/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Pete Past/)).not.toBeInTheDocument();
  });

  it('says so when there are no upcoming appointments', async () => {
    vi.spyOn(api, 'listAppointments').mockResolvedValue([]);
    renderDashboard();

    expect(await screen.findByText('You have no upcoming appointments.')).toBeInTheDocument();
    expect(screen.queryByRole('listitem')).not.toBeInTheDocument();
  });

  it('shows the error and no empty state when loading fails', async () => {
    vi.spyOn(api, 'listAppointments').mockRejectedValue(
      new ApiError('Could not load your appointments.', 500, null),
    );
    renderDashboard();

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load your appointments.');
    expect(screen.queryByText('You have no upcoming appointments.')).not.toBeInTheDocument();
  });
});
