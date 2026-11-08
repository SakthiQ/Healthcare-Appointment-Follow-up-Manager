import { FormEvent, useState } from 'react';
import { api } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { Badge, Card, ErrorBanner, Field, InfoBanner, SuccessBanner } from '../components/ui';
import { validateNewPassword } from '../lib/password';

export default function Account() {
  const { user, changePassword } = useAuth();

  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [fieldErrors, setFieldErrors] = useState<{ current?: string; next?: string; confirm?: string }>({});
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  const [changed, setChanged] = useState(false);

  const [resendError, setResendError] = useState<unknown>(null);
  const [resending, setResending] = useState(false);
  const [resent, setResent] = useState(false);

  if (!user) return null;

  async function handleChange(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setChanged(false);
    const errs: typeof fieldErrors = {};
    if (!current) errs.current = 'Enter your current password.';
    const nextError = validateNewPassword(next);
    if (nextError) errs.next = nextError;
    else if (next === current) errs.next = 'Choose a password different from your current one.';
    if (confirm !== next) errs.confirm = 'The two passwords do not match.';
    setFieldErrors(errs);
    if (Object.keys(errs).length) return;

    setSaving(true);
    try {
      await changePassword(current, next);
      setChanged(true);
      setCurrent('');
      setNext('');
      setConfirm('');
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  }

  async function handleResend() {
    if (!user) return;
    setResendError(null);
    setResent(false);
    setResending(true);
    try {
      await api.resendVerification(user.email);
      setResent(true);
    } catch (err) {
      setResendError(err);
    } finally {
      setResending(false);
    }
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Your account</h1>
          <p className="muted">Manage how you sign in.</p>
        </div>
      </header>

      <Card title="Profile">
        <div className="summary-row">
          <span>Name</span>
          <strong>{user.full_name}</strong>
        </div>
        <div className="summary-row">
          <span>Email</span>
          <strong>{user.email}</strong>
        </div>
        <div className="summary-row">
          <span>Role</span>
          <strong>{user.role}</strong>
        </div>
        <div className="summary-row">
          <span>Email status</span>
          {user.email_verified ? <Badge tone="ok">Verified</Badge> : <Badge tone="warn">Not verified</Badge>}
        </div>

        {!user.email_verified ? (
          <>
            <InfoBanner>
              We sent a confirmation link to {user.email}. Open it to verify your address. It may be
              in your spam folder.
            </InfoBanner>
            <ErrorBanner error={resendError} />
            {resent ? <SuccessBanner>A new link is on its way.</SuccessBanner> : null}
            <button type="button" className="btn" onClick={handleResend} disabled={resending}>
              {resending ? 'Sending…' : 'Send the link again'}
            </button>
          </>
        ) : null}
      </Card>

      <Card title="Change password">
        <ErrorBanner error={error} />
        {changed ? (
          <SuccessBanner>
            Your password has been changed. Your other signed-in devices were signed out.
          </SuccessBanner>
        ) : null}
        <form onSubmit={handleChange} noValidate>
          <div className="form-grid">
            <Field label="Current password" htmlFor="current" error={fieldErrors.current}>
              <input
                id="current"
                type="password"
                autoComplete="current-password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                disabled={saving}
              />
            </Field>
            <Field label="New password" htmlFor="new" error={fieldErrors.next}>
              <input
                id="new"
                type="password"
                autoComplete="new-password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                disabled={saving}
              />
            </Field>
            <Field label="Confirm new password" htmlFor="confirm" error={fieldErrors.confirm}>
              <input
                id="confirm"
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                disabled={saving}
              />
            </Field>
          </div>
          <button type="submit" className="btn btn-primary" disabled={saving}>
            {saving ? 'Saving…' : 'Change password'}
          </button>
        </form>
      </Card>
    </div>
  );
}
