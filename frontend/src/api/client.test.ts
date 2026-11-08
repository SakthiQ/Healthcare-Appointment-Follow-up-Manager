import { describe, expect, it, vi } from 'vitest';
import { jsonResponse } from '../test/helpers';

/** The client reads its mode from the build environment when the module loads, so each
 *  test loads a fresh copy under the mode it wants. */
async function loadClient(cookieMode: boolean) {
  vi.resetModules();
  vi.stubEnv('VITE_AUTH_COOKIES', cookieMode ? 'true' : 'false');
  return import('./client');
}

function stubFetch(make: () => Response | Promise<Response>) {
  const fetchMock = vi.fn(async (..._args: unknown[]) => make());
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function lastRequest(fetchMock: ReturnType<typeof stubFetch>) {
  const [url, init] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1] as [string, RequestInit];
  return { url, init, headers: (init.headers ?? {}) as Record<string, string> };
}

describe('authentication in Bearer mode (the default)', () => {
  it('sends the token in the Authorization header and nothing cookie-related', async () => {
    const { api, setToken } = await loadClient(false);
    setToken('tok-123');
    const fetchMock = stubFetch(() => jsonResponse({ id: 'u1' }));

    await api.me();

    const { url, init, headers } = lastRequest(fetchMock);
    expect(url).toBe('/api/v1/auth/me');
    expect(headers.Authorization).toBe('Bearer tok-123');
    expect(headers['X-CSRF-Protection']).toBeUndefined();
    expect(init.credentials).toBe('same-origin');
  });

  it('sends no Authorization header when signed out', async () => {
    const { api } = await loadClient(false);
    const fetchMock = stubFetch(() => jsonResponse([]));

    await api.searchDoctors();

    expect(lastRequest(fetchMock).headers.Authorization).toBeUndefined();
  });
});

describe('authentication in cookie mode', () => {
  it('keeps only a marker in localStorage, never the token', async () => {
    const { setToken, getToken } = await loadClient(true);

    setToken('secret-jwt-value');

    expect(getToken()).toBe('cookie-session');
    expect(JSON.stringify({ ...localStorage })).not.toContain('secret-jwt-value');
  });

  it('relies on the cookie: includes credentials, adds the CSRF header, sends no Authorization', async () => {
    const { api, setToken } = await loadClient(true);
    setToken('secret-jwt-value');
    const fetchMock = stubFetch(() => jsonResponse({ id: 'u1' }));

    await api.me();

    const { init, headers } = lastRequest(fetchMock);
    expect(init.credentials).toBe('include');
    expect(headers['X-CSRF-Protection']).toBe('1');
    expect(headers.Authorization).toBeUndefined();
  });
});

describe('error handling', () => {
  it('surfaces the backend message and error code', async () => {
    const { api, ApiError } = await loadClient(false);
    stubFetch(() => jsonResponse({ detail: 'Current password is incorrect.', error_code: 'VALIDATION_ERROR' }, 422));

    const error = await api.changePassword({ current_password: 'x', new_password: 'yyyyyy' }).catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error.message).toBe('Current password is incorrect.');
    expect(error.status).toBe(422);
    expect(error.errorCode).toBe('VALIDATION_ERROR');
  });

  it('turns FastAPI validation errors into "field: message"', async () => {
    const { api } = await loadClient(false);
    stubFetch(() =>
      jsonResponse({ detail: [{ loc: ['body', 'new_password'], msg: 'String should have at least 6 characters' }] }, 422),
    );

    const error = await api.resetPassword('tokentokentoken', 'abc').catch((e) => e);

    expect(error.message).toBe('new_password: String should have at least 6 characters');
  });

  it('shows the rate-limit message from a 429', async () => {
    const { api } = await loadClient(false);
    stubFetch(() => jsonResponse({ detail: 'Too many requests. Please try again in about 30 minute(s).' }, 429));

    const error = await api.forgotPassword('a@b.co').catch((e) => e);

    expect(error.status).toBe(429);
    expect(error.message).toMatch(/too many requests/i);
  });

  it('falls back to a plain message when the body has none', async () => {
    const { api } = await loadClient(false);
    stubFetch(() => new Response('<html>oops</html>', { status: 500 }));
    expect((await api.me().catch((e) => e)).message).toBe('Request failed (HTTP 500).');

    stubFetch(() => new Response(null, { status: 404 }));
    expect((await api.me().catch((e) => e)).message).toBe('Not found.');
  });

  it('reports an unreachable server as a network error', async () => {
    const { api } = await loadClient(false);
    stubFetch(() => Promise.reject(new TypeError('Failed to fetch')));

    const error = await api.me().catch((e) => e);

    expect(error.status).toBe(0);
    expect(error.errorCode).toBe('NETWORK_ERROR');
  });

  it('treats 204 as success with no body', async () => {
    const { api } = await loadClient(false);
    stubFetch(() => new Response(null, { status: 204 }));

    await expect(api.logout()).resolves.toBeUndefined();
  });

  it('nullIfNotFound turns a 404 into null but still throws everything else', async () => {
    const { api, nullIfNotFound } = await loadClient(false);
    stubFetch(() => jsonResponse({ detail: 'nope' }, 404));
    await expect(nullIfNotFound(api.getConsultation('a1'))).resolves.toBeNull();

    stubFetch(() => jsonResponse({ detail: 'boom' }, 500));
    await expect(nullIfNotFound(api.getConsultation('a1'))).rejects.toMatchObject({ status: 500 });
  });
});

describe('an expired or revoked session', () => {
  it('clears the token and tells the app when the current token is rejected', async () => {
    const { api, setToken, getToken, setUnauthorizedHandler } = await loadClient(false);
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    setToken('old');
    stubFetch(() => jsonResponse({ detail: 'Token has expired' }, 401));

    await api.me().catch(() => undefined);

    expect(getToken()).toBeNull();
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it('ignores a 401 for a token that has since been replaced (a stale request must not end the new session)', async () => {
    const { api, setToken, getToken, setUnauthorizedHandler } = await loadClient(false);
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    setToken('old');
    stubFetch(() => {
      setToken('new'); // the user signed in again while the request was in flight
      return jsonResponse({ detail: 'Token has expired' }, 401);
    });

    await api.me().catch(() => undefined);

    expect(getToken()).toBe('new');
    expect(handler).not.toHaveBeenCalled();
  });
});

describe('account endpoints', () => {
  it('posts the right payloads', async () => {
    const { api } = await loadClient(false);
    const fetchMock = stubFetch(() => jsonResponse({ message: 'ok' }));

    await api.forgotPassword('a@b.co');
    expect(lastRequest(fetchMock).url).toBe('/api/v1/auth/forgot-password');
    expect(JSON.parse(lastRequest(fetchMock).init.body as string)).toEqual({ email: 'a@b.co' });

    await api.resendVerification('a@b.co');
    expect(lastRequest(fetchMock).url).toBe('/api/v1/auth/resend-verification');

    await api.resetPassword('tok', 'new-pass-1');
    expect(lastRequest(fetchMock).url).toBe('/api/v1/auth/reset-password');
    expect(JSON.parse(lastRequest(fetchMock).init.body as string)).toEqual({ token: 'tok', new_password: 'new-pass-1' });

    await api.verifyEmail('tok');
    expect(lastRequest(fetchMock).url).toBe('/api/v1/auth/verify-email');
    expect(lastRequest(fetchMock).init.method).toBe('POST');
    expect(lastRequest(fetchMock).headers['Content-Type']).toBe('application/json');
  });

  it('builds the audit-log query without empty filters', async () => {
    const { api } = await loadClient(false);
    const fetchMock = stubFetch(() => jsonResponse({ items: [], total: 0, limit: 25, offset: 0 }));

    await api.listAuditLogs({ action: 'auth.', patient_id: '', actor_id: undefined, limit: 25, offset: 0 });
    expect(lastRequest(fetchMock).url).toBe('/api/v1/admin/audit-logs?action=auth.&limit=25&offset=0');

    await api.listAuditLogs({});
    expect(lastRequest(fetchMock).url).toBe('/api/v1/admin/audit-logs');
  });
});
