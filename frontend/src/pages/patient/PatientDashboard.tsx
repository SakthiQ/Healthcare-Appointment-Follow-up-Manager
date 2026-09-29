import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';
import { useAsync } from '../../lib/useAsync';
import { formatDateTime, parseServerDate } from '../../lib/format';
import { Card, EmptyState, ErrorBanner, Spinner, StatusBadge } from '../../components/ui';

const ACTIVE = new Set(['CONFIRMED', 'RESCHEDULED', 'HELD']);

export default function PatientDashboard() {
  const { user } = useAuth();
  const { data, loading, error, reload } = useAsync(() => api.listAppointments(), []);

  const appointments = data ?? [];
  const upcoming = appointments
    .filter((a) => ACTIVE.has(a.status) && parseServerDate(a.start_time) >= new Date())
    .sort((a, b) => a.start_time.localeCompare(b.start_time));
  const conflicted = appointments.filter((a) => a.status === 'CONFLICTED');

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Welcome, {user?.full_name}</h1>
          <p className="muted">Book appointments and follow up on your care.</p>
        </div>
        <Link to="/patient/doctors" className="btn btn-primary">
          Book an appointment
        </Link>
      </header>

      {conflicted.length > 0 ? (
        <div className="banner banner-danger" role="alert">
          <div>
            <strong>Action needed</strong>
            <div>
              {conflicted.length} appointment{conflicted.length > 1 ? 's' : ''} could not be kept because
              the doctor became unavailable. Please rebook.
            </div>
          </div>
        </div>
      ) : null}

      <Card title="Upcoming appointments">
        {loading ? <Spinner /> : null}
        <ErrorBanner error={error} onRetry={reload} />
        {!loading && !error ? (
          upcoming.length === 0 ? (
            <EmptyState>
              You have no upcoming appointments. <Link to="/patient/doctors">Find a doctor</Link> to book
              one.
            </EmptyState>
          ) : (
            <ul className="list">
              {upcoming.slice(0, 5).map((appt) => (
                <li key={appt.id} className="list-row">
                  <div>
                    <strong>{formatDateTime(appt.start_time)}</strong>
                    <div className="muted small">
                      {appt.doctor_name ?? 'Unknown doctor'} · Ends {formatDateTime(appt.end_time)}
                    </div>
                  </div>
                  <div className="list-row-end">
                    <StatusBadge status={appt.status} />
                    <Link className="btn btn-sm" to={`/patient/appointments/${appt.id}`}>
                      View
                    </Link>
                  </div>
                </li>
              ))}
            </ul>
          )
        ) : null}
      </Card>

      {conflicted.length > 0 ? (
        <Card title="Appointments needing rebooking">
          <ul className="list">
            {conflicted.map((appt) => (
              <li key={appt.id} className="list-row">
                <div>
                  <strong>{formatDateTime(appt.start_time)}</strong>
                  <div className="muted small">
                    {appt.doctor_name ?? 'Your doctor'} is unavailable — please choose a new slot.
                  </div>
                </div>
                <div className="list-row-end">
                  <StatusBadge status={appt.status} />
                  <Link className="btn btn-sm" to={`/patient/appointments/${appt.id}`}>
                    View
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}
