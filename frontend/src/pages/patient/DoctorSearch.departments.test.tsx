import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../../api/client';
import DoctorSearch from './DoctorSearch';

// Only the department choices (#70). The page's other behaviour is covered by #42.

describe('DoctorSearch: departments', () => {
  it('offers departments before the results and filters by the chosen one', async () => {
    vi.spyOn(api, 'listDepartments').mockResolvedValue([
      { id: 'dp1', name: 'Cardiology', description: null, is_active: true, active_doctor_count: 2 },
      { id: 'dp2', name: 'Paediatrics', description: null, is_active: true, active_doctor_count: 1 },
    ]);
    const search = vi.spyOn(api, 'searchDoctors').mockResolvedValue([]);
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <DoctorSearch />
      </MemoryRouter>,
    );

    const cardio = await screen.findByRole('button', { name: 'Cardiology (2)' });
    expect(screen.getByRole('button', { name: 'All departments' })).toHaveAttribute('aria-pressed', 'true');
    await user.click(cardio);

    expect(cardio).toHaveAttribute('aria-pressed', 'true');
    expect(search).toHaveBeenLastCalledWith({ name: '', specialization: '', department_id: 'dp1' });
    await user.click(screen.getByRole('button', { name: 'All departments' }));
    expect(search).toHaveBeenLastCalledWith({ name: '', specialization: '', department_id: undefined });
  });

  it('shows no department choices when there are none', async () => {
    vi.spyOn(api, 'listDepartments').mockResolvedValue([]);
    vi.spyOn(api, 'searchDoctors').mockResolvedValue([]);
    render(
      <MemoryRouter>
        <DoctorSearch />
      </MemoryRouter>,
    );

    await screen.findByRole('heading', { name: 'Find a doctor' });
    expect(screen.queryByRole('button', { name: 'All departments' })).not.toBeInTheDocument();
  });
});
