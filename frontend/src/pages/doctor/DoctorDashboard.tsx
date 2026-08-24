import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';
import { useAsync } from '../../lib/useAsync';
import { formatDate, formatDateTime, parseServerDate } from '../../lib/format';
import { Card, EmptyState, ErrorBanner, Spinner, StatusBadge } from '../../components/ui';

const ACTIVE = new Set(['CONFIRMED', 'RESCHEDULED']);

export default function DoctorDashboard() {
  const { user } = useAuth();
  const { data, loading, error, reload } = useAsync(() => api.listAppointments(), []);

  const appointments = data ?? [];
  const now = new Date();
  const upcoming = appointments
    .filter((a) => ACTIVE.has(a.status) && parseServerDate(a.start_time) >= now)
    .sort((a, b) => a.start_time.localeCompare(b.start_time));

  const todayKey = formatDate(now.toISOString());
  const todays = upcoming.filter((a) => formatDate(a.start_time) === todayKey);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Welcome, {user?.full_name}</h1>
          <p className="muted">Your schedule and patient consultations.</p>
        </div>
        <Link to="/doctor/appointments" className="btn btn-primary">
          All appointments
        </Link>
      </header>

      <div className="stat-row">
        <div className="stat">
          <span className="stat-value">{todays.length}</span>
          <span className="stat-label">Today</span>
        </div>
        <div className="stat">
          <span className="stat-value">{upcoming.length}</span>
          <span className="stat-label">Upcoming</span>
        </div>
        <div className="stat">
          <span className="stat-value">{appointments.length}</span>
          <span className="stat-label">Total</span>
        </div>
      </div>

      <Card title="Next appointments">
        {loading ? <Spinner /> : null}
        <ErrorBanner error={error} onRetry={reload} />
        {!loading && !error ? (
          upcoming.length === 0 ? (
            <EmptyState>You have no upcoming appointments.</EmptyState>
          ) : (
            <ul className="list">
              {upcoming.slice(0, 8).map((appt) => (
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
