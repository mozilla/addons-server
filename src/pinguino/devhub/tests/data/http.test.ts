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

  it('sends a JSON body with content-type when given', async () => {
    const body = { foo: 'bar' };
    const fetchFn = mockFetch({});
    await apiFetch('/x', { method: 'POST', body: body });

    const [, init] = fetchFn.mock.calls[0];
    expect(init).toMatchObject({
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    });
  });

  it('sends FormData when given', async () => {
    const fetchFn = mockFetch({});
    const body = new FormData();
    body.append('upload', 'x');

    await apiFetch('/x', { method: 'POST', body });

    const [, init] = fetchFn.mock.calls[0];
    expect(init.body).toBe(body);
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

  it('surfaces field-level validation errors in the ApiError message', async () => {
    mockFetch({
      ok: false,
      status: 400,
      json: async () => ({ name: ['This field is required.'] }),
    });

    let caught: unknown;
    try {
      await apiFetch('/addons/addon/x/', { method: 'PATCH', body: {} });
    } catch (e) {
      caught = e;
    }
    expect((caught as ApiError).message).toBe('name: This field is required.');
  });

  it('sends a Session auth header (from the <pinguino-app> token) and custom base', async () => {
    vi.stubEnv('VITE_AMO_API_BASE', 'https://amo.test/api/v5');
    // The token is read from the DOM at module load, so set it up then re-import.
    document.body.innerHTML = '<pinguino-app token="sess-123"></pinguino-app>';
    vi.resetModules();
    const fetchFn = mockFetch({});

    const { apiFetch: freshFetch } = await import('../../src/data/http');
    await freshFetch('/accounts/profile/');

    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe('https://amo.test/api/v5/accounts/profile/');
    expect(init.headers).toEqual({ authorization: 'Session sess-123' });

    // The token is stripped from the DOM so later scripts can't scrape it.
    expect(
      document.querySelector('pinguino-app')?.getAttribute('token'),
    ).toBeNull();
    vi.resetModules();
  });

  it('ignores the unsubstituted placeholder token (no auth header)', async () => {
    document.body.innerHTML =
      '<pinguino-app token="INSERT_TOKEN_HERE"></pinguino-app>';
    vi.resetModules();
    const fetchFn = mockFetch({});

    const { apiFetch: freshFetch } = await import('../../src/data/http');
    await freshFetch('/x');

    const [, init] = fetchFn.mock.calls[0];
    expect(init.headers).toEqual({});
    vi.resetModules();
  });
});
