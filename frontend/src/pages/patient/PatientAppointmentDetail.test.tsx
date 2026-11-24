import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../../api/client';
import type { AISummary, Appointment, AppointmentStatus, SlotGenerationResponse } from '../../api/types';
import PatientAppointmentDetail from './PatientAppointmentDetail';

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

function summary(overrides: Partial<AISummary>): AISummary {
  return {
    id: 's1',
    appointment_id: 'a1',
    type: 'PRE_VISIT',
    status: 'SUCCESS',
    payload: null,
    error_message: null,
    created_at: '2030-01-01T00:00:00Z',
    ...overrides,
  };
}

const notFound = () => new ApiError('Not found', 404, null);

function slots(): SlotGenerationResponse {
  return {
    doctor_id: 'd1',
    target_date: '2030-01-08',
    slot_duration_minutes: 30,
    timezone: 'UTC',
    total_slots: 3,
    available_slots: 2,
    slots: [
      { start_time: '2030-01-08T10:00:00Z', end_time: '2030-01-08T10:30:00Z', is_available: true },
      { start_time: '2030-01-08T10:30:00Z', end_time: '2030-01-08T11:00:00Z', is_available: false },
      { start_time: '2030-01-08T11:00:00Z', end_time: '2030-01-08T11:30:00Z', is_available: true },
    ],
  };
}

/** Mock the page's reads: the appointment, and no summaries unless a test says otherwise. */
function mockReads(appointment: Appointment) {
  vi.spyOn(api, 'getAppointment').mockResolvedValue(appointment);
  vi.spyOn(api, 'getPreVisitSummary').mockRejectedValue(notFound());
  vi.spyOn(api, 'getPostVisitSummary').mockRejectedValue(notFound());
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/patient/appointments/a1']}>
      <Routes>
        <Route path="/patient/appointments/:appointmentId" element={<PatientAppointmentDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('PatientAppointmentDetail', () => {
  beforeEach(() => {
    mockReads(appt());
  });

  it('shows the appointment from the route id, with its doctor and status', async () => {
    renderPage();

    expect(await screen.findByText('Dr Doc · Cardiology')).toBeInTheDocument();
    expect(api.getAppointment).toHaveBeenCalledWith('a1');
    expect(screen.getByText('CONFIRMED')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reschedule' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel appointment' })).toBeInTheDocument();
  });

  it('asks for confirmation, then cancels with the reason and shows the cancelled state', async () => {
    const cancel = vi.spyOn(api, 'cancelAppointment').mockResolvedValue(appt({ status: 'CANCELLED' }));
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: 'Cancel appointment' }));
    const dialog = screen.getByRole('dialog', { name: 'Cancel this appointment?' });
    expect(cancel).not.toHaveBeenCalled();

    vi.mocked(api.getAppointment).mockResolvedValue(appt({ status: 'CANCELLED', cancellation_reason: 'Feeling better' }));
    await user.type(within(dialog).getByLabelText(/Reason/), 'Feeling better');
    await user.click(within(dialog).getByRole('button', { name: 'Yes, cancel it' }));

    expect(cancel).toHaveBeenCalledWith('a1', 'Feeling better');
    expect(await screen.findByText('Your appointment has been cancelled.')).toBeInTheDocument();
    expect(await screen.findByText('CANCELLED')).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Cancel appointment' })).not.toBeInTheDocument();
  });

  it('closing the confirmation does not cancel', async () => {
    const cancel = vi.spyOn(api, 'cancelAppointment');
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: 'Cancel appointment' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(cancel).not.toHaveBeenCalled();
  });

  it('lists only free slots and reschedules to the chosen one', async () => {
    const getSlots = vi.spyOn(api, 'getSlots').mockResolvedValue(slots());
    const reschedule = vi.spyOn(api, 'rescheduleAppointment').mockResolvedValue(appt({ status: 'RESCHEDULED' }));
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: 'Reschedule' }));
    await waitFor(() => expect(getSlots).toHaveBeenCalled());
    expect(getSlots.mock.calls[0][0]).toBe('d1');

    const slotButtons = await screen.findAllByRole('button', { name: /^\d{2}:\d{2}/ });
    expect(slotButtons).toHaveLength(2); // the taken 10:30 slot is not offered
    vi.mocked(api.getAppointment).mockResolvedValue(appt({ status: 'RESCHEDULED' }));
    await user.click(slotButtons[1]);

    expect(reschedule).toHaveBeenCalledWith('a1', {
      new_start_time: '2030-01-08T11:00:00Z',
      new_end_time: '2030-01-08T11:30:00Z',
    });
    expect(await screen.findByText('Your appointment has been rescheduled.')).toBeInTheDocument();
    expect(await screen.findByText('RESCHEDULED')).toBeInTheDocument();
  });

  it('shows the error when the chosen slot was just taken, and reloads the slots', async () => {
    const getSlots = vi.spyOn(api, 'getSlots').mockResolvedValue(slots());
    vi.spyOn(api, 'rescheduleAppointment').mockRejectedValue(
      new ApiError('That slot was just booked by someone else.', 409, null),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: 'Reschedule' }));
    const [first] = await screen.findAllByRole('button', { name: /^\d{2}:\d{2}/ });
    const callsBefore = getSlots.mock.calls.length;
    await user.click(first);

    expect(await screen.findByText('That slot was just booked by someone else.')).toBeInTheDocument();
    await waitFor(() => expect(getSlots.mock.calls.length).toBeGreaterThan(callsBefore));
    expect(screen.queryByText('Your appointment has been rescheduled.')).not.toBeInTheDocument();
  });

  it('sends the symptoms and shows the pre-visit summary once it is ready', async () => {
    const submit = vi.spyOn(api, 'submitSymptomReport').mockResolvedValue({} as never);
    const generate = vi.spyOn(api, 'generatePreVisitSummary').mockResolvedValue({} as never);
    const user = userEvent.setup();
    renderPage();

    await user.type(await screen.findByLabelText(/Symptoms/), '  Chest pain since yesterday  ');
    vi.mocked(api.getPreVisitSummary).mockResolvedValue(
      summary({
        payload: {
          urgency: 'High',
          chief_complaint: 'Chest pain',
          suggested_questions: ['When did it start?', 'Does it spread?', 'Any shortness of breath?'],
        },
      }),
    );
    await user.click(screen.getByRole('button', { name: 'Generate pre-visit summary' }));

    expect(submit).toHaveBeenCalledWith('a1', 'Chest pain since yesterday');
    expect(generate).toHaveBeenCalledWith('a1');
    expect(await screen.findByText('Chest pain')).toBeInTheDocument();
    expect(screen.getByText('High')).toBeInTheDocument();
    expect(screen.getByText('Does it spread?')).toBeInTheDocument();
    expect(screen.queryByLabelText(/Symptoms/)).not.toBeInTheDocument();
  });

  it('asks for more detail instead of sending a too-short symptom report', async () => {
    const submit = vi.spyOn(api, 'submitSymptomReport');
    const user = userEvent.setup();
    renderPage();

    await user.type(await screen.findByLabelText(/Symptoms/), 'ok');
    await user.click(screen.getByRole('button', { name: 'Generate pre-visit summary' }));

    expect(screen.getByText('Please describe your symptoms (at least 3 characters).')).toBeInTheDocument();
    expect(submit).not.toHaveBeenCalled();
  });

  it('shows the error when generating the summary fails', async () => {
    vi.spyOn(api, 'submitSymptomReport').mockRejectedValue(new ApiError('Too many requests.', 429, null));
    const user = userEvent.setup();
    renderPage();

    await user.type(await screen.findByLabelText(/Symptoms/), 'Headache for two days');
    await user.click(screen.getByRole('button', { name: 'Generate pre-visit summary' }));

    expect(await screen.findByText('Too many requests.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Generate pre-visit summary' })).toBeEnabled();
  });

  it('says why when the pre-visit summary failed, without crashing', async () => {
    vi.mocked(api.getPreVisitSummary).mockResolvedValue(
      summary({ status: 'FAILED', error_message: 'The AI service timed out' }),
    );
    renderPage();

    expect(await screen.findByText('The summary could not be generated: The AI service timed out')).toBeInTheDocument();
  });

  it('shows the post-visit summary of a completed appointment, with no actions', async () => {
    mockReads(appt({ status: 'COMPLETED' }));
    vi.mocked(api.getPostVisitSummary).mockResolvedValue(
      summary({
        type: 'POST_VISIT',
        payload: {
          summary: 'You have a mild chest infection.',
          medication_schedule: 'Amoxicillin 500mg, three times a day, for 5 days',
          follow_up_steps: 'Come back if the fever lasts more than 3 days.',
        },
      }),
    );
    renderPage();

    expect(await screen.findByText('You have a mild chest infection.')).toBeInTheDocument();
    expect(screen.getByText('Amoxicillin 500mg, three times a day, for 5 days')).toBeInTheDocument();
    expect(screen.getByText('Come back if the fever lasts more than 3 days.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Reschedule' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Cancel appointment' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Symptoms/)).not.toBeInTheDocument();
  });

  it('waits politely when there is no post-visit summary yet', async () => {
    renderPage();

    expect(await screen.findByText(/hasn't published a post-visit summary yet/)).toBeInTheDocument();
  });

  it.each<[AppointmentStatus, boolean, boolean]>([
    ['CONFIRMED', true, true],
    ['RESCHEDULED', true, true],
    ['CONFLICTED', true, true],
    ['HELD', false, true],
    ['CANCELLED', false, false],
    ['COMPLETED', false, false],
  ])('a %s appointment: reschedule %s, cancel %s', async (status, canReschedule, canCancel) => {
    mockReads(appt({ status }));
    renderPage();

    await screen.findByText(status);
    expect(!!screen.queryByRole('button', { name: 'Reschedule' })).toBe(canReschedule);
    expect(!!screen.queryByRole('button', { name: 'Cancel appointment' })).toBe(canCancel);
  });

  it('warns that a conflicted appointment cannot go ahead', async () => {
    mockReads(appt({ status: 'CONFLICTED' }));
    renderPage();

    expect(await screen.findByText('Your doctor is unavailable for this date')).toBeInTheDocument();
  });

  it('shows the error and a way back when the appointment cannot be loaded', async () => {
    vi.mocked(api.getAppointment).mockRejectedValue(new ApiError('Appointment not found.', 404, null));
    renderPage();

    expect(await screen.findByText('Appointment not found.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back to appointments' })).toHaveAttribute('href', '/patient/appointments');
  });
});
