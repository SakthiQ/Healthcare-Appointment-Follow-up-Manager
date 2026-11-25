import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../../api/client';
import type { Appointment } from '../../api/types';
import DoctorAppointmentDetail from './DoctorAppointmentDetail';

// Only the no-show controls (#68). The page's other behaviour is covered by #36.

const notFound = () => new ApiError('Not found', 404, null);

function appt(overrides: Partial<Appointment> = {}): Appointment {
  return {
    id: 'a1', patient_id: 'p1', doctor_id: 'u1', doctor_profile_id: 'd1',
    start_time: '2020-01-07T09:00:00Z', end_time: '2020-01-07T09:30:00Z', status: 'CONFIRMED',
    created_at: '2020-01-01T00:00:00Z', updated_at: '2020-01-01T00:00:00Z',
    patient_name: 'Pam Patient', doctor_name: 'Dr Doc', doctor_specialization: 'Cardiology', doctor_timezone: 'UTC',
    ...overrides,
  };
}

function renderPage(appointment: Appointment) {
  vi.spyOn(api, 'getAppointment').mockResolvedValue(appointment);
  vi.spyOn(api, 'getPreVisitSummary').mockRejectedValue(notFound());
  vi.spyOn(api, 'getConsultation').mockRejectedValue(notFound());
  vi.spyOn(api, 'getPostVisitSummary').mockRejectedValue(notFound());
  vi.spyOn(api, 'getHistorySummary').mockRejectedValue(notFound());
  return render(
    <MemoryRouter initialEntries={['/doctor/appointments/a1']}>
      <Routes>
        <Route path="/doctor/appointments/:appointmentId" element={<DoctorAppointmentDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('DoctorAppointmentDetail: no-show', () => {
  it('marks a past appointment as a no-show after confirmation', async () => {
    const mark = vi.spyOn(api, 'markNoShow').mockResolvedValue(appt({ status: 'NO_SHOW' }));
    const user = userEvent.setup();
    renderPage(appt());

    await user.click(await screen.findByRole('button', { name: 'Mark as no-show' }));
    expect(mark).not.toHaveBeenCalled();
    vi.mocked(api.getAppointment).mockResolvedValue(appt({ status: 'NO_SHOW' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Mark as no-show' }));

    expect(mark).toHaveBeenCalledWith('a1');
    expect(await screen.findByText(/Marked as a no-show/)).toBeInTheDocument();
    expect(await screen.findByText('NO_SHOW')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Mark as no-show' })).not.toBeInTheDocument();
  });

  it('backing out of the dialog marks nothing', async () => {
    const mark = vi.spyOn(api, 'markNoShow');
    const user = userEvent.setup();
    renderPage(appt());

    await user.click(await screen.findByRole('button', { name: 'Mark as no-show' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }));

    expect(mark).not.toHaveBeenCalled();
  });

  it('is not offered before the start time or from other statuses', async () => {
    const { unmount } = renderPage(appt({ start_time: '2099-01-07T09:00:00Z', end_time: '2099-01-07T09:30:00Z' }));
    await screen.findByText('CONFIRMED');
    expect(screen.queryByRole('button', { name: 'Mark as no-show' })).not.toBeInTheDocument();
    unmount();

    renderPage(appt({ status: 'CANCELLED' }));
    await screen.findByText('CANCELLED');
    expect(screen.queryByRole('button', { name: 'Mark as no-show' })).not.toBeInTheDocument();
  });

  it('shows the error when the server refuses', async () => {
    vi.spyOn(api, 'markNoShow').mockRejectedValue(
      new ApiError('Only a confirmed or rescheduled appointment can be marked as a no-show, not COMPLETED.', 409, null),
    );
    const user = userEvent.setup();
    renderPage(appt());

    await user.click(await screen.findByRole('button', { name: 'Mark as no-show' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Mark as no-show' }));

    expect(await screen.findByText(/can be marked as a no-show, not COMPLETED/)).toBeInTheDocument();
  });
});
