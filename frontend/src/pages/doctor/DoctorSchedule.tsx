import { api } from '../../api/client';
import { useAsync } from '../../lib/useAsync';
import { DAY_NAMES, formatDate, timeZoneName, todayInputValue } from '../../lib/format';
import { Badge, Card, EmptyState, ErrorBanner, InfoBanner, Spinner } from '../../components/ui';

/** Read-only view of the signed-in doctor's weekly hours and upcoming leave. */
export default function DoctorSchedule() {
  const profileQuery = useAsync(() => api.getMyDoctorProfile(), []);
  const doctorId = profileQuery.data?.id;
  const hoursQuery = useAsync(
    () => (doctorId ? api.getDoctorSchedule(doctorId) : Promise.resolve(null)),
    [doctorId],
  );
  const leavesQuery = useAsync(
    () => (doctorId ? api.getDoctorLeaves(doctorId) : Promise.resolve(null)),
    [doctorId],
  );

  if (profileQuery.loading) return <Spinner label="Loading your schedule…" />;
  if (profileQuery.error) return <ErrorBanner error={profileQuery.error} onRetry={profileQuery.reload} />;

  const profile = profileQuery.data;
  const hours = (hoursQuery.data ?? []).filter((h) => h.is_active);
  const today = todayInputValue();
  const leaves = (leavesQuery.data ?? [])
    .filter((leave) => leave.leave_date >= today)
    .sort((a, b) => a.leave_date.localeCompare(b.leave_date));

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>My schedule</h1>
          <p className="muted">
            Times are in your timezone, {timeZoneName(profile?.timezone)}.
          </p>
        </div>
      </header>

      <InfoBanner>Your hours and leave are set by an administrator. Ask them for any changes.</InfoBanner>

      <Card title="Weekly hours">
        {hoursQuery.loading ? <Spinner /> : null}
        <ErrorBanner error={hoursQuery.error} onRetry={hoursQuery.reload} />
        {/* Only once this doctor's hours have arrived, so no day flashes as a day off. */}
        {hoursQuery.data ? (
          <ul className="list">
            {DAY_NAMES.map((day, i) => {
              const shift = hours.find((h) => h.day_of_week === i);
              return (
                <li key={day} className="list-row">
                  <strong>{day}</strong>
                  {shift ? (
                    <span>
                      {shift.start_time.slice(0, 5)}–{shift.end_time.slice(0, 5)}
                    </span>
                  ) : (
                    <Badge tone="muted">Day off</Badge>
                  )}
                </li>
              );
            })}
          </ul>
        ) : null}
      </Card>

      <Card title="Upcoming leave">
        {leavesQuery.loading ? <Spinner /> : null}
        <ErrorBanner error={leavesQuery.error} onRetry={leavesQuery.reload} />
        {leavesQuery.data && leaves.length === 0 ? (
          <EmptyState>No upcoming leave.</EmptyState>
        ) : null}
        {leaves.length > 0 ? (
          <ul className="list">
            {leaves.map((leave) => (
              <li key={leave.id} className="list-row">
                <strong>{formatDate(`${leave.leave_date}T00:00:00Z`)}</strong>
                <span className="muted">{leave.reason ?? 'No reason given'}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </Card>
    </div>
  );
}
