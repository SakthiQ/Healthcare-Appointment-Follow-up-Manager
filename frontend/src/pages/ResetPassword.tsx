import { FormEvent, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { ErrorBanner, Field, SuccessBanner } from '../components/ui';
import { validateNewPassword } from '../lib/password';
import { LanguagePicker, useT } from '../i18n/I18n';

export default function ResetPassword() {
  const t = useT();
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
    if (confirm !== password) errs.confirm = t('reset.mismatch');
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
          <LanguagePicker />
          <h1>{t('reset.title')}</h1>
          <ErrorBanner error={new Error(t('reset.incomplete'))} />
          <p className="auth-alt">
            <Link to="/forgot-password">{t('reset.requestNew')}</Link>
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <LanguagePicker />
        <h1>{t('reset.choose')}</h1>

        {done ? (
          <>
            <SuccessBanner>
              {t('reset.done')}
            </SuccessBanner>
            <Link to="/login" className="btn btn-primary btn-block">
              {t('reset.goToSignIn')}
            </Link>
          </>
        ) : (
          <>
            <ErrorBanner error={error} />
            <form onSubmit={handleSubmit} noValidate>
              <Field label={t('reset.newPassword')} htmlFor="password" error={fieldErrors.password}>
                <input
                  id="password"
                  type="password"
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={submitting}
                />
              </Field>
              <Field label={t('reset.confirm')} htmlFor="confirm" error={fieldErrors.confirm}>
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
                {submitting ? t('reset.saving') : t('reset.submit')}
              </button>
            </form>
            <p className="auth-alt">
              {t('reset.expired')} <Link to="/forgot-password">{t('reset.requestAnother')}</Link>
            </p>
          </>
        )}
      </div>
    </div>
  );
}
