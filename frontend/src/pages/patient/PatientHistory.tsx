import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { useAsync } from '../../lib/useAsync';
import { formatDateTime } from '../../lib/format';
import { Card, EmptyState, ErrorBanner, Pager, Spinner } from '../../components/ui';

const PAGE_SIZE = 10;

/** Every completed visit in one place: who you saw, what was prescribed, and what to do next. */
export default function PatientHistory() {
  const [page, setPage] = useState(0);
  const { data, loading, error, reload } = useAsync(
    () => api.getMyHistory({ limit: PAGE_SIZE, offset: page * PAGE_SIZE }),
    [page],
  );

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>My health history</h1>
          <p className="muted">Your completed visits, newest first, with what was prescribed.</p>
        </div>
      </header>

      {loading && !data ? <Spinner label="Loading your history…" /> : null}
      <ErrorBanner error={error} onRetry={reload} />

      {data && data.items.length === 0 ? (
        <EmptyState>No completed visits yet. They appear here after each consultation.</EmptyState>
      ) : null}

      {data?.items.map((visit) => (
        <Card
          key={visit.appointment_id}
          title={formatDateTime(visit.start_time, visit.doctor_timezone)}
          actions={
            <Link className="btn btn-sm" to={`/patient/appointments/${visit.appointment_id}`}>
              Open visit
            </Link>
          }
        >
          <p>
            <strong>{visit.doctor_name ?? 'Your doctor'}</strong>
            {visit.doctor_specialization ? ` · ${visit.doctor_specialization}` : ''}
          </p>
          <h3>Medication</h3>
          {visit.medications.length === 0 ? (
            <p className="muted">No medication prescribed.</p>
          ) : (
            <ul>
              {visit.medications.map((m, i) => (
                <li key={i}>
                  {m.name} {m.dosage}, {m.frequency}
                  {m.duration_days ? `, for ${m.duration_days} days` : ''}
                </li>
              ))}
            </ul>
          )}
          {visit.instructions ? <p className="prewrap">{visit.instructions}</p> : null}
          <h3>Follow-up</h3>
          <p className={visit.follow_up_steps ? 'prewrap' : 'muted'}>
            {visit.follow_up_steps ?? 'No follow-up summary for this visit.'}
          </p>
        </Card>
      ))}

      {data ? <Pager page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} /> : null}
    </div>
  );
}
