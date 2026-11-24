import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../../api/client';
import type { Doctor } from '../../api/types';
import * as download from '../../lib/download';
import ExportAppointments from './ExportAppointments';

const doctors: Doctor[] = [
  { id: 'd1', user_id: 'u1', email: null, full_name: 'Dr Ada', specialization: 'Cardiology',
    slot_duration_minutes: 30, timezone: 'UTC', is_active: true, created_at: '2030-01-01T00:00:00Z' },
];

describe('ExportAppointments', () => {
  it('exports everything when no filter is chosen, and saves the CSV', async () => {
    const exp = vi.spyOn(api, 'exportAppointmentsCsv').mockResolvedValue('appointment_id\r\na1\r\n');
    const save = vi.spyOn(download, 'saveTextFile').mockImplementation(() => {});
    const user = userEvent.setup();
    render(<ExportAppointments doctors={doctors} />);

    await user.click(screen.getByRole('button', { name: 'Export CSV' }));

    expect(exp).toHaveBeenCalledWith({ status: undefined, doctor_id: undefined, from: undefined, until: undefined });
    expect(save).toHaveBeenCalledWith(expect.stringMatching(/^appointments-\d{4}-\d{2}-\d{2}\.csv$/),
      'appointment_id\r\na1\r\n', 'text/csv;charset=utf-8');
  });

  it('sends the chosen filters, counting the until date inclusively', async () => {
    const exp = vi.spyOn(api, 'exportAppointmentsCsv').mockResolvedValue('');
    vi.spyOn(download, 'saveTextFile').mockImplementation(() => {});
    const user = userEvent.setup();
    render(<ExportAppointments doctors={doctors} />);

    await user.selectOptions(screen.getByLabelText('Status'), 'CANCELLED');
    await user.selectOptions(screen.getByLabelText('Doctor'), 'd1');
    await user.type(screen.getByLabelText('From (UTC date)'), '2030-01-01');
    await user.type(screen.getByLabelText('Until (UTC date, inclusive)'), '2030-01-31');
    await user.click(screen.getByRole('button', { name: 'Export CSV' }));

    expect(exp).toHaveBeenCalledWith({
      status: 'CANCELLED', doctor_id: 'd1', from: '2030-01-01T00:00:00Z', until: '2030-02-01T00:00:00Z',
    });
  });

  it('shows the error when the export is too large', async () => {
    vi.spyOn(api, 'exportAppointmentsCsv').mockRejectedValue(
      new ApiError('More than 10,000 appointments match. Narrow the date range or filters and export again.', 400, 'EXPORT_TOO_LARGE'),
    );
    const save = vi.spyOn(download, 'saveTextFile');
    const user = userEvent.setup();
    render(<ExportAppointments doctors={doctors} />);

    await user.click(screen.getByRole('button', { name: 'Export CSV' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Narrow the date range');
    expect(save).not.toHaveBeenCalled();
  });
});
