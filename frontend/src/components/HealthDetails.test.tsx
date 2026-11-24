import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../api/client';
import { HealthDetails } from './HealthDetails';
import { PatientHealthCard } from './PatientHealthCard';

describe('HealthDetails', () => {
  it('loads the saved details, says who can see them, and saves edits', async () => {
    vi.spyOn(api, 'getMyProfile').mockResolvedValue({ date_of_birth: '1990-05-17', phone: null, allergies: 'Penicillin' });
    const save = vi.spyOn(api, 'updateMyProfile').mockResolvedValue({ date_of_birth: '1990-05-17', phone: '12345', allergies: 'Penicillin, peanuts' });
    const user = userEvent.setup();
    render(<HealthDetails />);

    await waitFor(() => expect(screen.getByLabelText('Known allergies')).toHaveValue('Penicillin'));
    expect(screen.getByText(/Only the doctor of each of your appointments/)).toBeInTheDocument();
    await user.type(screen.getByLabelText('Phone'), ' 12345 ');
    await user.type(screen.getByLabelText('Known allergies'), ', peanuts');
    await user.click(screen.getByRole('button', { name: 'Save health details' }));

    expect(save).toHaveBeenCalledWith({ date_of_birth: '1990-05-17', phone: '12345', allergies: 'Penicillin, peanuts' });
    expect(await screen.findByText('Health details saved.')).toBeInTheDocument();
  });

  it('shows the error when saving is refused', async () => {
    vi.spyOn(api, 'getMyProfile').mockResolvedValue({ date_of_birth: null, phone: null, allergies: null });
    vi.spyOn(api, 'updateMyProfile').mockRejectedValue(new ApiError('Date of birth cannot be in the future.', 422, null));
    const user = userEvent.setup();
    render(<HealthDetails />);

    await user.click(await screen.findByRole('button', { name: 'Save health details' }));

    expect(await screen.findByText('Date of birth cannot be in the future.')).toBeInTheDocument();
  });
});

describe('PatientHealthCard', () => {
  it('shows allergies prominently and the age', async () => {
    const spy = vi.spyOn(api, 'getPatientHealth').mockResolvedValue({ age: 36, allergies: 'Penicillin' });
    render(<PatientHealthCard appointmentId="a1" />);

    expect(await screen.findByText('Penicillin')).toBeInTheDocument();
    expect(spy).toHaveBeenCalledWith('a1');
    expect(screen.getByText('36')).toBeInTheDocument();
  });

  it('says None recorded when there are no allergies', async () => {
    vi.spyOn(api, 'getPatientHealth').mockResolvedValue({ age: null, allergies: null });
    render(<PatientHealthCard appointmentId="a1" />);

    expect(await screen.findByText('None recorded')).toBeInTheDocument();
    expect(screen.getByText('Not recorded')).toBeInTheDocument();
  });
});
