import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../../api/client';
import type { Appointment } from '../../api/types';
import ConflictedAppointments from './ConflictedAppointments';

function appt(overrides: Partial<Appointment> = {}): Appointment {
  return {
    id: 'a1',
    patient_id: 'p1',
    doctor_id: 'u1',
    doctor_profile_id: 'd1',
    start_time: '2030-01-07T09:00:00Z',
    end_time: '2030-01-07T09:30:00Z',
    status: 'CONFLICTED',
    created_at: '2030-01-01T00:00:00Z',
    updated_at: '2030-01-01T00:00:00Z',
    patient_name: 'Pam Patient',
    doctor_name: 'Dr Away',
    doctor_specialization: 'Cardiology',
    doctor_timezone: 'UTC',
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <ConflictedAppointments />
    </MemoryRouter>,
  );
}

describe('ConflictedAppointments', () => {
  it('asks only for conflicted appointments', async () => {
    const spy = vi.spyOn(api, 'listAppointments').mockResolvedValue([]);
    renderPage();

    await screen.findByText('No conflicted appointments. Everything is on track.');
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith({ status: 'CONFLICTED' });
  });

  it('shows the doctor, patient and status of each conflict, and how many there are', async () => {
    vi.spyOn(api, 'listAppointments').mockResolvedValue([
      appt({ id: 'a1' }),
      appt({ id: 'a2', patient_id: 'p2', patient_name: 'Sam Second', doctor_name: 'Dr Elsewhere' }),
    ]);
    renderPage();

    expect(await screen.findByText('2 conflicted appointment(s)')).toBeInTheDocument();
    const [, ...rows] = screen.getAllByRole('row');
    expect(rows).toHaveLength(2);

    expect(within(rows[0]).getByText('Dr Away')).toBeInTheDocument();
    expect(within(rows[0]).getByText('Pam Patient')).toBeInTheDocument();
    expect(within(rows[0]).getByText('CONFLICTED')).toBeInTheDocument();

    expect(within(rows[1]).getByText('Dr Elsewhere')).toBeInTheDocument();
    expect(within(rows[1]).getByText('Sam Second')).toBeInTheDocument();
    expect(within(rows[1]).getByText('CONFLICTED')).toBeInTheDocument();
  });

  it('falls back to the patient id and a dash when names are missing', async () => {
    vi.spyOn(api, 'listAppointments').mockResolvedValue([
      appt({ patient_id: 'patient-uuid-123', patient_name: null, doctor_name: null }),
    ]);
    renderPage();

    expect(await screen.findByText('1 conflicted appointment(s)')).toBeInTheDocument();
    const [, row] = screen.getAllByRole('row');
    expect(within(row).getByText('patient-uuid-123')).toBeInTheDocument();
    expect(within(row).getByText('—')).toBeInTheDocument();
  });

  it('says so when nothing is conflicted', async () => {
    vi.spyOn(api, 'listAppointments').mockResolvedValue([]);
    renderPage();

    expect(await screen.findByText('No conflicted appointments. Everything is on track.')).toBeInTheDocument();
    expect(screen.getByText('0 conflicted appointment(s)')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('shows the error and no table when loading fails', async () => {
    vi.spyOn(api, 'listAppointments').mockRejectedValue(
      new ApiError('Could not load conflicted appointments.', 500, null),
    );
    renderPage();

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load conflicted appointments.');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.queryByText('No conflicted appointments. Everything is on track.')).not.toBeInTheDocument();
  });
});
