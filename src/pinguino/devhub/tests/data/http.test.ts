import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const SESSION_PATH = '/accounts/session/';

// Routes the session-id lookup and the actual API call to separate responses so
// tests can assert on each. `sessionId: null` mimics a logged-out 401.
function mockFetch({
  sessionId = null,
  response = {},
}: {
  sessionId?: string | null;
  response?: Partial<Response> & { json?: () => unknown };
} = {}) {
  const fn = vi.fn(async (url: string, _init?: RequestInit) => {
    if (url.endsWith(SESSION_PATH)) {
      return {
        ok: sessionId !== null,
        status: sessionId !== null ? 200 : 401,
        json: async () => ({ session_id: sessionId }),
      };
    }
    return { ok: true, status: 200, json: async () => ({}), ...response };
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

// The call that isn't the session-id lookup, i.e. the request under test.
function apiCall(fetchFn: ReturnType<typeof mockFetch>): [string, RequestInit] {
  const call = fetchFn.mock.calls.find(([url]) => !url.endsWith(SESSION_PATH));
  if (!call) throw new Error('no API call was recorded');
  return [call[0], call[1] ?? {}];
}

// http.ts memoises the session id at module scope (once per page load), so each
// test gets a fresh module to stay isolated.
async function freshApiFetch() {
  vi.resetModules();
  return (await import('../../src/data/http')).apiFetch;
}

describe('apiFetch', () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('hits the default base URL and returns parsed JSON', async () => {
    const fetchFn = mockFetch({ response: { json: async () => ({ ok: 1 }) } });
    const apiFetch = await freshApiFetch();

    const data = await apiFetch<{ ok: number }>('/addons/addon/');

    expect(data).toEqual({ ok: 1 });
    expect(apiCall(fetchFn)[0]).toBe('/api/v5/addons/addon/');
  });

  it('sends a Session auth header built from the fetched session id', async () => {
    const fetchFn = mockFetch({ sessionId: 'sess-123' });
    const apiFetch = await freshApiFetch();

    await apiFetch('/accounts/profile/');

    const [, init] = apiCall(fetchFn);
    expect(init.headers).toEqual({ authorization: 'Session sess-123' });
  });

  it('sends no auth header when logged out (session endpoint 401s)', async () => {
    const fetchFn = mockFetch({ sessionId: null });
    const apiFetch = await freshApiFetch();

    await apiFetch('/x');

    const [, init] = apiCall(fetchFn);
    expect(init.headers).toEqual({});
  });

  it('fetches the session id once per page load, shared across calls', async () => {
    const fetchFn = mockFetch({ sessionId: 'sess-123' });
    const apiFetch = await freshApiFetch();

    await Promise.all([apiFetch('/a'), apiFetch('/b'), apiFetch('/c')]);

    const sessionCalls = fetchFn.mock.calls.filter(([url]) =>
      url.endsWith(SESSION_PATH),
    );
    expect(sessionCalls).toHaveLength(1);
    expect(sessionCalls[0][0]).toBe(`/api/v5${SESSION_PATH}`);
  });

  it('sends a JSON body with content-type when given', async () => {
    const body = { foo: 'bar' };
    const fetchFn = mockFetch({ sessionId: 'sess-123' });
    const apiFetch = await freshApiFetch();

    await apiFetch('/x', { method: 'POST', body });

    const [, init] = apiCall(fetchFn);
    expect(init).toMatchObject({
      method: 'POST',
      headers: {
        authorization: 'Session sess-123',
        'content-type': 'application/json',
      },
      body: JSON.stringify(body),
    });
  });

  it('throws a typed ApiError carrying the status on a failed response', async () => {
    mockFetch({ response: { ok: false, status: 404 } });
    const apiFetch = await freshApiFetch();

    let caught: unknown;
    try {
      await apiFetch('/missing');
    } catch (e) {
      caught = e;
    }
    const { ApiError } = await import('../../src/data/http');
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as InstanceType<typeof ApiError>).status).toBe(404);
  });

  it('uses a custom base URL when configured', async () => {
    vi.stubEnv('VITE_AMO_API_BASE', 'https://amo.test/api/v5');
    const fetchFn = mockFetch({ sessionId: 'sess-123' });
    const apiFetch = await freshApiFetch();

    await apiFetch('/accounts/profile/');

    expect(apiCall(fetchFn)[0]).toBe(
      'https://amo.test/api/v5/accounts/profile/',
    );
  });
});
