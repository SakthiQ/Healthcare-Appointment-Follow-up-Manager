import { FormEvent, useState } from 'react';
import { api } from '../../api/client';
import type { Department } from '../../api/types';
import { useAsync } from '../../lib/useAsync';
import { Badge, Card, EmptyState, ErrorBanner, Field, Spinner, SuccessBanner } from '../../components/ui';

/** Admins create, rename and deactivate the departments doctors belong to. */
export default function Departments() {
  const { data, loading, error, reload } = useAsync(() => api.adminListDepartments(), []);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [editing, setEditing] = useState<{ id: string; name: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function run(action: () => Promise<unknown>, done: string) {
    setActionError(null);
    setNotice(null);
    setBusy(true);
    try {
      await action();
      setNotice(done);
      reload();
      return true;
    } catch (err) {
      setActionError(err);
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (trimmed.length < 2) {
      setActionError(new Error('Department name must be at least 2 characters.'));
      return;
    }
    if (await run(() => api.createDepartment({ name: trimmed, description: description.trim() || null }), `Created ${trimmed}.`)) {
      setName('');
      setDescription('');
    }
  }

  async function handleRename(e: FormEvent) {
    e.preventDefault();
    if (!editing) return;
    const trimmed = editing.name.trim();
    if (await run(() => api.updateDepartment(editing.id, { name: trimmed }), `Renamed to ${trimmed}.`)) {
      setEditing(null);
    }
  }

  function toggle(dept: Department) {
    run(
      () => api.updateDepartment(dept.id, { is_active: !dept.is_active }),
      dept.is_active
        ? `${dept.name} deactivated. Patients no longer see it.`
        : `${dept.name} reactivated.`,
    );
  }

  const departments = data ?? [];

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Departments</h1>
          <p className="muted">Group doctors so patients can browse by department.</p>
        </div>
      </header>

      {notice ? <SuccessBanner>{notice}</SuccessBanner> : null}
      <ErrorBanner error={actionError} />

      <Card title="New department">
        <form onSubmit={handleCreate} noValidate>
          <div className="form-grid">
            <Field label="Name" htmlFor="dept-name">
              <input id="dept-name" maxLength={100} value={name} onChange={(e) => setName(e.target.value)} disabled={busy} placeholder="e.g. Cardiology" />
            </Field>
            <Field label="Description (optional)" htmlFor="dept-description">
              <input id="dept-description" maxLength={500} value={description} onChange={(e) => setDescription(e.target.value)} disabled={busy} />
            </Field>
          </div>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            Create department
          </button>
        </form>
      </Card>

      <Card title="All departments">
        {loading ? <Spinner /> : null}
        <ErrorBanner error={error} onRetry={reload} />
        {!loading && !error && departments.length === 0 ? (
          <EmptyState>No departments yet. Create the first one above.</EmptyState>
        ) : null}
        {departments.length > 0 ? (
          <ul className="list">
            {departments.map((dept) => (
              <li key={dept.id} className="list-row">
                {editing?.id === dept.id ? (
                  <form onSubmit={handleRename} className="row-actions">
                    <label className="sr-only" htmlFor={`rename-${dept.id}`}>
                      New name for {dept.name}
                    </label>
                    <input id={`rename-${dept.id}`} maxLength={100} value={editing.name}
                      onChange={(e) => setEditing({ id: dept.id, name: e.target.value })} disabled={busy} />
                    <button type="submit" className="btn btn-sm btn-primary" disabled={busy}>Save</button>
                    <button type="button" className="btn btn-sm" onClick={() => setEditing(null)} disabled={busy}>Cancel</button>
                  </form>
                ) : (
                  <div>
                    <strong>{dept.name}</strong>
                    <div className="muted small">
                      {dept.active_doctor_count} active doctor(s){dept.description ? ` · ${dept.description}` : ''}
                    </div>
                  </div>
                )}
                <div className="list-row-end">
                  <Badge tone={dept.is_active ? 'ok' : 'muted'}>{dept.is_active ? 'Active' : 'Deactivated'}</Badge>
                  {editing?.id !== dept.id ? (
                    <button type="button" className="btn btn-sm" onClick={() => setEditing({ id: dept.id, name: dept.name })} disabled={busy}>
                      Rename
                    </button>
                  ) : null}
                  <button type="button" className="btn btn-sm" onClick={() => toggle(dept)} disabled={busy}>
                    {dept.is_active ? 'Deactivate' : 'Reactivate'}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        ) : null}
      </Card>
    </div>
  );
}
