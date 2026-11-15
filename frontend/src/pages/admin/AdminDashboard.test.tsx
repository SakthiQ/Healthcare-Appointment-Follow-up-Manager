import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../../api/client';
import type { AdminStats, Doctor } from '../../api/types';
import { useAuth } from '../../auth/AuthContext';
import { makeAuth, makeUser } from '../../test/helpers';
import AdminDashboard from './AdminDashboard';

vi.mock('../../auth/AuthContext', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../auth/AuthContext')>()),
  useAuth: vi.fn(),
}));

function doctor(overrides: Partial<Doctor> = {}): Doctor {
  return {
    id: 'd1',
    user_id: 'u1',
    email: 'doc@example.com',
    full_name: 'Dr Active',
    specialization: 'Cardiology',
    slot_duration_minutes: 30,
    timezone: 'UTC',
    is_active: true,
    created_at: '2030-01-01T00:00:00Z',
    ...overrides,
  };
}

function stats(overrides: Partial<AdminStats> = {}): AdminStats {
  return {
    active_doctors: 1,
    appointments_total: 2481,
    appointments_by_status: {
      HELD: 0, CONFIRMED: 2400, RESCHEDULED: 60, CANCELLED: 18, CONFLICTED: 3, COMPLETED: 0,
    },
    ...overrides,
  };
}

function renderDashboard() {
  vi.mocked(useAuth).mockReturnValue(makeAuth({ user: makeUser({ role: 'ADMIN', full_name: 'Ada Admin' }) }));
  return render(
    <MemoryRouter>
      <AdminDashboard />
    </MemoryRouter>,
  );
}

describe('AdminDashboard', () => {
  it('shows counts from the stats endpoint and never downloads every appointment', async () => {
    vi.spyOn(api, 'searchDoctors').mockResolvedValue([doctor(), doctor({ id: 'd2', full_name: 'Dr Gone', is_active: false })]);
    const statsSpy = vi.spyOn(api, 'getAdminStats').mockResolvedValue(stats());
    const listSpy = vi.spyOn(api, 'listAppointments');

    renderDashboard();

    expect(await screen.findByText('2481')).toBeInTheDocument();
    expect(screen.getByText('3 appointment(s) need attention')).toBeInTheDocument();
    expect(screen.getByText('Dr Active')).toBeInTheDocument();
    expect(screen.queryByText('Dr Gone')).not.toBeInTheDocument();
    expect(statsSpy).toHaveBeenCalledTimes(1);
    expect(listSpy).not.toHaveBeenCalled();
  });

  it('hides the conflict banner when nothing is conflicted', async () => {
    vi.spyOn(api, 'searchDoctors').mockResolvedValue([doctor()]);
    vi.spyOn(api, 'getAdminStats').mockResolvedValue(
      stats({ appointments_total: 5, appointments_by_status: { CONFIRMED: 5, CONFLICTED: 0 } }),
    );

    renderDashboard();

    expect(await screen.findByText('5')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
