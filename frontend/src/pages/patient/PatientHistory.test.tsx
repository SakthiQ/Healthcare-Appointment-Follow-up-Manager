import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../../api/client';
import type { HistoryItem } from '../../api/types';
import { expectNoA11yViolations } from '../../test/a11y';
import PatientHistory from './PatientHistory';

function visit(n: number, overrides: Partial<HistoryItem> = {}): HistoryItem {
  return {
    appointment_id: `a${n}`,
    start_time: `2030-0${n}-07T09:00:00Z`,
    doctor_name: `Dr Number ${n}`,
    doctor_specialization: 'Cardiology',
    doctor_timezone: 'UTC',
    medications: [{ name: 'Amoxicillin', dosage: '500mg', frequency: 'three times a day', duration_days: 5 }],
    instructions: 'Take after meals',
    follow_up_steps: 'Come back if the fever lasts',
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <PatientHistory />
    </MemoryRouter>,
  );
}

describe('PatientHistory', () => {
  it('lists each visit with its doctor, medication, instructions and follow-up, linking to the visit', async () => {
    const spy = vi.spyOn(api, 'getMyHistory').mockResolvedValue({
      items: [visit(2), visit(1, { medications: [], follow_up_steps: null, instructions: null })],
      total: 2,
    });
    renderPage();

    expect(await screen.findByText('Dr Number 2')).toBeInTheDocument();
    expect(spy).toHaveBeenCalledWith({ limit: 10, offset: 0 });
    expect(screen.getByText('Amoxicillin 500mg, three times a day, for 5 days')).toBeInTheDocument();
    expect(screen.getByText('Take after meals')).toBeInTheDocument();
    expect(screen.getByText('Come back if the fever lasts')).toBeInTheDocument();
    expect(screen.getByText('No medication prescribed.')).toBeInTheDocument();
    expect(screen.getByText('No follow-up summary for this visit.')).toBeInTheDocument();
    const links = screen.getAllByRole('link', { name: 'Open visit' });
    expect(links.map((l) => l.getAttribute('href'))).toEqual(['/patient/appointments/a2', '/patient/appointments/a1']);
  });

  it('pages through a long history', async () => {
    const spy = vi.spyOn(api, 'getMyHistory').mockImplementation(async ({ offset }) => ({
      items: offset === 0 ? Array.from({ length: 10 }, (_, i) => visit((i % 9) + 1, { appointment_id: `p${i}` })) : [visit(1, { appointment_id: 'last', doctor_name: 'Dr Last' })],
      total: 11,
    }));
    const user = userEvent.setup();
    renderPage();

    await screen.findAllByRole('link', { name: 'Open visit' });
    await user.click(screen.getByRole('button', { name: 'Next' }));

    expect(await screen.findByText('Dr Last')).toBeInTheDocument();
    expect(spy).toHaveBeenLastCalledWith({ limit: 10, offset: 10 });
  });

  it('says so when there are no completed visits yet', async () => {
    vi.spyOn(api, 'getMyHistory').mockResolvedValue({ items: [], total: 0 });
    renderPage();

    expect(await screen.findByText(/No completed visits yet/)).toBeInTheDocument();
  });

  it('shows the error when the history cannot be loaded', async () => {
    vi.spyOn(api, 'getMyHistory').mockRejectedValue(new ApiError('Could not load your history.', 500, null));
    renderPage();

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load your history.');
  });

  it('has no axe violations', async () => {
    vi.spyOn(api, 'getMyHistory').mockResolvedValue({ items: [visit(1)], total: 1 });
    renderPage();
    await screen.findByText('Dr Number 1');
    await expectNoA11yViolations(document.body);
  });
});
