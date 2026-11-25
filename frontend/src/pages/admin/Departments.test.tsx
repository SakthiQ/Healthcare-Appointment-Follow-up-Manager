import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../../api/client';
import type { Department } from '../../api/types';
import Departments from './Departments';

function dept(overrides: Partial<Department> = {}): Department {
  return { id: 'dp1', name: 'Cardiology', description: 'Heart care', is_active: true, active_doctor_count: 3, ...overrides };
}

describe('Departments', () => {
  it('lists every department with its doctor count and status', async () => {
    vi.spyOn(api, 'adminListDepartments').mockResolvedValue([
      dept(),
      dept({ id: 'dp2', name: 'Closed Ward', description: null, is_active: false, active_doctor_count: 0 }),
    ]);
    render(<Departments />);

    expect(await screen.findByText('Cardiology')).toBeInTheDocument();
    const rows = screen.getAllByRole('listitem');
    expect(within(rows[0]).getByText('3 active doctor(s) · Heart care')).toBeInTheDocument();
    expect(within(rows[0]).getByText('Active')).toBeInTheDocument();
    expect(within(rows[1]).getByText('Deactivated')).toBeInTheDocument();
    expect(within(rows[1]).getByRole('button', { name: 'Reactivate' })).toBeInTheDocument();
  });

  it('creates a department with the trimmed name', async () => {
    vi.spyOn(api, 'adminListDepartments').mockResolvedValue([]);
    const create = vi.spyOn(api, 'createDepartment').mockResolvedValue(dept({ id: 'new', name: 'Neurology' }));
    const user = userEvent.setup();
    render(<Departments />);

    await screen.findByText(/No departments yet/);
    await user.type(screen.getByLabelText('Name'), '  Neurology ');
    await user.click(screen.getByRole('button', { name: 'Create department' }));

    expect(create).toHaveBeenCalledWith({ name: 'Neurology', description: null });
    expect(await screen.findByText('Created Neurology.')).toBeInTheDocument();
  });

  it('shows the error when the name is already taken', async () => {
    vi.spyOn(api, 'adminListDepartments').mockResolvedValue([dept()]);
    vi.spyOn(api, 'createDepartment').mockRejectedValue(new ApiError("A department called 'cardiology' already exists.", 409, null));
    const user = userEvent.setup();
    render(<Departments />);

    await screen.findByText('Cardiology');
    await user.type(screen.getByLabelText('Name'), 'cardiology');
    await user.click(screen.getByRole('button', { name: 'Create department' }));

    expect(await screen.findByText(/already exists/)).toBeInTheDocument();
  });

  it('renames a department', async () => {
    vi.spyOn(api, 'adminListDepartments').mockResolvedValue([dept()]);
    const update = vi.spyOn(api, 'updateDepartment').mockResolvedValue(dept({ name: 'Cardiac Care' }));
    const user = userEvent.setup();
    render(<Departments />);

    await user.click(await screen.findByRole('button', { name: 'Rename' }));
    const input = screen.getByLabelText('New name for Cardiology');
    await user.clear(input);
    await user.type(input, 'Cardiac Care');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(update).toHaveBeenCalledWith('dp1', { name: 'Cardiac Care' });
    expect(await screen.findByText('Renamed to Cardiac Care.')).toBeInTheDocument();
  });

  it('deactivates a department', async () => {
    vi.spyOn(api, 'adminListDepartments').mockResolvedValue([dept()]);
    const update = vi.spyOn(api, 'updateDepartment').mockResolvedValue(dept({ is_active: false }));
    const user = userEvent.setup();
    render(<Departments />);

    await user.click(await screen.findByRole('button', { name: 'Deactivate' }));

    expect(update).toHaveBeenCalledWith('dp1', { is_active: false });
    expect(await screen.findByText(/Patients no longer see it/)).toBeInTheDocument();
  });
});
