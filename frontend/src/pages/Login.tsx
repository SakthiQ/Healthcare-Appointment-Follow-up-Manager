import { FormEvent, useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { api, ApiError } from '../api/client';
import { useAuth, homePathForRole } from '../auth/AuthContext';
import { ErrorBanner, Field, SuccessBanner } from '../components/ui';
import { LanguagePicker, useT } from '../i18n/I18n';

export default function Login() {
  const { user, login, loading } = useAuth();
  const navigate = useNavigate();
  const location = useLocation() as { state?: { from?: string } };

  const t = useT();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fieldErrors, setFieldErrors] = useState<{ email?: string; password?: string }>({});
  const [error, setError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);
  const [resendNote, setResendNote] = useState<string | null>(null);

  if (!loading && user) return <Navigate to={homePathForRole(user.role)} replace />;

  function validate(): boolean {
    const errs: typeof fieldErrors = {};
    if (!email.trim()) errs.email = t('validation.emailRequired');
    else if (!/^\S+@\S+\.\S+$/.test(email.trim())) errs.email = t('validation.emailInvalid');
    if (!password) errs.password = t('validation.passwordRequired');
    setFieldErrors(errs);
    return Object.keys(errs).length === 0;
  }

  // Sign-in is refused (403) until the email is verified, when the API is set to require it.
  const needsVerification = error instanceof ApiError && error.status === 403;

  async function handleResend() {
    setResendNote(null);
    try {
      const result = await api.resendVerification(email.trim());
      setResendNote(result.message);
    } catch (err) {
      setError(err);
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setResendNote(null);
    if (!validate()) return;

    setSubmitting(true);
    try {
      const loggedIn = await login(email.trim(), password);
      const target = location.state?.from ?? homePathForRole(loggedIn.role);
      navigate(target, { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <LanguagePicker />
        <h1>{t('login.title')}</h1>
        <p className="muted">{t('login.subtitle')}</p>

        <ErrorBanner error={error} />
        {needsVerification ? (
          <button type="button" className="btn btn-block" onClick={handleResend} disabled={!email.trim()}>
            {t('login.resendVerification')}
          </button>
        ) : null}
        {resendNote ? <SuccessBanner>{resendNote}</SuccessBanner> : null}

        <form onSubmit={handleSubmit} noValidate>
          <Field label={t('login.email')} htmlFor="email" error={fieldErrors.email}>
            <input
              id="email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={submitting}
            />
          </Field>

          <Field label={t('login.password')} htmlFor="password" error={fieldErrors.password}>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={submitting}
            />
          </Field>

          <button type="submit" className="btn btn-primary btn-block" disabled={submitting}>
            {submitting ? t('login.submitting') : t('login.submit')}
          </button>
        </form>

        <p className="auth-alt">
          <Link to="/forgot-password">{t('login.forgot')}</Link>
        </p>
        <p className="auth-alt">
          {t('login.newPatient')} <Link to="/register">{t('login.createAccount')}</Link>
        </p>
      </div>
    </div>
  );
}
