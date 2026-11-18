import { useState } from 'react';
import { api, ApiError } from '../../api/client';
import type { FailedJob, FailedJobKind } from '../../api/types';
import { Card, EmptyState, ErrorBanner, Pager, Spinner, SuccessBanner } from '../../components/ui';
import { formatDateTime } from '../../lib/format';
import { useAsync } from '../../lib/useAsync';

const PAGE_SIZE = 25;

const TABS: { kind: FailedJobKind; label: string }[] = [
  { kind: 'notification', label: 'Emails' },
  { kind: 'calendar', label: 'Calendar' },
];

export default function FailedJobs() {
  const [kind, setKind] = useState<FailedJobKind>('notification');
  const [page, setPage] = useState(0);
  // Rows retried on this page, hidden until the list is next fetched.
  const [retried, setRetried] = useState<Set<string>>(new Set());
  const [busyId, setBusyId] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [retryError, setRetryError] = useState<unknown>(null);

  const { data, loading, error, reload } = useAsync(
    () => api.listFailedJobs({ kind, limit: PAGE_SIZE, offset: page * PAGE_SIZE }),
    [kind, page],
  );

  function switchTab(next: FailedJobKind) {
    if (next === kind) return;
    setKind(next);
    setPage(0);
    setRetried(new Set());
    setSuccess(null);
    setRetryError(null);
  }

  function refresh() {
    setRetried(new Set());
    reload();
  }

  async function retry(job: FailedJob) {
    setBusyId(job.id);
    setSuccess(null);
    setRetryError(null);
    try {
      await api.retryFailedJob(job);
      setRetried((prev) => new Set(prev).add(job.id));
      setSuccess(
        job.kind === 'calendar'
          ? `The ${job.type} calendar sync is back in the queue.`
          : `The ${job.type} email is back in the queue and will be sent on the next run.`,
      );
    } catch (err) {
      setRetryError(err);
      // Someone else may have retried it already, or it can no longer be sent: show what is true now.
      if (err instanceof ApiError && err.status === 409) refresh();
    } finally {
      setBusyId(null);
    }
  }

  const rows = data ? data.items.filter((job) => !retried.has(job.id)) : [];
  const total = data ? Math.max(0, data.total - retried.size) : 0;
  const noun = kind === 'calendar' ? 'calendar sync' : 'email';

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Failed jobs</h1>
          <p className="muted">
            Emails and calendar syncs that used up their retries, newest first. Retrying puts a job
            back in the queue with its attempts reset. Times are UTC.
          </p>
        </div>
      </header>

      <div className="row-actions" role="tablist" aria-label="Job kind">
        {TABS.map((tab) => (
          <button
            key={tab.kind}
            type="button"
            role="tab"
            aria-selected={kind === tab.kind}
            className={`btn btn-sm${kind === tab.kind ? ' btn-primary' : ''}`}
            onClick={() => switchTab(tab.kind)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {success ? <SuccessBanner>{success}</SuccessBanner> : null}
      <ErrorBanner error={retryError} />

      <Card title={`${total} failed ${noun}${total === 1 ? '' : 's'}`}>
        {loading ? <Spinner label="Loading failed jobs…" /> : null}
        <ErrorBanner error={error} onRetry={refresh} />
        {!loading && !error && data ? (
          rows.length === 0 ? (
            <EmptyState>No failed {noun}s.</EmptyState>
          ) : (
            <>
              <table className="table">
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Appointment</th>
                    <th>Attempts</th>
                    <th>Last error</th>
                    <th>Failed</th>
                    <th>
                      <span className="sr-only">Action</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((job) => (
                    <tr key={job.id}>
                      <td className="mono">{job.type}</td>
                      <td className="mono small" title={job.appointment_id ?? undefined}>
                        {job.appointment_id ? job.appointment_id.slice(0, 8) : '—'}
                      </td>
                      <td>{job.attempts}</td>
                      <td className="small" title={job.last_error ?? undefined}>
                        {job.last_error ? truncate(job.last_error, 120) : '—'}
                      </td>
                      <td>{formatDateTime(job.updated_at)}</td>
                      <td>
                        {job.retryable ? (
                          <button
                            type="button"
                            className="btn btn-sm"
                            disabled={busyId !== null}
                            onClick={() => retry(job)}
                            aria-label={`Retry ${job.type}`}
                          >
                            {busyId === job.id ? 'Retrying…' : 'Retry'}
                          </button>
                        ) : (
                          <span className="muted small">{job.not_retryable_reason ?? 'Cannot be retried.'}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <Pager
                page={page}
                pageSize={PAGE_SIZE}
                total={data.total}
                onPage={(next) => {
                  setRetried(new Set());
                  setPage(next);
                }}
              />
            </>
          )
        ) : null}
      </Card>
    </div>
  );
}

function truncate(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}
