import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../../api/client';
import type { FailedJob, FailedJobPage } from '../../api/types';
import FailedJobs from './FailedJobs';

function job(overrides: Partial<FailedJob> = {}): FailedJob {
  return {
    id: 'job-1',
    kind: 'notification',
    type: 'BOOKING_CONFIRMATION',
    status: 'FAILED',
    appointment_id: 'aaaaaaaa-1111-2222-3333-444444444444',
    attempts: 5,
    last_error: 'SMTP connection failed: timed out',
    updated_at: '2030-01-07T09:30:00Z',
    retryable: true,
    not_retryable_reason: null,
    ...overrides,
  };
}

function page(items: FailedJob[], total = items.length): FailedJobPage {
  return { items, total };
}

describe('FailedJobs', () => {
  it('lists failed emails with type, appointment, attempts, error and time', async () => {
    const spy = vi.spyOn(api, 'listFailedJobs').mockResolvedValue(page([job()]));
    render(<FailedJobs />);

    expect(await screen.findByText('BOOKING_CONFIRMATION')).toBeInTheDocument();
    expect(screen.getByText('aaaaaaaa')).toHaveAttribute('title', 'aaaaaaaa-1111-2222-3333-444444444444');
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.getByText('SMTP connection failed: timed out')).toBeInTheDocument();
    expect(screen.getByText('07 Jan 2030, 09:30 UTC')).toBeInTheDocument();
    expect(screen.getByText('1 failed email')).toBeInTheDocument();
    expect(spy).toHaveBeenCalledWith({ kind: 'notification', limit: 25, offset: 0 });
  });

  it('switches to the calendar tab and asks for calendar jobs', async () => {
    const spy = vi
      .spyOn(api, 'listFailedJobs')
      .mockResolvedValueOnce(page([job()]))
      .mockResolvedValueOnce(page([job({ id: 'cal-1', kind: 'calendar', type: 'CREATE (patient)' })]));
    render(<FailedJobs />);
    await screen.findByText('BOOKING_CONFIRMATION');

    await userEvent.setup().click(screen.getByRole('tab', { name: 'Calendar' }));

    expect(await screen.findByText('CREATE (patient)')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Calendar' })).toHaveAttribute('aria-selected', 'true');
    expect(spy).toHaveBeenLastCalledWith({ kind: 'calendar', limit: 25, offset: 0 });
  });

  it('retries a job, removes its row and says so', async () => {
    vi.spyOn(api, 'listFailedJobs').mockResolvedValue(page([job(), job({ id: 'job-2', type: 'APPOINTMENT_REMINDER' })]));
    const retry = vi.spyOn(api, 'retryFailedJob').mockResolvedValue(job({ status: 'PENDING' }));
    render(<FailedJobs />);
    await screen.findByText('BOOKING_CONFIRMATION');

    await userEvent.setup().click(screen.getByRole('button', { name: 'Retry BOOKING_CONFIRMATION' }));

    expect(retry).toHaveBeenCalledWith(expect.objectContaining({ id: 'job-1', kind: 'notification' }));
    expect(await screen.findByText(/BOOKING_CONFIRMATION email is back in the queue/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry BOOKING_CONFIRMATION' })).not.toBeInTheDocument();
    expect(screen.getByText('APPOINTMENT_REMINDER')).toBeInTheDocument();
    expect(screen.getByText('1 failed email')).toBeInTheDocument();
  });

  it('shows why a job cannot be retried instead of a button', async () => {
    vi.spyOn(api, 'listFailedJobs').mockResolvedValue(
      page([job({ type: 'PASSWORD_RESET', retryable: false, not_retryable_reason: 'It carried a one-time link.' })]),
    );
    render(<FailedJobs />);

    const row = (await screen.findByText('PASSWORD_RESET')).closest('tr')!;
    expect(within(row).getByText('It carried a one-time link.')).toBeInTheDocument();
    expect(within(row).queryByRole('button')).not.toBeInTheDocument();
  });

  it('shows the message from a 409 and reloads the list', async () => {
    const list = vi
      .spyOn(api, 'listFailedJobs')
      .mockResolvedValueOnce(page([job()]))
      .mockResolvedValueOnce(page([]));
    vi.spyOn(api, 'retryFailedJob').mockRejectedValue(
      new ApiError('This job is not FAILED any more.', 409, 'CONFLICT'),
    );
    render(<FailedJobs />);
    await screen.findByText('BOOKING_CONFIRMATION');

    await userEvent.setup().click(screen.getByRole('button', { name: 'Retry BOOKING_CONFIRMATION' }));

    expect(await screen.findByText('This job is not FAILED any more.')).toBeInTheDocument();
    expect(await screen.findByText('No failed emails.')).toBeInTheDocument();
    expect(list).toHaveBeenCalledTimes(2);
  });

  it('pages through the list using the total', async () => {
    const spy = vi.spyOn(api, 'listFailedJobs').mockResolvedValue(page([job()], 60));
    render(<FailedJobs />);
    await screen.findByText('BOOKING_CONFIRMATION');

    await userEvent.setup().click(screen.getByRole('button', { name: 'Next' }));

    await vi.waitFor(() => expect(spy).toHaveBeenLastCalledWith({ kind: 'notification', limit: 25, offset: 25 }));
  });
});
