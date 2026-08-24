import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';
import { useAsync } from '../../lib/useAsync';
import { Card, ErrorBanner, Spinner } from '../../components/ui';

export default function AdminDashboard() {
  const { user } = useAuth();
  const doctorsQuery = useAsync(() => api.searchDoctors(), []);
  const conflictsQuery = useAsync(() => api.listAppointments({ status: 'CONFLICTED' }), []);
  const allQuery = useAsync(() => api.listAppointments(), []);

  const doctors = doctorsQuery.data ?? [];
  const conflicts = conflictsQuery.data ?? [];
  const all = allQuery.data ?? [];

  const loading = doctorsQuery.loading || conflictsQuery.loading || allQuery.loading;
  const error = doctorsQuery.error ?? conflictsQuery.error ?? allQuery.error;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Administration</h1>
          <p className="muted">Signed in as {user?.full_name}</p>
        </div>
        <Link to="/admin/doctors" className="btn btn-primary">
          Manage doctors
        </Link>
      </header>

      {loading ? <Spinner /> : null}
      <ErrorBanner
        error={error}
        onRetry={() => {
          doctorsQuery.reload();
          conflictsQuery.reload();
          allQuery.reload();
        }}
      />

      {!loading && !error ? (
        <>
          <div className="stat-row">
            <div className="stat">
              <span className="stat-value">{doctors.length}</span>
              <span className="stat-label">Active doctors</span>
            </div>
            <div className="stat">
              <span className="stat-value">{all.length}</span>
              <span className="stat-label">Appointments</span>
            </div>
            <div className={conflicts.length > 0 ? 'stat stat-danger' : 'stat'}>
              <span className="stat-value">{conflicts.length}</span>
              <span className="stat-label">Conflicted</span>
            </div>
          </div>

          {conflicts.length > 0 ? (
            <div className="banner banner-danger" role="alert">
              <div>
                <strong>{conflicts.length} appointment(s) need attention</strong>
                <div>These clash with doctor leave. Affected patients have been notified.</div>
              </div>
              <Link className="btn btn-sm" to="/admin/conflicts">
                Review
              </Link>
            </div>
          ) : null}

          <Card title="Doctors">
            {doctors.length === 0 ? (
              <p className="empty">
                No doctors yet. <Link to="/admin/doctors">Add the first one</Link>.
              </p>
            ) : (
              <ul className="list">
                {doctors.slice(0, 6).map((doc) => (
                  <li key={doc.id} className="list-row">
                    <div>
                      <strong>{doc.full_name}</strong>
                      <div className="muted small">
                        {doc.specialization} · {doc.slot_duration_minutes} min slots
                      </div>
                    </div>
                    <Link className="btn btn-sm" to={`/admin/doctors/${doc.id}`}>
                      Configure
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      ) : null}
    </div>
  );
}
