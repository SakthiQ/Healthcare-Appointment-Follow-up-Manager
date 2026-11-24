import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../../api/client';
import type { Doctor } from '../../api/types';
import DoctorManagement from './DoctorManagement';

function doctor(overrides: Partial<Doctor> = {}): Doctor {
  return {
    id: 'd1',
    user_id: 'u1',
    email: 'ada@clinic.example.com',
    full_name: 'Dr Ada',
    specialization: 'Cardiology',
    slot_duration_minutes: 30,
    timezone: 'Asia/Kolkata',
    is_active: true,
    created_at: '2030-01-01T00:00:00Z',
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <DoctorManagement />
    </MemoryRouter>,
  );
}

async function fillForm(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Add doctor' }));
  await user.type(screen.getByLabelText('Full name'), '  Dr New  ');
  await user.type(screen.getByLabelText('Specialisation'), 'Neurology');
  await user.type(screen.getByLabelText('Email'), 'new@clinic.example.com');
  await user.type(screen.getByLabelText('Temporary password'), 'temporary-pass-1');
  const slot = screen.getByLabelText('Slot duration (minutes)');
  await user.clear(slot);
  await user.type(slot, '20');
  const tz = screen.getByLabelText('Timezone');
  await user.clear(tz);
  await user.type(tz, 'Asia/Kolkata');
}

describe('DoctorManagement', () => {
  it('lists active and inactive doctors, each linking to its configuration page', async () => {
    const search = vi.spyOn(api, 'searchDoctors').mockResolvedValue([
      doctor(),
      doctor({ id: 'd2', full_name: 'Dr Bo', specialization: 'Paediatrics', is_active: false, email: 'bo@clinic.example.com' }),
    ]);
    renderPage();

    expect(await screen.findByText('Dr Ada')).toBeInTheDocument();
    expect(search).toHaveBeenCalledWith();
    const rows = screen.getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText('Cardiology · 30 min · ada@clinic.example.com')).toBeInTheDocument();
    expect(within(rows[0]).getByText('Active')).toBeInTheDocument();
    expect(within(rows[0]).getByRole('link', { name: 'Configure' })).toHaveAttribute('href', '/admin/doctors/d1');
    expect(within(rows[1]).getByText('Inactive')).toBeInTheDocument();
    expect(within(rows[1]).getByRole('link', { name: 'Configure' })).toHaveAttribute('href', '/admin/doctors/d2');
  });

  it('says so when there are no doctors yet', async () => {
    vi.spyOn(api, 'searchDoctors').mockResolvedValue([]);
    renderPage();

    expect(await screen.findByText(/No doctors yet/)).toBeInTheDocument();
  });

  it('shows the error when the list cannot be loaded', async () => {
    vi.spyOn(api, 'searchDoctors').mockRejectedValue(new ApiError('Could not load doctors.', 500, null));
    renderPage();

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load doctors.');
  });

  it('creates a doctor with the entered values and shows them in the list', async () => {
    const search = vi.spyOn(api, 'searchDoctors').mockResolvedValue([doctor()]);
    const create = vi.spyOn(api, 'createDoctor').mockResolvedValue(
      doctor({ id: 'd9', full_name: 'Dr New', specialization: 'Neurology' }),
    );
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('Dr Ada');

    search.mockResolvedValue([doctor(), doctor({ id: 'd9', full_name: 'Dr New', specialization: 'Neurology' })]);
    await fillForm(user);
    await user.click(screen.getByRole('button', { name: 'Create doctor' }));

    expect(create).toHaveBeenCalledWith({
      email: 'new@clinic.example.com',
      password: 'temporary-pass-1',
      full_name: 'Dr New',
      specialization: 'Neurology',
      slot_duration_minutes: 20,
      timezone: 'Asia/Kolkata',
    });
    expect(await screen.findByText('Created Dr New. Configure their working hours next.')).toBeInTheDocument();
    expect(await screen.findByText('Dr New')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Create doctor' })).not.toBeInTheDocument();
  });

  it('checks the form before sending anything', async () => {
    vi.spyOn(api, 'searchDoctors').mockResolvedValue([]);
    const create = vi.spyOn(api, 'createDoctor');
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/No doctors yet/);

    await user.click(screen.getByRole('button', { name: 'Add doctor' }));
    await user.type(screen.getByLabelText('Email'), 'not-an-email');
    await user.click(screen.getByRole('button', { name: 'Create doctor' }));

    expect(screen.getByText('Full name is required.')).toBeInTheDocument();
    expect(screen.getByText('Enter a valid email address.')).toBeInTheDocument();
    expect(screen.getByText(/Password must be at least/)).toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();
  });

  it('shows the error and keeps the form when the email is already used', async () => {
    vi.spyOn(api, 'searchDoctors').mockResolvedValue([doctor()]);
    vi.spyOn(api, 'createDoctor').mockRejectedValue(
      new ApiError('A user with this email already exists.', 409, null),
    );
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('Dr Ada');

    await fillForm(user);
    await user.click(screen.getByRole('button', { name: 'Create doctor' }));

    expect(await screen.findByText('A user with this email already exists.')).toBeInTheDocument();
    expect(screen.getByLabelText('Email')).toHaveValue('new@clinic.example.com');
    expect(screen.getByRole('button', { name: 'Create doctor' })).toBeEnabled();
  });
});
