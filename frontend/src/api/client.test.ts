import { describe, expect, it, vi } from 'vitest';
import { jsonResponse } from '../test/helpers';

// Generated per run (a function call, not a literal): there is no credential in this file.
const NEW_PASSWORD = crypto.randomUUID();

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

    await api.resetPassword('tok', NEW_PASSWORD);
    expect(lastRequest(fetchMock).url).toBe('/api/v1/auth/reset-password');
    expect(JSON.parse(lastRequest(fetchMock).init.body as string)).toEqual({ token: 'tok', new_password: NEW_PASSWORD });

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

describe('appointment lists', () => {
  it('asks for one page and reads the total from X-Total-Count', async () => {
    const { api } = await loadClient(false);
    const fetchMock = stubFetch(
      () =>
        new Response(JSON.stringify([{ id: 'a26' }, { id: 'a27' }]), {
          status: 200,
          headers: { 'Content-Type': 'application/json', 'X-Total-Count': '27' },
        }),
    );

    const page = await api.listAppointmentsPage({ status: 'CONFIRMED', limit: 25, offset: 25 });

    expect(lastRequest(fetchMock).url).toBe('/api/v1/appointments?status=CONFIRMED&limit=25&offset=25');
    expect(page.items.map((a) => a.id)).toEqual(['a26', 'a27']);
    expect(page.total).toBe(27);
  });

  it('falls back to the page length when the total header is missing', async () => {
    const { api } = await loadClient(false);
    stubFetch(() => jsonResponse([{ id: 'a1' }]));
    const page = await api.listAppointmentsPage({ limit: 25, offset: 0 });
    expect(page.total).toBe(1);
  });

  it('can ask only for appointments from a given time', async () => {
    const { api } = await loadClient(false);
    const fetchMock = stubFetch(() => jsonResponse([]));
    await api.listAppointments({ from: '2030-01-07T09:00:00.000Z' });
    expect(lastRequest(fetchMock).url).toBe('/api/v1/appointments?from=2030-01-07T09%3A00%3A00.000Z');
  });

  it('sends booking notes and a cancellation reason', async () => {
    const { api } = await loadClient(false);
    const fetchMock = stubFetch(() => jsonResponse({ id: 'a1' }));

    await api.createAppointment({ doctor_id: 'd1', hold_id: 'h1', notes: 'Wheelchair access please' });
    expect(JSON.parse(lastRequest(fetchMock).init.body as string)).toEqual({
      doctor_id: 'd1', hold_id: 'h1', notes: 'Wheelchair access please',
    });

    await api.cancelAppointment('a1', 'Feeling better');
    expect(lastRequest(fetchMock).url).toBe('/api/v1/appointments/a1/cancel');
    expect(JSON.parse(lastRequest(fetchMock).init.body as string)).toEqual({ cancellation_reason: 'Feeling better' });
  });
});

describe('when the server is busy', () => {
  function busy(retryAfter = '1') {
    return new Response(
      JSON.stringify({ detail: 'The server is busy right now. Please try again in a moment.', error_code: 'SERVER_BUSY' }),
      { status: 503, headers: { 'Content-Type': 'application/json', 'Retry-After': retryAfter } },
    );
  }

  /** Answers with each response in turn, then keeps repeating the last one. */
  function sequence(...responses: (() => Response)[]) {
    let i = 0;
    return stubFetch(() => responses[Math.min(i++, responses.length - 1)]());
  }

  it('waits for Retry-After and sends the request again', async () => {
    vi.useFakeTimers();
    try {
      const { api } = await loadClient(false);
      const fetchMock = sequence(() => busy('2'), () => jsonResponse({ id: 'u1' }));

      const result = api.me();
      await vi.advanceTimersByTimeAsync(1_900);
      expect(fetchMock).toHaveBeenCalledTimes(1); // still waiting out the 2 s
      await vi.advanceTimersByTimeAsync(700); // 2 s plus at most 0.5 s jitter

      await expect(result).resolves.toEqual({ id: 'u1' });
      expect(fetchMock).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('retries a POST too, because a busy request never reached the endpoint', async () => {
    vi.useFakeTimers();
    try {
      const { api } = await loadClient(false);
      const fetchMock = sequence(busy, () => jsonResponse({ id: 'a1' }, 201));

      const result = api.createAppointment({ doctor_id: 'd1', start_time: 's', end_time: 'e' });
      await vi.advanceTimersByTimeAsync(2_000);

      await expect(result).resolves.toEqual({ id: 'a1' });
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(lastRequest(fetchMock).init.method).toBe('POST');
    } finally {
      vi.useRealTimers();
    }
  });

  it('gives up after two retries and shows the busy message', async () => {
    vi.useFakeTimers();
    try {
      const { api, ApiError, BUSY_RETRIES } = await loadClient(false);
      const fetchMock = sequence(busy);

      const result = api.me().catch((e) => e);
      await vi.advanceTimersByTimeAsync(10_000);
      const error = await result;

      expect(error).toBeInstanceOf(ApiError);
      expect(error.status).toBe(503);
      expect(error.errorCode).toBe('SERVER_BUSY');
      expect(error.message).toBe('The server is busy right now. Please try again in a moment.');
      expect(fetchMock).toHaveBeenCalledTimes(1 + BUSY_RETRIES);
    } finally {
      vi.useRealTimers();
    }
  });

  it('caps a long Retry-After at 5 seconds', async () => {
    vi.useFakeTimers();
    try {
      const { api } = await loadClient(false);
      const fetchMock = sequence(() => busy('120'), () => jsonResponse({ id: 'u1' }));

      const result = api.me();
      await vi.advanceTimersByTimeAsync(5_600);

      await expect(result).resolves.toEqual({ id: 'u1' });
      expect(fetchMock).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('does not retry a 503 that is not the busy signal', async () => {
    const { api } = await loadClient(false);
    const fetchMock = stubFetch(() => jsonResponse({ detail: 'Service Unavailable' }, 503));

    const error = await api.me().catch((e) => e);

    expect(error.status).toBe(503);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
