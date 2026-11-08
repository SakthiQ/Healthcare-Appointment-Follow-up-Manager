import { FormEvent, useState } from 'react';
import { api } from '../../api/client';
import { Card, EmptyState, ErrorBanner, Field, Spinner } from '../../components/ui';
import { formatDateTime } from '../../lib/format';
import { useAsync } from '../../lib/useAsync';

const PAGE_SIZE = 25;

interface Filters {
  action: string;
  patient_id: string;
  actor_id: string;
}

const NO_FILTERS: Filters = { action: '', patient_id: '', actor_id: '' };

export default function AuditLog() {
  const [draft, setDraft] = useState<Filters>(NO_FILTERS);
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [page, setPage] = useState(0);

  const { data, loading, error, reload } = useAsync(
    () =>
      api.listAuditLogs({
        action: filters.action.trim() || undefined,
        patient_id: filters.patient_id.trim() || undefined,
        actor_id: filters.actor_id.trim() || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
    [filters, page],
  );

  function applyFilters(e: FormEvent) {
    e.preventDefault();
    setPage(0);
    setFilters(draft);
  }

  function clearFilters() {
    setDraft(NO_FILTERS);
    setFilters(NO_FILTERS);
    setPage(0);
  }

  const total = data?.total ?? 0;
  const lastPage = Math.max(0, Math.ceil(total / PAGE_SIZE) - 1);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Audit log</h1>
          <p className="muted">
            Who read or changed what, newest first. Times are UTC. Entries hold identifiers and an
            action name, never clinical content, and cannot be edited or deleted here.
          </p>
        </div>
      </header>

      <Card title="Filter">
        <form onSubmit={applyFilters} noValidate>
          <div className="form-grid">
            <Field
              label="Action"
              htmlFor="action"
              hint='Exact (appointment.view) or a prefix ending in a dot (auth.)'
            >
              <input
                id="action"
                value={draft.action}
                onChange={(e) => setDraft({ ...draft, action: e.target.value })}
              />
            </Field>
            <Field label="Patient id" htmlFor="patient" hint="Whose data was accessed">
              <input
                id="patient"
                value={draft.patient_id}
                onChange={(e) => setDraft({ ...draft, patient_id: e.target.value })}
              />
            </Field>
            <Field label="Actor id" htmlFor="actor" hint="Who did it">
              <input
                id="actor"
                value={draft.actor_id}
                onChange={(e) => setDraft({ ...draft, actor_id: e.target.value })}
              />
            </Field>
          </div>
          <div className="row-actions">
            <button type="submit" className="btn btn-primary">
              Apply filters
            </button>
            <button type="button" className="btn" onClick={clearFilters}>
              Clear
            </button>
          </div>
        </form>
      </Card>

      <Card title={`${total} entr${total === 1 ? 'y' : 'ies'}`}>
        {loading ? <Spinner label="Loading the audit log…" /> : null}
        <ErrorBanner error={error} onRetry={reload} />
        {!loading && !error && data ? (
          data.items.length === 0 ? (
            <EmptyState>No entries match.</EmptyState>
          ) : (
            <>
              <table className="table">
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Who</th>
                    <th>Action</th>
                    <th>Resource</th>
                    <th>Patient</th>
                    <th>IP</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((entry) => (
                    <tr key={entry.id}>
                      <td>{formatDateTime(entry.occurred_at)}</td>
                      <td>
                        {entry.actor_role ?? '—'}
                        {entry.actor_user_id ? (
                          <div className="mono small" title={entry.actor_user_id}>
                            {entry.actor_user_id.slice(0, 8)}
                          </div>
                        ) : null}
                      </td>
                      <td className="mono">{entry.action}</td>
                      <td>
                        {entry.resource_type ?? '—'}
                        {entry.resource_id ? (
                          <div className="mono small" title={entry.resource_id}>
                            {entry.resource_id.slice(0, 8)}
                          </div>
                        ) : null}
                      </td>
                      <td className="mono small" title={entry.patient_id ?? undefined}>
                        {entry.patient_id ? entry.patient_id.slice(0, 8) : '—'}
                      </td>
                      <td className="mono small">{entry.ip ?? '—'}</td>
                      <td className="mono small" title={entry.detail ?? undefined}>
                        {entry.detail ? entry.detail.slice(0, 40) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="row-actions">
                <button type="button" className="btn btn-sm" disabled={page === 0} onClick={() => setPage(page - 1)}>
                  Newer
                </button>
                <span className="muted small">
                  Page {page + 1} of {lastPage + 1}
                </span>
                <button type="button" className="btn btn-sm" disabled={page >= lastPage} onClick={() => setPage(page + 1)}>
                  Older
                </button>
              </div>
            </>
          )
        ) : null}
      </Card>
    </div>
  );
}
