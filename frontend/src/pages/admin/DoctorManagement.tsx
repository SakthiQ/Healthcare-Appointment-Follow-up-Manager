import { FormEvent, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { useAsync } from '../../lib/useAsync';
import { Badge, Card, EmptyState, ErrorBanner, Field, Spinner, SuccessBanner } from '../../components/ui';

export default function DoctorManagement() {
  const { data, loading, error, reload } = useAsync(() => api.searchDoctors(), []);

  const [showForm, setShowForm] = useState(false);
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [specialization, setSpecialization] = useState('');
  const [slotDuration, setSlotDuration] = useState(30);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [submitError, setSubmitError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  function resetForm() {
    setFullName('');
    setEmail('');
    setPassword('');
    setSpecialization('');
    setSlotDuration(30);
    setFieldErrors({});
    setSubmitError(null);
  }

  function validate(): boolean {
    const errs: Record<string, string> = {};
    if (fullName.trim().length < 2) errs.fullName = 'Full name is required.';
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) errs.email = 'Enter a valid email address.';
    if (password.length < 6) errs.password = 'Password must be at least 6 characters.';
    if (specialization.trim().length < 2) errs.specialization = 'Specialisation is required.';
    if (slotDuration < 5 || slotDuration > 240)
      errs.slotDuration = 'Slot duration must be between 5 and 240 minutes.';
    setFieldErrors(errs);
    return Object.keys(errs).length === 0;
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setSubmitError(null);
    setNotice(null);
    if (!validate()) return;

    setSubmitting(true);
    try {
      const created = await api.createDoctor({
        email: email.trim(),
        password,
        full_name: fullName.trim(),
        specialization: specialization.trim(),
        slot_duration_minutes: slotDuration,
      });
      setNotice(`Created ${created.full_name}. Configure their working hours next.`);
      resetForm();
      setShowForm(false);
      reload();
    } catch (err) {
      setSubmitError(err);
    } finally {
      setSubmitting(false);
    }
  }

  const doctors = data ?? [];

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Doctors</h1>
          <p className="muted">Create doctor accounts and configure their schedules.</p>
        </div>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => {
            setShowForm((v) => !v);
            setNotice(null);
          }}
        >
          {showForm ? 'Close' : 'Add doctor'}
        </button>
      </header>

      {notice ? <SuccessBanner>{notice}</SuccessBanner> : null}

      {showForm ? (
        <Card title="New doctor">
          <ErrorBanner error={submitError} />
          <form onSubmit={handleCreate} noValidate>
            <div className="form-grid">
              <Field label="Full name" htmlFor="fullName" error={fieldErrors.fullName}>
                <input
                  id="fullName"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  disabled={submitting}
                />
              </Field>
              <Field label="Specialisation" htmlFor="specialization" error={fieldErrors.specialization}>
                <input
                  id="specialization"
                  value={specialization}
                  onChange={(e) => setSpecialization(e.target.value)}
                  disabled={submitting}
                  placeholder="e.g. Cardiology"
                />
              </Field>
              <Field label="Email" htmlFor="email" error={fieldErrors.email}>
                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  disabled={submitting}
                />
              </Field>
              <Field
                label="Temporary password"
                htmlFor="password"
                error={fieldErrors.password}
                hint="At least 6 characters."
              >
                <input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={submitting}
                />
              </Field>
              <Field
                label="Slot duration (minutes)"
                htmlFor="slotDuration"
                error={fieldErrors.slotDuration}
                hint="Between 5 and 240."
              >
                <input
                  id="slotDuration"
                  type="number"
                  min={5}
                  max={240}
                  value={slotDuration}
                  onChange={(e) => setSlotDuration(Number(e.target.value))}
                  disabled={submitting}
                />
              </Field>
            </div>
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? 'Creating…' : 'Create doctor'}
            </button>
          </form>
        </Card>
      ) : null}

      <Card title="All doctors">
        {loading ? <Spinner /> : null}
        <ErrorBanner error={error} onRetry={reload} />
        {!loading && !error ? (
          doctors.length === 0 ? (
            <EmptyState>No doctors yet. Use "Add doctor" to create the first one.</EmptyState>
          ) : (
            <ul className="list">
              {doctors.map((doc) => (
                <li key={doc.id} className="list-row">
                  <div>
                    <strong>{doc.full_name}</strong>
                    <div className="muted small">
                      {doc.specialization} · {doc.slot_duration_minutes} min · {doc.email}
                    </div>
                  </div>
                  <div className="list-row-end">
                    <Badge tone={doc.is_active ? 'ok' : 'muted'}>
                      {doc.is_active ? 'Active' : 'Inactive'}
                    </Badge>
                    <Link className="btn btn-sm" to={`/admin/doctors/${doc.id}`}>
                      Configure
                    </Link>
                  </div>
                </li>
              ))}
            </ul>
          )
        ) : null}
        <p className="muted small">
          Only active doctors are bookable by patients. Deactivate on a doctor's page.
        </p>
      </Card>
    </div>
  );
}
