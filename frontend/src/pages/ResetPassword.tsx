import { FormEvent, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { ErrorBanner, Field, SuccessBanner } from '../components/ui';
import { validateNewPassword } from '../lib/password';

export default function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';

  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [fieldErrors, setFieldErrors] = useState<{ password?: string; confirm?: string }>({});
  const [error, setError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const errs: typeof fieldErrors = {};
    const passwordError = validateNewPassword(password);
    if (passwordError) errs.password = passwordError;
    if (confirm !== password) errs.confirm = 'The two passwords do not match.';
    setFieldErrors(errs);
    if (Object.keys(errs).length) return;

    setSubmitting(true);
    try {
      await api.resetPassword(token, password);
      setDone(true);
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  }

  if (!token) {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <h1>Reset your password</h1>
          <ErrorBanner error={new Error('This link is incomplete. Open the link from your email again.')} />
          <p className="auth-alt">
            <Link to="/forgot-password">Request a new link</Link>
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1>Choose a new password</h1>

        {done ? (
          <>
            <SuccessBanner>
              Your password has been changed and you were signed out everywhere. Sign in with the
              new one.
            </SuccessBanner>
            <Link to="/login" className="btn btn-primary btn-block">
              Go to sign in
            </Link>
          </>
        ) : (
          <>
            <ErrorBanner error={error} />
            <form onSubmit={handleSubmit} noValidate>
              <Field label="New password" htmlFor="password" error={fieldErrors.password}>
                <input
                  id="password"
                  type="password"
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={submitting}
                />
              </Field>
              <Field label="Confirm new password" htmlFor="confirm" error={fieldErrors.confirm}>
                <input
                  id="confirm"
                  type="password"
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  disabled={submitting}
                />
              </Field>
              <button type="submit" className="btn btn-primary btn-block" disabled={submitting}>
                {submitting ? 'Saving…' : 'Change password'}
              </button>
            </form>
            <p className="auth-alt">
              Link expired? <Link to="/forgot-password">Request a new one</Link>
            </p>
          </>
        )}
      </div>
    </div>
  );
}
