import { render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../../api/client';
import type { Doctor } from '../../api/types';
import { expectNoA11yViolations } from '../../test/a11y';
import DoctorSchedule from './DoctorSchedule';

const me: Doctor = {
  id: 'd1', user_id: 'u1', email: 'ada@clinic.example.com', full_name: 'Dr Ada', specialization: 'Cardiology',
  slot_duration_minutes: 30, timezone: 'Asia/Kolkata', is_active: true, created_at: '2030-01-01T00:00:00Z',
};

function mockSchedule() {
  vi.spyOn(api, 'getMyDoctorProfile').mockResolvedValue(me);
  vi.spyOn(api, 'getDoctorSchedule').mockResolvedValue([
    { id: 'w1', doctor_id: 'd1', day_of_week: 0, start_time: '09:00:00', end_time: '13:00:00', is_active: true },
    { id: 'w2', doctor_id: 'd1', day_of_week: 2, start_time: '14:00:00', end_time: '18:30:00', is_active: true },
    { id: 'w3', doctor_id: 'd1', day_of_week: 4, start_time: '09:00:00', end_time: '17:00:00', is_active: false },
  ]);
  vi.spyOn(api, 'getDoctorLeaves').mockResolvedValue([
    { id: 'l2', doctor_id: 'd1', leave_date: '2099-03-02', reason: null, created_at: '2030-01-01T00:00:00Z' },
    { id: 'l1', doctor_id: 'd1', leave_date: '2099-02-14', reason: 'Conference', created_at: '2030-01-01T00:00:00Z' },
    { id: 'l0', doctor_id: 'd1', leave_date: '2000-01-01', reason: 'Long ago', created_at: '2000-01-01T00:00:00Z' },
  ]);
}

describe('DoctorSchedule', () => {
  it("loads the doctor's own profile, then their hours and leave", async () => {
    mockSchedule();
    render(<DoctorSchedule />);

    expect(await screen.findByRole('heading', { name: 'My schedule' })).toBeInTheDocument();
    await waitFor(() => expect(api.getDoctorSchedule).toHaveBeenCalledWith('d1'));
    await waitFor(() => expect(api.getDoctorLeaves).toHaveBeenCalledWith('d1'));
    expect(screen.getByText(/set by an administrator/)).toBeInTheDocument();
  });

  it('shows hours for working days and marks the rest as days off', async () => {
    mockSchedule();
    render(<DoctorSchedule />);

    const monday = (await screen.findByText('Monday')).closest('li') as HTMLElement;
    expect(within(monday).getByText('09:00–13:00')).toBeInTheDocument();
    const wednesday = screen.getByText('Wednesday').closest('li') as HTMLElement;
    expect(within(wednesday).getByText('14:00–18:30')).toBeInTheDocument();
    // An inactive row and a day with no row are both days off.
    for (const day of ['Tuesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']) {
      const row = screen.getByText(day).closest('li') as HTMLElement;
      expect(within(row).getByText('Day off')).toBeInTheDocument();
    }
  });

  it('lists upcoming leave earliest first, with reasons, and leaves out past dates', async () => {
    mockSchedule();
    render(<DoctorSchedule />);

    expect(await screen.findByText('Conference')).toBeInTheDocument();
    const leaveCard = screen.getByText('Upcoming leave').closest('section') as HTMLElement;
    const rows = within(leaveCard).getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText('Conference')).toBeInTheDocument();
    expect(within(rows[1]).getByText('No reason given')).toBeInTheDocument();
    expect(screen.queryByText('Long ago')).not.toBeInTheDocument();
  });

  it('says so when there is no upcoming leave', async () => {
    mockSchedule();
    vi.mocked(api.getDoctorLeaves).mockResolvedValue([]);
    render(<DoctorSchedule />);

    expect(await screen.findByText('No upcoming leave.')).toBeInTheDocument();
  });

  it('shows the error when the profile cannot be loaded', async () => {
    vi.spyOn(api, 'getMyDoctorProfile').mockRejectedValue(new ApiError('No doctor profile is linked to this account.', 404, null));
    render(<DoctorSchedule />);

    expect(await screen.findByRole('alert')).toHaveTextContent('No doctor profile is linked to this account.');
  });

  it('has no axe violations', async () => {
    mockSchedule();
    render(<DoctorSchedule />);
    await screen.findByText('Conference');
    await expectNoA11yViolations(document.body);
  });
});
