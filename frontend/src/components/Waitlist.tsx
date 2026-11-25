import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { useAsync } from '../lib/useAsync';
import { formatDate } from '../lib/format';
import { Card, ErrorBanner, SuccessBanner } from './ui';

/** On a fully booked day: join the waitlist and get an email if a slot opens. */
export function JoinWaitlistButton({ doctorId, date }: { doctorId: string; date: string }) {
  const [busy, setBusy] = useState(false);
  const [joined, setJoined] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function handleJoin() {
    setError(null);
    setBusy(true);
    try {
      await api.joinWaitlist(doctorId, date);
      setJoined(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (joined) {
    return (
      <SuccessBanner>
        You are on the waitlist. If a slot opens that day, we will email you. Everyone waiting is told at
        once, so book quickly.
      </SuccessBanner>
    );
  }
  return (
    <div>
      <ErrorBanner error={error} />
      <button type="button" className="btn" onClick={handleJoin} disabled={busy}>
        {busy ? 'Joining…' : 'Join waitlist for this day'}
      </button>
    </div>
  );
}

/** The patient's waitlists, on their dashboard. Hidden when there are none. */
export function MyWaitlist() {
  const { data, error, reload } = useAsync(() => api.getMyWaitlist(), []);
  const [actionError, setActionError] = useState<unknown>(null);

  async function leave(doctorId: string, date: string) {
    setActionError(null);
    try {
      await api.leaveWaitlist(doctorId, date);
      reload();
    } catch (err) {
      setActionError(err);
    }
  }

  if (!error && (!data || data.length === 0)) return null;
  return (
    <Card title="My waitlist">
      <ErrorBanner error={error ?? actionError} onRetry={error ? reload : undefined} />
      <ul className="list">
        {(data ?? []).map((entry) => (
          <li key={entry.id} className="list-row">
            <div>
              <strong>{entry.doctor_name ?? 'Doctor'}</strong> · {formatDate(`${entry.date}T00:00:00Z`)}
              <div className="muted small">
                {entry.notified_at ? 'A slot opened up. Book it before someone else does.' : 'Waiting for a slot to open.'}
              </div>
            </div>
            <div className="list-row-end">
              {entry.notified_at ? (
                <Link className="btn btn-sm btn-primary" to={`/patient/doctors/${entry.doctor_id}`}>
                  Book
                </Link>
              ) : null}
              <button type="button" className="btn btn-sm" onClick={() => leave(entry.doctor_id, entry.date)}>
                Leave
              </button>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}
