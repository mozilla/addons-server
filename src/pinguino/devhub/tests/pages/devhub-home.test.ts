import { describe, expect, it, vi } from 'vitest';
import type { DevhubHome } from '../../src/pages/devhub-home';
import '../../src/pages/devhub-home';
import type { Addon, Update } from '../../src/data';
import {
  ADDON_STATUS,
  queryClient,
  queryKeys,
  VERSION_STATUS,
} from '../../src/data';
import { mount, settle } from '../helpers/fixture';

// Seeded cache data is fresh, so the query controllers read it on first paint
// without refetching.
const ext = (slug: string): Addon => ({
  slug,
  name: slug,
  kind: 'extension',
  icon: 'extension',
  status: ADDON_STATUS.public,
  version: '1.0.0',
  lastUpdated: 'Aug 18 2025',
  visibility: 'visible',
  canChangeVisibility: true,
  channels: ['listed'],
});
const theme = (slug: string): Addon => ({
  ...ext(slug),
  kind: 'theme',
  icon: 'themes',
});

const update: Update = {
  id: 'u1',
  title: 'Approved',
  message: 'Congrats!',
  version: '1.0.0',
  versionStatus: VERSION_STATUS.public,
  addonName: 'Ad Blocker',
  channel: 'listed',
  date: 'Sep 2 2025',
  user: 'Kate',
  addonSlug: 'a',
};

function seed(addons: Addon[], updates: Update[]) {
  queryClient.setQueryData(queryKeys.profile, { name: 'Kate' });
  queryClient.setQueryData(queryKeys.addons, addons);
  // The dashboard feed is the all-add-ons infinite activity query (no slug); its
  // cache holds an InfiniteData of ActivityPages.
  queryClient.setQueryData(['activity', 'infinite', null], {
    pages: [{ items: updates, total: updates.length }],
    pageParams: [1],
  });
}

const text = (el: Element | null) =>
  el?.textContent?.replace(/\s+/g, ' ').trim();

describe('devhub-home', () => {
  it('groups add-ons by kind with per-group counts and a submit card each', async () => {
    seed([ext('a'), ext('b'), theme('t')], []);
    const el = await mount<DevhubHome>('devhub-home');
    await settle(el);
    const root = el.shadowRoot as ShadowRoot;

    const counts = [...root.querySelectorAll('.count')].map(text);
    expect(counts).toContain('2 Extensions');
    expect(counts).toContain('1 Themes');

    expect(root.querySelectorAll('addon-card')).toHaveLength(3);
    expect(root.querySelectorAll('submit-card')).toHaveLength(2); // one per group
  });

  it('shows the empty-updates illustration when the feed is empty', async () => {
    seed([ext('a')], []);
    const el = await mount<DevhubHome>('devhub-home');
    await settle(el);
    const root = el.shadowRoot as ShadowRoot;

    expect(
      root.querySelector('.empty-updates moz-illustration'),
    ).not.toBeNull();
    expect(root.querySelectorAll('update-card')).toHaveLength(0);
  });

  it('renders an update-card per feed entry when the feed is populated', async () => {
    seed([ext('a')], [update, { ...update, id: 'u2' }]);
    const el = await mount<DevhubHome>('devhub-home');
    await settle(el);
    const root = el.shadowRoot as ShadowRoot;

    expect(root.querySelectorAll('update-card')).toHaveLength(2);
    expect(root.querySelector('.empty-updates')).toBeNull();
  });

  it('counts the server total, not just the rows loaded so far', async () => {
    // Two rows loaded, but the server reports 50 in total.
    queryClient.setQueryData(queryKeys.profile, { name: 'Kate' });
    queryClient.setQueryData(queryKeys.addons, [ext('a')]);
    queryClient.setQueryData(['activity', 'infinite', null], {
      pages: [{ items: [update, { ...update, id: 'u2' }], total: 50 }],
      pageParams: [1],
    });
    const el = await mount<DevhubHome>('devhub-home');
    await settle(el);
    const root = el.shadowRoot as ShadowRoot;

    expect(text(root.querySelector('.feed .count'))).toBe('50 Updates');
  });

  // The feed is virtualized infinite scroll: as the last loaded rows come into
  // view it pulls the next page, provided the server has more.
  it('fetches the next page when the end of the feed scrolls into view', async () => {
    // One page loaded, but the server reports more rows than are loaded.
    queryClient.setQueryData(queryKeys.profile, { name: 'Kate' });
    queryClient.setQueryData(queryKeys.addons, [ext('a')]);
    queryClient.setQueryData(['activity', 'infinite', null], {
      pages: [{ items: [update], total: 2 }],
      pageParams: [1],
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
    vi.stubGlobal('fetch', fetchMock);

    const el = await mount<DevhubHome>('devhub-home');
    await settle(el);
    const root = el.shadowRoot as ShadowRoot;

    const event = new Event('visibilityChanged');
    // Last visible row is the final loaded one, so the threshold is crossed.
    (event as Event & { last: number }).last = 0;
    root.querySelector('lit-virtualizer')?.dispatchEvent(event);

    await settle(el);
    const fetchedPage2 = fetchMock.mock.calls.some(([url]) =>
      String(url).includes('page=2'),
    );
    expect(fetchedPage2).toBe(true);
  });

  it('does not page past the last entry', async () => {
    // Everything the server has is already loaded: total matches the row count.
    queryClient.setQueryData(queryKeys.profile, { name: 'Kate' });
    queryClient.setQueryData(queryKeys.addons, [ext('a')]);
    queryClient.setQueryData(['activity', 'infinite', null], {
      pages: [{ items: [update], total: 1 }],
      pageParams: [1],
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
    vi.stubGlobal('fetch', fetchMock);

    const el = await mount<DevhubHome>('devhub-home');
    await settle(el);
    const root = el.shadowRoot as ShadowRoot;

    const event = new Event('visibilityChanged');
    (event as Event & { last: number }).last = 0;
    root.querySelector('lit-virtualizer')?.dispatchEvent(event);

    await settle(el);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('greets the signed-in developer by name in the header', async () => {
    seed([ext('a')], []);
    const el = await mount<DevhubHome>('devhub-home');
    await settle(el);
    const root = el.shadowRoot as ShadowRoot;

    expect(root.querySelector('moz-page-header')?.getAttribute('heading')).toBe(
      'Welcome to the Developer Hub, Kate',
    );
  });

  it('shows only the submit card in an empty group', async () => {
    seed([], []);
    const el = await mount<DevhubHome>('devhub-home');
    await settle(el);
    const root = el.shadowRoot as ShadowRoot;

    const counts = [...root.querySelectorAll('.count')].map(text);
    expect(counts).toContain('0 Extensions');
    expect(counts).toContain('0 Themes');
    expect(root.querySelectorAll('addon-card')).toHaveLength(0);
    expect(root.querySelectorAll('submit-card')).toHaveLength(2);
  });
});
