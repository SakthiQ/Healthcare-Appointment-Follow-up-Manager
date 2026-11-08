import { FormEvent, useEffect, useState } from 'react';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import type { InvitationLookup } from '../api/types';
import { useAuth, homePathForRole } from '../auth/AuthContext';
import { ErrorBanner, Field, Spinner } from '../components/ui';

const ROLE_LABEL = { DOCTOR: 'a doctor', ADMIN: 'an administrator' } as const;

export default function Register() {
  const { user, login, loading } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  // An invitation link looks like /register?invite=<token>. Everyone uses this one page;
  // the invitation, not the form, decides the role.
  const inviteToken = searchParams.get('invite');

  const [invitation, setInvitation] = useState<InvitationLookup | null>(null);
  const [inviteLoading, setInviteLoading] = useState(Boolean(inviteToken));
  const [inviteError, setInviteError] = useState<unknown>(null);

  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!inviteToken) return;
    let cancelled = false;
    setInviteLoading(true);
    setInviteError(null);
    api
      .lookupInvitation(inviteToken)
      .then((found) => {
        if (cancelled) return;
        setInvitation(found);
        setEmail(found.email);
        if (found.full_name) setFullName(found.full_name);
      })
      .catch((err) => {
        if (!cancelled) setInviteError(err);
      })
      .finally(() => {
        if (!cancelled) setInviteLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [inviteToken]);

  if (!loading && user) return <Navigate to={homePathForRole(user.role)} replace />;

  function validate(): boolean {
    const errs: Record<string, string> = {};
    if (fullName.trim().length < 2) errs.fullName = 'Enter your full name (at least 2 characters).';
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) errs.email = 'Enter a valid email address.';
    if (password.length < 6) errs.password = 'Password must be at least 6 characters.';
    if (confirm !== password) errs.confirm = 'Passwords do not match.';
    setFieldErrors(errs);
    return Object.keys(errs).length === 0;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!validate()) return;

    setSubmitting(true);
    try {
      // Without an invitation this is patient self-registration. With one, the backend takes
      // the role (and a doctor's profile) from the invitation and ignores `role` here.
      await api.register({
        email: email.trim(),
        password,
        full_name: fullName.trim(),
        role: 'PATIENT',
        ...(invitation && inviteToken ? { invite_token: inviteToken } : {}),
      });
      const loggedIn = await login(email.trim(), password);
      navigate(homePathForRole(loggedIn.role), { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  }

  if (inviteToken && inviteLoading) {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <Spinner label="Checking your invitation…" />
        </div>
      </div>
    );
  }

  if (inviteToken && !invitation) {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <h1>Invitation problem</h1>
          <ErrorBanner error={inviteError} />
          <p className="auth-alt">
            <Link to="/login">Sign in</Link> if you already have an account, or ask an administrator
            for a new invitation.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1>Create your account</h1>
        {invitation ? (
          <p className="muted">
            You have been invited to join as <strong>{ROLE_LABEL[invitation.role]}</strong>. Choose a
            password to finish.
          </p>
        ) : (
          <p className="muted">Register as a patient to book appointments.</p>
        )}

        <ErrorBanner error={error} />

        <form onSubmit={handleSubmit} noValidate>
          <Field label="Full name" htmlFor="fullName" error={fieldErrors.fullName}>
            <input
              id="fullName"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              disabled={submitting}
              autoComplete="name"
            />
          </Field>

          <Field
            label="Email"
            htmlFor="email"
            error={fieldErrors.email}
            hint={invitation ? 'The address your invitation was sent to.' : undefined}
          >
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={submitting}
              readOnly={Boolean(invitation)}
              autoComplete="email"
            />
          </Field>

          <Field
            label="Password"
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
              autoComplete="new-password"
            />
          </Field>

          <Field label="Confirm password" htmlFor="confirm" error={fieldErrors.confirm}>
            <input
              id="confirm"
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              disabled={submitting}
              autoComplete="new-password"
            />
          </Field>

          <button type="submit" className="btn btn-primary btn-block" disabled={submitting}>
            {submitting ? 'Creating account…' : 'Create account'}
          </button>
        </form>

        <p className="auth-alt">
          Already registered? <Link to="/login">Sign in</Link>
        </p>
      </div>
    </div>
  );
}
