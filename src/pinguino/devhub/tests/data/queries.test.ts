import { beforeEach, describe, expect, it, vi } from 'vitest';
import { queryClient, queryKeys, removeAddon } from '../../src/data';

function mockDelete(listAfter: unknown[]) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (String(url).includes('delete_confirm/')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ delete_confirm: 'tok' }),
      };
    }
    if (init?.method === 'DELETE') {
      return { ok: true, status: 204, json: async () => ({}) };
    }
    return {
      ok: true,
      status: 200,
      json: async () => ({ results: listAfter }),
    };
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('removeAddon', () => {
  beforeEach(() => queryClient.clear());

  // Invalidating only refetches active observers, and the manage view unmounts
  // as the delete resolves — so without the explicit eviction the dashboard
  // renders the add-on we just deleted.
  it('leaves the cached list without the deleted add-on', async () => {
    mockDelete([{ slug: 'kept', name: 'Kept', type: 'extension' }]);
    queryClient.setQueryData(queryKeys.addons, [
      { slug: 'doomed', name: 'Doomed' },
      { slug: 'kept', name: 'Kept' },
    ]);

    await removeAddon('doomed');

    const cached = queryClient.getQueryData(queryKeys.addons) as {
      slug: string;
    }[];
    expect(cached.map((a) => a.slug)).toEqual(['kept']);
  });

  it('spends the delete token before touching the cache', async () => {
    const fetchMock = mockDelete([]);
    queryClient.setQueryData(queryKeys.addons, [{ slug: 'doomed' }]);

    await removeAddon('doomed');

    expect(
      fetchMock.mock.calls.map((c) => `${c[1]?.method ?? 'GET'} ${c[0]}`),
    ).toEqual([
      'GET /api/v5/addons/addon/doomed/delete_confirm/',
      'DELETE /api/v5/addons/addon/doomed/?delete_confirm=tok',
    ]);
  });

  it('keeps an empty cache empty rather than inventing a list', async () => {
    mockDelete([]);
    await removeAddon('doomed');
    expect(queryClient.getQueryData(queryKeys.addons)).toBeUndefined();
  });
});
