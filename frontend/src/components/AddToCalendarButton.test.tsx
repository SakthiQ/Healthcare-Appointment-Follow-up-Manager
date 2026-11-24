import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../api/client';
import * as download from '../lib/download';
import { AddToCalendarButton } from './AddToCalendarButton';

describe('AddToCalendarButton', () => {
  it('fetches the appointment calendar file and saves it as an .ics file', async () => {
    const get = vi.spyOn(api, 'getAppointmentCalendar').mockResolvedValue('BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n');
    const save = vi.spyOn(download, 'saveTextFile').mockImplementation(() => {});
    const user = userEvent.setup();
    render(<AddToCalendarButton appointmentId="a1" />);

    await user.click(screen.getByRole('button', { name: 'Add to calendar' }));

    expect(get).toHaveBeenCalledWith('a1');
    expect(save).toHaveBeenCalledWith('appointment-a1.ics', 'BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n', 'text/calendar;charset=utf-8');
    expect(screen.getByRole('button', { name: 'Add to calendar' })).toBeEnabled();
  });

  it('shows the error when the file cannot be fetched', async () => {
    vi.spyOn(api, 'getAppointmentCalendar').mockRejectedValue(new ApiError('Not authorized to access this appointment.', 403, null));
    const save = vi.spyOn(download, 'saveTextFile');
    const user = userEvent.setup();
    render(<AddToCalendarButton appointmentId="a1" />);

    await user.click(screen.getByRole('button', { name: 'Add to calendar' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Not authorized to access this appointment.');
    expect(save).not.toHaveBeenCalled();
  });
});

describe('saveTextFile', () => {
  it('clicks a temporary download link for a blob and cleans up', () => {
    const create = vi.fn(() => 'blob:fake');
    const revoke = vi.fn();
    vi.stubGlobal('URL', { ...URL, createObjectURL: create, revokeObjectURL: revoke });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    download.saveTextFile('appointment-a1.ics', 'X', 'text/calendar');

    expect(create).toHaveBeenCalledWith(expect.any(Blob));
    expect(click).toHaveBeenCalledTimes(1);
    expect(revoke).toHaveBeenCalledWith('blob:fake');
    expect(document.querySelector('a[download]')).toBeNull();
  });
});
