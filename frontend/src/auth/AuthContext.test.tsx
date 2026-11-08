import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api, getToken, setToken } from '../api/client';
import { jsonResponse, makeUser } from '../test/helpers';
import { AuthProvider, homePathForRole, useAuth } from './AuthContext';

function Probe() {
  const auth = useAuth();
  const attempt = (action: () => Promise<unknown>) => () => void action().catch(() => undefined);
  return (
    <div>
      <span data-testid="state">
        {auth.loading ? 'loading' : auth.user ? `user:${auth.user.full_name}` : 'anonymous'}
      </span>
      <button onClick={attempt(() => auth.login('pat@example.com', 'password123'))}>login</button>
      <button onClick={auth.logout}>logout</button>
      <button onClick={attempt(() => auth.changePassword('old-pass', 'new-pass-1'))}>change</button>
    </div>
  );
}

function renderProvider() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
}

const state = () => screen.getByTestId('state').textContent;

describe('restoring a session on load', () => {
  it('is anonymous without a stored token, and never calls the API', async () => {
    const me = vi.spyOn(api, 'me');
    renderProvider();
    await waitFor(() => expect(state()).toBe('anonymous'));
    expect(me).not.toHaveBeenCalled();
  });

  it('restores the user when the stored token is still valid', async () => {
    setToken('tok');
    vi.spyOn(api, 'me').mockResolvedValue(makeUser({ full_name: 'Restored Rita' }));
    renderProvider();
    await waitFor(() => expect(state()).toBe('user:Restored Rita'));
  });

  it('drops a token the backend no longer accepts', async () => {
    setToken('stale');
    vi.spyOn(api, 'me').mockRejectedValue(new Error('401'));
    renderProvider();
    await waitFor(() => expect(state()).toBe('anonymous'));
    expect(getToken()).toBeNull();
  });
});

describe('signing in and out', () => {
  async function signedIn() {
    vi.spyOn(api, 'login').mockResolvedValue({
      access_token: 'issued-token',
      token_type: 'bearer',
      user: makeUser({ full_name: 'Pat' }),
    });
    renderProvider();
    await waitFor(() => expect(state()).toBe('anonymous'));
    await userEvent.setup().click(screen.getByText('login'));
    await waitFor(() => expect(state()).toBe('user:Pat'));
  }

  it('stores the token and the user on login', async () => {
    await signedIn();
    expect(getToken()).toBe('issued-token');
  });

  it('revokes the token on the server, then clears it locally, on logout', async () => {
    await signedIn();
    const logout = vi.spyOn(api, 'logout').mockResolvedValue(undefined);

    await userEvent.setup().click(screen.getByText('logout'));

    expect(logout).toHaveBeenCalledTimes(1);
    expect(state()).toBe('anonymous');
    expect(getToken()).toBeNull();
  });

  it('still signs out locally when the revoke request fails', async () => {
    await signedIn();
    vi.spyOn(api, 'logout').mockRejectedValue(new Error('offline'));

    await userEvent.setup().click(screen.getByText('logout'));

    expect(state()).toBe('anonymous');
    expect(getToken()).toBeNull();
  });

  it('does not call the API to log out when there is no session', async () => {
    const logout = vi.spyOn(api, 'logout');
    renderProvider();
    await waitFor(() => expect(state()).toBe('anonymous'));

    await userEvent.setup().click(screen.getByText('logout'));

    expect(logout).not.toHaveBeenCalled();
  });
});

describe('changing the password', () => {
  it('swaps in the fresh token so this session carries on', async () => {
    setToken('before-change');
    vi.spyOn(api, 'me').mockResolvedValue(makeUser({ full_name: 'Pat' }));
    const change = vi.spyOn(api, 'changePassword').mockResolvedValue({
      access_token: 'after-change',
      token_type: 'bearer',
      user: makeUser({ full_name: 'Pat Renamed' }),
    });
    renderProvider();
    await waitFor(() => expect(state()).toBe('user:Pat'));

    await userEvent.setup().click(screen.getByText('change'));

    await waitFor(() => expect(state()).toBe('user:Pat Renamed'));
    expect(change).toHaveBeenCalledWith({ current_password: 'old-pass', new_password: 'new-pass-1' });
    expect(getToken()).toBe('after-change');
  });
});

describe('a session revoked behind the app\'s back', () => {
  it('drops the user as soon as any request is refused with 401', async () => {
    setToken('tok');
    vi.spyOn(api, 'me').mockResolvedValueOnce(makeUser({ full_name: 'Pat' }));
    renderProvider();
    await waitFor(() => expect(state()).toBe('user:Pat'));

    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'This session has been signed out.' }, 401)));
    vi.mocked(api.me).mockRestore();
    await act(async () => {
      await api.me().catch(() => undefined);
    });

    await waitFor(() => expect(state()).toBe('anonymous'));
  });
});

describe('homePathForRole', () => {
  it.each([
    ['ADMIN', '/admin'],
    ['DOCTOR', '/doctor'],
    ['PATIENT', '/patient'],
  ] as const)('%s lands on %s', (role, path) => {
    expect(homePathForRole(role)).toBe(path);
  });
});
