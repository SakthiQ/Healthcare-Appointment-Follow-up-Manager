import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../../api/client';
import type { Doctor, DoctorLeave, WorkingHours } from '../../api/types';
import { DAY_NAMES } from '../../lib/format';
import DoctorConfig from './DoctorConfig';

function doctor(overrides: Partial<Doctor> = {}): Doctor {
  return {
    id: 'd1',
    user_id: 'u1',
    email: 'ada@clinic.example.com',
    full_name: 'Dr Ada',
    specialization: 'Cardiology',
    slot_duration_minutes: 30,
    timezone: 'UTC',
    is_active: true,
    created_at: '2030-01-01T00:00:00Z',
    ...overrides,
  };
}

const monday: WorkingHours = {
  id: 'wh1', doctor_id: 'd1', day_of_week: 0, start_time: '09:00:00', end_time: '13:00:00', is_active: true,
};

const leave: DoctorLeave = {
  id: 'l1', doctor_id: 'd1', leave_date: '2030-02-14', reason: 'Conference', created_at: '2030-01-01T00:00:00Z',
};

function mockReads(doc = doctor()) {
  vi.spyOn(api, 'adminListDepartments').mockResolvedValue([]);
  vi.spyOn(api, 'getDoctor').mockResolvedValue(doc);
  vi.spyOn(api, 'getDoctorSchedule').mockResolvedValue([monday]);
  vi.spyOn(api, 'getDoctorLeaves').mockResolvedValue([leave]);
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/admin/doctors/d1']}>
      <Routes>
        <Route path="/admin/doctors/:doctorId" element={<DoctorConfig />} />
      </Routes>
    </MemoryRouter>,
  );
}

/** Render and wait until the profile, hours and leave have loaded and filled the forms, so a
 * test's typing is never overwritten by the page filling a form from data that arrived late. */
async function renderLoaded() {
  renderPage();
  await waitFor(() => expect(screen.getByLabelText('Specialisation')).toHaveValue('Cardiology'));
  await waitFor(() => expect(screen.getByLabelText(`${DAY_NAMES[0]} start time`)).toHaveValue('09:00'));
  await screen.findByText('Conference');
}

const CONFLICT_NOTICE = /appointments .*marked conflicted and (those|the) patients notified/;

describe('DoctorConfig', () => {
  beforeEach(() => mockReads());

  it('loads the profile, working hours and leave for the doctor in the route', async () => {
    renderPage();

    expect(await screen.findByRole('heading', { name: 'Dr Ada' })).toBeInTheDocument();
    expect(api.getDoctor).toHaveBeenCalledWith('d1');
    // The form is filled from the loaded doctor one render after the heading appears.
    await waitFor(() => expect(screen.getByLabelText('Specialisation')).toHaveValue('Cardiology'));
    expect(screen.getByLabelText('Slot duration (minutes)')).toHaveValue(30);
    expect(screen.getByText('Active')).toBeInTheDocument();

    expect(await screen.findByLabelText(`${DAY_NAMES[0]} start time`)).toHaveValue('09:00');
    expect(screen.getByLabelText(`${DAY_NAMES[0]} end time`)).toHaveValue('13:00');
    expect(screen.getByRole('checkbox', { name: DAY_NAMES[0] })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: DAY_NAMES[1] })).not.toBeChecked();

    expect(await screen.findByText('Conference')).toBeInTheDocument();
  });

  it('saves the profile with the edited values', async () => {
    const update = vi.spyOn(api, 'updateDoctor').mockResolvedValue(doctor({ specialization: 'Neurology' }));
    const user = userEvent.setup();
    await renderLoaded();

    const spec = await screen.findByLabelText('Specialisation');
    await user.clear(spec);
    await user.type(spec, '  Neurology ');
    const slot = screen.getByLabelText('Slot duration (minutes)');
    await user.clear(slot);
    await user.type(slot, '45');
    await user.click(screen.getByRole('button', { name: 'Save profile' }));

    expect(update).toHaveBeenCalledWith('d1', { specialization: 'Neurology', slot_duration_minutes: 45, timezone: 'UTC' });
    expect(await screen.findByText('Profile updated.')).toBeInTheDocument();
  });

  it('refuses an invalid profile without calling the API', async () => {
    const update = vi.spyOn(api, 'updateDoctor');
    const user = userEvent.setup();
    await renderLoaded();

    const slot = await screen.findByLabelText('Slot duration (minutes)');
    await user.clear(slot);
    await user.type(slot, '2');
    await user.click(screen.getByRole('button', { name: 'Save profile' }));

    expect(screen.getByText('Slot duration must be between 5 and 240 minutes.')).toBeInTheDocument();
    expect(update).not.toHaveBeenCalled();
  });

  it('deactivates after confirmation and says the appointments were marked conflicted', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const setStatus = vi.spyOn(api, 'setDoctorStatus').mockResolvedValue(doctor({ is_active: false }));
    const user = userEvent.setup();
    await renderLoaded();

    await user.click(await screen.findByRole('button', { name: 'Deactivate' }));

    expect(window.confirm).toHaveBeenCalled();
    expect(setStatus).toHaveBeenCalledWith('d1', false);
    expect(await screen.findByText(CONFLICT_NOTICE)).toBeInTheDocument();
  });

  it('does not deactivate when the admin backs out', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    const setStatus = vi.spyOn(api, 'setDoctorStatus');
    const user = userEvent.setup();
    await renderLoaded();

    await user.click(await screen.findByRole('button', { name: 'Deactivate' }));

    expect(setStatus).not.toHaveBeenCalled();
  });

  it('activates an inactive doctor without asking', async () => {
    mockReads(doctor({ is_active: false }));
    const confirm = vi.spyOn(window, 'confirm');
    const setStatus = vi.spyOn(api, 'setDoctorStatus').mockResolvedValue(doctor());
    const user = userEvent.setup();
    await renderLoaded();

    await user.click(await screen.findByRole('button', { name: 'Activate' }));

    expect(confirm).not.toHaveBeenCalled();
    expect(setStatus).toHaveBeenCalledWith('d1', true);
    expect(await screen.findByText(/Doctor activated/)).toBeInTheDocument();
  });

  it('saves only the ticked days, with the times entered', async () => {
    const save = vi.spyOn(api, 'configureWorkingHours').mockResolvedValue([]);
    const user = userEvent.setup();
    await renderLoaded();

    await user.click(await screen.findByRole('checkbox', { name: DAY_NAMES[2] }));
    const start = screen.getByLabelText(`${DAY_NAMES[2]} start time`);
    const end = screen.getByLabelText(`${DAY_NAMES[2]} end time`);
    await user.clear(start);
    await user.type(start, '10:30');
    await user.clear(end);
    await user.type(end, '15:00');
    await user.click(screen.getByRole('button', { name: 'Save working hours' }));

    expect(save).toHaveBeenCalledWith('d1', [
      { day_of_week: 0, start_time: '09:00:00', end_time: '13:00:00', is_active: true },
      { day_of_week: 2, start_time: '10:30:00', end_time: '15:00:00', is_active: true },
    ]);
    expect(await screen.findByText('Working hours saved.')).toBeInTheDocument();
  });

  it('refuses a day that ends before it starts', async () => {
    const save = vi.spyOn(api, 'configureWorkingHours');
    const user = userEvent.setup();
    await renderLoaded();

    const end = await screen.findByLabelText(`${DAY_NAMES[0]} end time`);
    await user.clear(end);
    await user.type(end, '08:00');
    await user.click(screen.getByRole('button', { name: 'Save working hours' }));

    expect(screen.getByText('End time must be after start time.')).toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });

  it('adds leave and says the appointments that day were marked conflicted', async () => {
    const create = vi.spyOn(api, 'createLeave').mockResolvedValue(leave);
    const user = userEvent.setup();
    await renderLoaded();

    const date = await screen.findByLabelText('Leave date');
    await user.clear(date);
    await user.type(date, '2030-03-02');
    await user.type(screen.getByLabelText('Reason (optional)'), ' Training ');
    await user.click(screen.getByRole('button', { name: 'Add leave date' }));

    expect(create).toHaveBeenCalledWith('d1', { leave_date: '2030-03-02', reason: 'Training' });
    expect(await screen.findByText(CONFLICT_NOTICE)).toBeInTheDocument();
  });

  it('shows the error when the leave already exists', async () => {
    vi.spyOn(api, 'createLeave').mockRejectedValue(new ApiError('Leave already exists for this date.', 409, null));
    const user = userEvent.setup();
    await renderLoaded();

    await user.click(await screen.findByRole('button', { name: 'Add leave date' }));

    expect(await screen.findByText('Leave already exists for this date.')).toBeInTheDocument();
  });

  it('removes leave only after confirmation', async () => {
    const del = vi.spyOn(api, 'deleteLeave').mockResolvedValue(undefined);
    const user = userEvent.setup();
    await renderLoaded();

    await user.click(await screen.findByRole('button', { name: 'Remove' }));
    expect(del).not.toHaveBeenCalled();
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove leave' }));

    expect(del).toHaveBeenCalledWith('d1', 'l1');
    expect(await screen.findByText('Leave removed.')).toBeInTheDocument();
  });

  it('shows the error and a way back when the doctor cannot be loaded', async () => {
    vi.mocked(api.getDoctor).mockRejectedValue(new ApiError('Doctor not found.', 404, null));
    renderPage();

    expect(await screen.findByText('Doctor not found.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back' })).toHaveAttribute('href', '/admin/doctors');
  });
});
