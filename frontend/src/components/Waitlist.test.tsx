import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../api/client';
import type { WaitlistEntry } from '../api/types';
import { JoinWaitlistButton, MyWaitlist } from './Waitlist';

function entry(overrides: Partial<WaitlistEntry> = {}): WaitlistEntry {
  return {
    id: 'w1', doctor_id: 'd1', date: '2030-01-07', created_at: '2030-01-01T00:00:00Z', notified_at: null,
    doctor_name: 'Dr Ada', doctor_specialization: 'Cardiology', ...overrides,
  };
}

describe('JoinWaitlistButton', () => {
  it('joins the waitlist for the chosen doctor and day', async () => {
    const join = vi.spyOn(api, 'joinWaitlist').mockResolvedValue(entry());
    const user = userEvent.setup();
    render(<JoinWaitlistButton doctorId="d1" date="2030-01-07" />);

    await user.click(screen.getByRole('button', { name: 'Join waitlist for this day' }));

    expect(join).toHaveBeenCalledWith('d1', '2030-01-07');
    expect(await screen.findByText(/You are on the waitlist/)).toBeInTheDocument();
  });

  it('shows why joining was refused', async () => {
    vi.spyOn(api, 'joinWaitlist').mockRejectedValue(new ApiError('You are already on the waitlist for that day.', 409, null));
    const user = userEvent.setup();
    render(<JoinWaitlistButton doctorId="d1" date="2030-01-07" />);

    await user.click(screen.getByRole('button', { name: 'Join waitlist for this day' }));

    expect(await screen.findByText('You are already on the waitlist for that day.')).toBeInTheDocument();
  });
});

describe('MyWaitlist', () => {
  it('lists waitlists, offers Book once a slot opened, and leaves one', async () => {
    vi.spyOn(api, 'getMyWaitlist').mockResolvedValue([
      entry(),
      entry({ id: 'w2', doctor_id: 'd2', date: '2030-01-08', doctor_name: 'Dr Bo', notified_at: '2030-01-02T00:00:00Z' }),
    ]);
    const leave = vi.spyOn(api, 'leaveWaitlist').mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <MyWaitlist />
      </MemoryRouter>,
    );

    const rows = await screen.findAllByRole('listitem');
    expect(within(rows[0]).getByText('Waiting for a slot to open.')).toBeInTheDocument();
    expect(within(rows[0]).queryByRole('link', { name: 'Book' })).not.toBeInTheDocument();
    expect(within(rows[1]).getByText(/A slot opened up/)).toBeInTheDocument();
    expect(within(rows[1]).getByRole('link', { name: 'Book' })).toHaveAttribute('href', '/patient/doctors/d2');

    await user.click(within(rows[0]).getByRole('button', { name: 'Leave' }));
    expect(leave).toHaveBeenCalledWith('d1', '2030-01-07');
  });

  it('shows nothing when the patient is on no waitlist', async () => {
    vi.spyOn(api, 'getMyWaitlist').mockResolvedValue([]);
    const { container } = render(
      <MemoryRouter>
        <MyWaitlist />
      </MemoryRouter>,
    );

    await vi.waitFor(() => expect(api.getMyWaitlist).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
