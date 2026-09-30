import { api } from '../../api/client';
import { useAsync } from '../../lib/useAsync';
import { formatDateTime } from '../../lib/format';
import { Card, EmptyState, ErrorBanner, InfoBanner, Spinner, StatusBadge } from '../../components/ui';

export default function ConflictedAppointments() {
  const { data, loading, error, reload } = useAsync(
    () => api.listAppointments({ status: 'CONFLICTED' }),
    [],
  );

  const conflicts = data ?? [];

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Conflicted appointments</h1>
          <p className="muted">Appointments that clash with a doctor's leave.</p>
        </div>
      </header>

      <InfoBanner>
        These appointments were automatically flagged when leave was recorded. The original booking is
        preserved — nothing was deleted — and affected patients were notified so they can rebook.
      </InfoBanner>

      <Card title={`${conflicts.length} conflicted appointment(s)`}>
        {loading ? <Spinner /> : null}
        <ErrorBanner error={error} onRetry={reload} />
        {!loading && !error ? (
          conflicts.length === 0 ? (
            <EmptyState>No conflicted appointments. Everything is on track.</EmptyState>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Original time</th>
                  <th>Doctor</th>
                  <th>Patient</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {conflicts.map((appt) => (
                  <tr key={appt.id}>
                    <td>{formatDateTime(appt.start_time)}</td>
                    <td>{appt.doctor_name ?? '—'}</td>
                    <td>{appt.patient_name ?? <span className="mono small">{appt.patient_id}</span>}</td>
                    <td>
                      <StatusBadge status={appt.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        ) : null}
      </Card>
    </div>
  );
}
