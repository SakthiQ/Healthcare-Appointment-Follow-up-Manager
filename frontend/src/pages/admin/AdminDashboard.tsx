import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';
import { useAsync } from '../../lib/useAsync';
import { Card, ErrorBanner, Spinner } from '../../components/ui';
import ExportAppointments from './ExportAppointments';

export default function AdminDashboard() {
  const { user } = useAuth();
  const doctorsQuery = useAsync(() => api.searchDoctors(), []);
  // Counts come from the database; downloading every appointment just to count them
  // does not scale.
  const statsQuery = useAsync(() => api.getAdminStats(), []);

  // Admins are sent every doctor, including deactivated ones.
  const doctors = (doctorsQuery.data ?? []).filter((d) => d.is_active);
  const stats = statsQuery.data;
  const conflictedCount = stats?.appointments_by_status.CONFLICTED ?? 0;

  const loading = doctorsQuery.loading || statsQuery.loading;
  const error = doctorsQuery.error ?? statsQuery.error;

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
          statsQuery.reload();
        }}
      />

      {!loading && !error ? (
        <>
          <div className="stat-row">
            <div className="stat">
              <span className="stat-value">{stats?.active_doctors ?? doctors.length}</span>
              <span className="stat-label">Active doctors</span>
            </div>
            <div className="stat">
              <span className="stat-value">{stats?.appointments_total ?? 0}</span>
              <span className="stat-label">Appointments</span>
            </div>
            <div className={conflictedCount > 0 ? 'stat stat-danger' : 'stat'}>
              <span className="stat-value">{conflictedCount}</span>
              <span className="stat-label">Conflicted</span>
            </div>
          </div>

          {conflictedCount > 0 ? (
            <div className="banner banner-danger" role="alert">
              <div>
                <strong>{conflictedCount} appointment(s) need attention</strong>
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

          <ExportAppointments doctors={doctorsQuery.data ?? []} />
        </>
      ) : null}
    </div>
  );
}
