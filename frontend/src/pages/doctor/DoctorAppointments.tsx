import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import type { AppointmentStatus } from '../../api/types';
import { useAsync } from '../../lib/useAsync';
import { formatDateTime } from '../../lib/format';
import { Card, EmptyState, ErrorBanner, Spinner, StatusBadge } from '../../components/ui';

const FILTERS: { label: string; value: AppointmentStatus | '' }[] = [
  { label: 'All', value: '' },
  { label: 'Confirmed', value: 'CONFIRMED' },
  { label: 'Rescheduled', value: 'RESCHEDULED' },
  { label: 'Conflicted', value: 'CONFLICTED' },
  { label: 'Completed', value: 'COMPLETED' },
  { label: 'Cancelled', value: 'CANCELLED' },
];

export default function DoctorAppointments() {
  const [filter, setFilter] = useState<AppointmentStatus | ''>('');
  const { data, loading, error, reload } = useAsync(
    () => api.listAppointments(filter ? { status: filter } : undefined),
    [filter],
  );

  const appointments = data ?? [];

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Appointments</h1>
          <p className="muted">Open an appointment to review symptoms and record your consultation.</p>
        </div>
      </header>

      <Card>
        <div className="filter-row" role="group" aria-label="Filter by status">
          {FILTERS.map((f) => (
            <button
              key={f.value || 'all'}
              type="button"
              className={filter === f.value ? 'pill active' : 'pill'}
              onClick={() => setFilter(f.value)}
            >
              {f.label}
            </button>
          ))}
        </div>
      </Card>

      <Card>
        {loading ? <Spinner /> : null}
        <ErrorBanner error={error} onRetry={reload} />
        {!loading && !error ? (
          appointments.length === 0 ? (
            <EmptyState>No appointments{filter ? ` with status ${filter}` : ''}.</EmptyState>
          ) : (
            <ul className="list">
              {appointments.map((appt) => (
                <li key={appt.id} className="list-row">
                  <div>
                    <strong>{formatDateTime(appt.start_time)}</strong>
                    <div className="muted small">Ends {formatDateTime(appt.end_time)}</div>
                  </div>
                  <div className="list-row-end">
                    <StatusBadge status={appt.status} />
                    <Link className="btn btn-sm" to={`/doctor/appointments/${appt.id}`}>
                      Open
                    </Link>
                  </div>
                </li>
              ))}
            </ul>
          )
        ) : null}
      </Card>
    </div>
  );
}
