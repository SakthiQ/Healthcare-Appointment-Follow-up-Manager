import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../api/client';
import type { AISummary } from '../api/types';
import { expectNoA11yViolations } from '../test/a11y';
import { PreviousVisitsCard } from './PreviousVisitsCard';

const notFound = () => new ApiError('Not found', 404, null);

function summary(overrides: Partial<AISummary> = {}): AISummary {
  return {
    id: 's1', appointment_id: 'a1', type: 'HISTORY', status: 'SUCCESS', error_message: null,
    created_at: '2030-01-01T00:00:00Z',
    payload: {
      recent_visits: [
        { date: '2029-12-01', complaint: 'Persistent cough', medications: ['Amoxicillin 500mg, twice daily'] },
        { date: '2029-10-15', complaint: 'Migraine', medications: [] },
      ],
      recurring_issues: ['Headaches at two visits'],
      notes_for_doctor: 'Two previous visits.',
    },
    ...overrides,
  };
}

describe('PreviousVisitsCard', () => {
  it('generates a summary on demand and shows it with the AI note', async () => {
    vi.spyOn(api, 'getHistorySummary').mockRejectedValueOnce(notFound()).mockResolvedValue(summary());
    const generate = vi.spyOn(api, 'generateHistorySummary').mockResolvedValue(summary());
    const user = userEvent.setup();
    const { container } = render(<PreviousVisitsCard appointmentId="a1" />);

    expect(await screen.findByText(/Generate a summary of the patient's earlier visits/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Generate' }));

    expect(generate).toHaveBeenCalledWith('a1');
    expect(await screen.findByText('Persistent cough')).toBeInTheDocument();
    expect(screen.getByText(/01 Dec 2029/)).toBeInTheDocument();
    expect(screen.getByText('Amoxicillin 500mg, twice daily')).toBeInTheDocument();
    expect(screen.getByText('Headaches at two visits')).toBeInTheDocument();
    expect(screen.getByText('Two previous visits.')).toBeInTheDocument();
    expect(screen.getByText(/AI-generated .* check the records/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Regenerate' })).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it('says so when the patient has no earlier visits', async () => {
    vi.spyOn(api, 'getHistorySummary').mockResolvedValue(summary({
      payload: { recent_visits: [], recurring_issues: [], notes_for_doctor: 'No previous completed visits with this clinic.' },
    }));
    render(<PreviousVisitsCard appointmentId="a1" />);

    expect(await screen.findByText('No previous completed visits with this clinic.')).toBeInTheDocument();
    expect(screen.queryByText('Recurring')).not.toBeInTheDocument();
  });

  it('shows why the last attempt failed and lets the doctor retry', async () => {
    vi.spyOn(api, 'getHistorySummary').mockResolvedValue(summary({
      status: 'FAILED', payload: null, error_message: 'Invalid AI response schema',
    }));
    render(<PreviousVisitsCard appointmentId="a1" />);

    expect(await screen.findByText(/The last attempt failed: Invalid AI response schema/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Generate' })).toBeEnabled();
  });

  it('shows an error when generating is refused, such as by the rate limit', async () => {
    vi.spyOn(api, 'getHistorySummary').mockRejectedValue(notFound());
    vi.spyOn(api, 'generateHistorySummary').mockRejectedValue(
      new ApiError('Too many requests. Try again later.', 429, null),
    );
    const user = userEvent.setup();
    render(<PreviousVisitsCard appointmentId="a1" />);

    await user.click(await screen.findByRole('button', { name: 'Generate' }));

    expect(await screen.findByText(/Too many requests/)).toBeInTheDocument();
  });
});
