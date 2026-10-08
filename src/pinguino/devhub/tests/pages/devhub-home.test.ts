import { describe, expect, it } from 'vitest';
import type { DevhubHome } from '../../src/pages/devhub-home';
import '../../src/pages/devhub-home';
import type { Addon, Update } from '../../src/data';
import { queryClient, queryKeys } from '../../src/data';
import { mount, settle } from '../helpers/fixture';

// Seeded cache data is fresh, so the query controllers read it on first paint
// without refetching.
const ext = (slug: string): Addon => ({
  slug,
  name: slug,
  kind: 'extension',
  icon: 'extension',
  statusLabel: 'Live add-on',
  version: '1.0.0',
  lastUpdated: 'Aug 18 2025',
  visibility: 'live',
  distribution: 'amo',
});
const theme = (slug: string): Addon => ({
  ...ext(slug),
  kind: 'theme',
  icon: 'themes',
});

const update: Update = {
  id: 'u1',
  approved: true,
  title: 'Approved',
  message: 'Congrats!',
  version: '1.0.0',
  versionStatus: 'Approved',
  tags: ['Live'],
  date: 'Sep 2 2025',
};

function seed(addons: Addon[], updates: Update[]) {
  queryClient.setQueryData(queryKeys.profile, { name: 'Kate' });
  queryClient.setQueryData(queryKeys.addons, addons);
  queryClient.setQueryData(queryKeys.updates, updates);
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
