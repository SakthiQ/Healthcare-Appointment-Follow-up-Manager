import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { ErrorBanner, Spinner, SuccessBanner } from '../components/ui';

type State = { kind: 'working' } | { kind: 'ok' } | { kind: 'failed'; error: unknown };

export default function VerifyEmail() {
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const { user, refreshUser } = useAuth();
  const [state, setState] = useState<State>(
    token ? { kind: 'working' } : { kind: 'failed', error: new Error('This link is incomplete. Open the link from your email again.') },
  );

  // The link works once, and React StrictMode runs effects twice in development: without
  // this guard the second run would spend the token again and report a false failure.
  const started = useRef(false);

  useEffect(() => {
    if (!token || started.current) return;
    started.current = true;
    api
      .verifyEmail(token)
      .then(async () => {
        setState({ kind: 'ok' });
        if (user) await refreshUser().catch(() => undefined); // a signed-in user's banner goes away
      })
      .catch((error) => setState({ kind: 'failed', error }));
    // Runs once per token; `user` and `refreshUser` are deliberately not dependencies.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1>Email verification</h1>
        {state.kind === 'working' ? <Spinner label="Confirming your email address…" /> : null}
        {state.kind === 'ok' ? (
          <>
            <SuccessBanner>Thank you. Your email address is confirmed.</SuccessBanner>
            <Link to={user ? '/' : '/login'} className="btn btn-primary btn-block">
              {user ? 'Continue' : 'Go to sign in'}
            </Link>
          </>
        ) : null}
        {state.kind === 'failed' ? (
          <>
            <ErrorBanner error={state.error} />
            <p className="auth-alt">
              {user ? (
                <Link to="/account">Request a new link from your account page</Link>
              ) : (
                <Link to="/login">Sign in to request a new link</Link>
              )}
            </p>
          </>
        ) : null}
      </div>
    </div>
  );
}
