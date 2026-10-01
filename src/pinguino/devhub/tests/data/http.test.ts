import { describe, expect, it, vi } from 'vitest';
import { ApiError, apiFetch } from '../../src/data/http';

function mockFetch(response: Partial<Response> & { json?: () => unknown }) {
  const fn = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({}),
    ...response,
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

describe('apiFetch', () => {
  it('hits the default base URL and returns parsed JSON', async () => {
    const fetchFn = mockFetch({ json: async () => ({ ok: 1 }) });

    const data = await apiFetch<{ ok: number }>('/addons/addon/');

    expect(data).toEqual({ ok: 1 });
    expect(fetchFn).toHaveBeenCalledWith(
      '/api/v5/addons/addon/',
      expect.anything(),
    );
  });

  it('sends no auth header when no session is configured', async () => {
    const fetchFn = mockFetch({});
    await apiFetch('/x');
    const [, init] = fetchFn.mock.calls[0];
    expect(init.headers).toEqual({});
  });

  it('throws a typed ApiError carrying the status on a failed response', async () => {
    mockFetch({ ok: false, status: 404 });

    let caught: unknown;
    try {
      await apiFetch('/missing');
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(404);
  });

  it('sends a Session auth header and custom base when configured', async () => {
    vi.stubEnv('VITE_AMO_SESSION_ID', 'sess-123');
    vi.stubEnv('VITE_AMO_API_BASE', 'https://amo.test/api/v5');
    vi.resetModules();
    const fetchFn = mockFetch({});

    const { apiFetch: freshFetch } = await import('../../src/data/http');
    await freshFetch('/accounts/profile/');

    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe('https://amo.test/api/v5/accounts/profile/');
    expect(init.headers).toEqual({ authorization: 'Session sess-123' });
    vi.resetModules();
  });
});
