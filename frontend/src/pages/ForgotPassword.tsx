import { FormEvent, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { ErrorBanner, Field, SuccessBanner } from '../components/ui';
import { LanguagePicker, useT } from '../i18n/I18n';

export default function ForgotPassword() {
  const t = useT();
  const [email, setEmail] = useState('');
  const [fieldError, setFieldError] = useState<string | undefined>();
  const [error, setError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) {
      setFieldError(t('validation.emailInvalid'));
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
        <LanguagePicker />
        <h1>{t('forgot.title')}</h1>
        <p className="muted">{t('forgot.subtitle')}</p>

        <ErrorBanner error={error} />
        {sent ? <SuccessBanner>{sent} {t('forgot.linkValid')}</SuccessBanner> : null}

        <form onSubmit={handleSubmit} noValidate>
          <Field label={t('login.email')} htmlFor="email" error={fieldError}>
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
            {submitting ? t('forgot.sending') : sent ? t('forgot.sendAgain') : t('forgot.send')}
          </button>
        </form>

        <p className="auth-alt">
          <Link to="/login">{t('common.backToSignIn')}</Link>
        </p>
      </div>
    </div>
  );
}
