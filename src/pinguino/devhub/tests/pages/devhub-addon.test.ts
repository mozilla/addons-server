import { describe, expect, it, vi } from 'vitest';
import type { DevhubAddon } from '../../src/pages/addon/templates/devhub-addon';
import '../../src/pages/addon/templates/devhub-addon';
import type { Addon } from '../../src/data';
import { ADDON_STATUS, queryClient, queryKeys } from '../../src/data';
import { DEFAULT_VERSION, mount, seedAddons, settle } from '../helpers/fixture';

const addon: Addon = {
  slug: 'ad-blocker',
  name: 'Ad Blocker',
  kind: 'extension',
  icon: 'extension',
  status: ADDON_STATUS.public,
  lastUpdated: 'Aug 18 2025',
  visibility: 'visible',
  canChangeVisibility: true,
  channels: ['listed'],
};

// The page fetches authors and categories too; report only add-on requests.
function mockDetail(response: object) {
  const calls = { detail: [] as string[], list: [] as string[] };
  const fetchMock = vi.fn(async (url: string) => {
    const href = String(url);
    if (/\/addons\/addon\/\?/.test(href)) calls.list.push(href);
    else if (/\/addons\/addon\/[^/]+\/\?/.test(href)) calls.detail.push(href);
    return response;
  });
  vi.stubGlobal('fetch', fetchMock);
  return calls;
}

describe('devhub-addon', () => {
  it('defaults to the listing editor tab and renders the shell', async () => {
    seedAddons([addon]);
    const el = await mount<DevhubAddon>('devhub-addon', { slug: 'ad-blocker' });
    await settle(el);
    const root = el.shadowRoot as ShadowRoot;

    const header = root.querySelector('addon-manage-header');
    expect((header as unknown as { addon: Addon })?.addon.name).toBe(
      'Ad Blocker',
    );

    const tabs = [...root.querySelectorAll('moz-segmented-control-item')].map(
      (t) => t.getAttribute('value'),
    );
    expect(tabs).toEqual(['versions', 'feed', 'edit', 'statistics']);
    expect(
      root.querySelector('moz-segmented-control')?.getAttribute('value'),
    ).toBe('edit');
    expect(root.querySelector('addon-listing')).not.toBeNull();
  });

  it('stubs (not the listing) for a non-edit tab', async () => {
    seedAddons([addon]);
    const el = await mount<DevhubAddon>('devhub-addon', {
      slug: 'ad-blocker',
      tab: 'statistics',
    });
    await settle(el);
    const root = el.shadowRoot as ShadowRoot;

    expect(
      root.querySelector('moz-segmented-control')?.getAttribute('value'),
    ).toBe('statistics');
    expect(root.querySelector('addon-listing')).toBeNull();
    expect(root.querySelector('coming-soon')).not.toBeNull();
  });

  it('renders the versions panel for the add-on on the versions tab', async () => {
    seedAddons([addon]);
    queryClient.setQueryData([...queryKeys.versions('ad-blocker'), 1], {
      items: [DEFAULT_VERSION],
      total: 1,
    });
    const el = await mount<DevhubAddon>('devhub-addon', {
      slug: 'ad-blocker',
      tab: 'versions',
    });
    await settle(el);
    const root = el.shadowRoot as ShadowRoot;

    const panel = root.querySelector('addon-version');
    expect(panel?.addon.slug).toBe('ad-blocker');
    expect(root.querySelector('addon-listing')).toBeNull();
    expect(root.querySelector('coming-soon')).toBeNull();
  });

  it('stubs an unimplemented Django tab', async () => {
    seedAddons([addon]);
    const el = await mount<DevhubAddon>('devhub-addon', {
      slug: 'ad-blocker',
      tab: 'invitation',
    });
    await settle(el);
    const root = el.shadowRoot as ShadowRoot;

    expect(root.querySelector('coming-soon')).not.toBeNull();
    expect(root.querySelector('addon-listing')).toBeNull();
  });

  it('selecting a tab navigates to its sub-URL', async () => {
    seedAddons([addon]);
    const el = await mount<DevhubAddon>('devhub-addon', { slug: 'ad-blocker' });
    await settle(el);
    const root = el.shadowRoot as ShadowRoot;

    root.querySelector('moz-segmented-control')?.dispatchEvent(
      new CustomEvent('moz-segmented-control:change', {
        detail: { value: 'statistics' },
      }),
    );
    expect(location.pathname).toBe('/developers/addon/ad-blocker/statistics');
  });

  it('fetches an add-on missing from the cached lists', async () => {
    const calls = mockDetail({
      ok: true,
      status: 200,
      json: async () => ({
        slug: 'hidden-gem',
        name: { 'en-US': 'Hidden Gem' },
        type: 'extension',
        status: 'public',
        channels: ['listed'],
      }),
    });
    seedAddons([addon]);

    const el = await mount<DevhubAddon>('devhub-addon', { slug: 'hidden-gem' });
    await vi.waitFor(async () => {
      await settle(el);
      const header = (el.shadowRoot as ShadowRoot).querySelector(
        'addon-manage-header',
      );
      expect((header as unknown as { addon: Addon })?.addon.name).toBe(
        'Hidden Gem',
      );
    });
    expect(calls.detail).toHaveLength(1);
    expect(calls.detail[0]).toContain('/addons/addon/hidden-gem/');
    expect(calls.list).toEqual([]);
  });

  it('asks for nothing when the slug is already in the cached lists', async () => {
    const calls = mockDetail({
      ok: true,
      status: 200,
      json: async () => ({}),
    });
    seedAddons([addon]);

    const el = await mount<DevhubAddon>('devhub-addon', { slug: 'ad-blocker' });
    await settle(el);

    expect(calls.detail).toEqual([]);
    expect(calls.list).toEqual([]);
  });

  it('shows a not-found message when the API has no such add-on either', async () => {
    mockDetail({ ok: false, status: 404, json: async () => ({}) });
    seedAddons([addon]);

    const el = await mount<DevhubAddon>('devhub-addon', { slug: 'unknown' });
    await vi.waitFor(async () => {
      await settle(el);
      expect(el.shadowRoot?.textContent).toContain("couldn't find that add-on");
    });
    expect(el.shadowRoot?.querySelector('addon-manage-header')).toBeNull();
  });
});

describe('devhub-addon page title', () => {
  async function titleFor(props: Partial<DevhubAddon>): Promise<string> {
    seedAddons([addon]);
    const el = await mount<DevhubAddon>('devhub-addon', {
      slug: 'ad-blocker',
      ...props,
    });
    await settle(el);
    return document.title;
  }

  it('titles the edit tab "Edit Listing details" under the add-on name', async () => {
    expect(await titleFor({})).toBe(
      'Edit Listing details :: Ad Blocker :: Add-ons for Firefox',
    );
  });

  it('titles the edit tab by its active section', async () => {
    expect(await titleFor({ tab: 'edit', section: 'authors' })).toBe(
      'Edit Authors :: Ad Blocker :: Add-ons for Firefox',
    );
  });

  it('passes the page parameter to the versions panel', async () => {
    seedAddons([addon]);
    const el = await mount<DevhubAddon>('devhub-addon', {
      slug: 'ad-blocker',
      tab: 'versions',
      page: 2,
    });
    await settle(el);
    const root = el.shadowRoot as ShadowRoot;

    expect(root.querySelector('addon-version')?.page).toBe(2);
  });

  it('titles the versions tab', async () => {
    queryClient.setQueryData([...queryKeys.versions('ad-blocker'), 1], {
      items: [DEFAULT_VERSION],
      total: 1,
    });
    expect(await titleFor({ tab: 'versions' })).toBe(
      'Versions :: Ad Blocker :: Add-ons for Firefox',
    );
  });

  it('titles the feed tab', async () => {
    expect(await titleFor({ tab: 'feed' })).toBe(
      'Activity & Notification :: Ad Blocker :: Add-ons for Firefox',
    );
  });

  it('drops the page segment for a not-yet-implemented tab', async () => {
    expect(await titleFor({ tab: 'statistics' })).toBe(
      'Ad Blocker :: Add-ons for Firefox',
    );
  });

  it('drops the page segment for a non-TabValue tab too (e.g. invitation)', async () => {
    // invitation isn't a real tab, so it must behave like statistics rather
    // than inheriting the edit title via the #activeTab fallback.
    expect(await titleFor({ tab: 'invitation' })).toBe(
      'Ad Blocker :: Add-ons for Firefox',
    );
  });
});

describe('devhub-addon feed tab', () => {
  it('renders the activity feed for the add-on and page', async () => {
    seedAddons([addon]);
    const el = await mount<DevhubAddon>('devhub-addon', {
      slug: 'ad-blocker',
      tab: 'feed',
      page: 2,
    });
    await settle(el);

    const feed = (el.shadowRoot as ShadowRoot).querySelector('activity-feed');
    expect(feed).not.toBeNull();
    expect((feed as unknown as { slug: string; page: number }).slug).toBe(
      'ad-blocker',
    );
    expect((feed as unknown as { slug: string; page: number }).page).toBe(2);
  });
});
