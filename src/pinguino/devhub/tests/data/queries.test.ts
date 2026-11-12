import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Addon, AddonPage } from '../../src/data';
import { queryClient, queryKeys, removeAddon } from '../../src/data';
import { seedAddons } from '../helpers/fixture';

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
    seedAddons(
      [
        { slug: 'doomed', name: 'Doomed', kind: 'extension' },
        { slug: 'kept', name: 'Kept', kind: 'extension' },
      ] as Addon[],
      { extension: 9 },
    );

    await removeAddon('doomed');

    const cached = queryClient.getQueryData(
      queryKeys.addonList('extension'),
    ) as AddonPage;
    expect(cached.results.map((a) => a.slug)).toEqual(['kept']);
    // The author's total drops with it, not just the page we hold.
    expect(cached.count).toBe(8);
  });

  // The dashboard names the add-on in its activity feed as well as its cards,
  // and the feed is a separate query that nothing else invalidates.
  it('drops the deleted add-on from the cached activity feed', async () => {
    mockDelete([]);
    queryClient.setQueryData(queryKeys.updates, [
      { id: '1', addonSlug: 'doomed', addonName: 'Doomed' },
      { id: '2', addonSlug: 'kept', addonName: 'Kept' },
    ]);

    await removeAddon('doomed');

    const cached = queryClient.getQueryData(queryKeys.updates) as {
      addonSlug: string;
    }[];
    expect(cached.map((u) => u.addonSlug)).toEqual(['kept']);
  });

  it('spends the delete token before touching the cache', async () => {
    const fetchMock = mockDelete([]);
    seedAddons([{ slug: 'doomed', kind: 'extension' }] as Addon[]);

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
    expect(
      queryClient.getQueryData(queryKeys.addonList('extension')),
    ).toBeUndefined();
  });
});
