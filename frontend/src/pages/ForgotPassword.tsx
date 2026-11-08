import { FormEvent, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { ErrorBanner, Field, SuccessBanner } from '../components/ui';

export default function ForgotPassword() {
  const [email, setEmail] = useState('');
  const [fieldError, setFieldError] = useState<string | undefined>();
  const [error, setError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) {
      setFieldError('Enter a valid email address.');
      return;
    }
    setFieldError(undefined);

    setSubmitting(true);
    try {
      // The API answers the same way whether or not the address has an account.
      const result = await api.forgotPassword(email.trim());
      setSent(result.message);
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1>Forgot your password?</h1>
        <p className="muted">Enter your email and we will send you a link to choose a new one.</p>

        <ErrorBanner error={error} />
        {sent ? <SuccessBanner>{sent} The link works for 30 minutes.</SuccessBanner> : null}

        <form onSubmit={handleSubmit} noValidate>
          <Field label="Email" htmlFor="email" error={fieldError}>
            <input
              id="email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={submitting}
            />
          </Field>
          <button type="submit" className="btn btn-primary btn-block" disabled={submitting}>
            {submitting ? 'Sending…' : sent ? 'Send it again' : 'Send reset link'}
          </button>
        </form>

        <p className="auth-alt">
          <Link to="/login">Back to sign in</Link>
        </p>
      </div>
    </div>
  );
}
