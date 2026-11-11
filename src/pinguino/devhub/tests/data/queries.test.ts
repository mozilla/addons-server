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

  // The dashboard names the add-on in its activity feed as well as its cards,
  // and the feed is a separate query that nothing else invalidates.
  it('drops the deleted add-on from the cached activity feed', async () => {
    mockDelete([]);
    // The dashboard feed is the all-add-ons infinite activity query (no slug);
    // deleted entries must be dropped from every loaded page.
    const feedKey = ['activity', 'infinite', null] as const;
    queryClient.setQueryData(feedKey, {
      pages: [
        {
          items: [
            { id: '1', addonSlug: 'doomed', addonName: 'Doomed' },
            { id: '2', addonSlug: 'kept', addonName: 'Kept' },
          ],
          total: 3,
        },
        {
          items: [{ id: '3', addonSlug: 'doomed', addonName: 'Doomed' }],
          total: 3,
        },
      ],
      pageParams: [1, 2],
    });

    await removeAddon('doomed');

    const cached = queryClient.getQueryData(feedKey) as {
      pages: { items: { addonSlug: string }[]; total: number }[];
    };
    const slugs = cached.pages.flatMap((p) => p.items.map((u) => u.addonSlug));
    expect(slugs).toEqual(['kept']);
    // Two 'doomed' rows removed, so the server total drops from 3 to 1.
    expect(cached.pages.every((p) => p.total === 1)).toBe(true);
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
