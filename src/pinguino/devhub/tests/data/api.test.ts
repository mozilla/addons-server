import { describe, expect, it, vi } from 'vitest';
import {
  fetchActivity,
  fetchAddons,
  fetchAgreement,
  fetchCategories,
  fetchEulaPolicy,
  fetchProfile,
  fetchUpdates,
  formatDate,
  localized,
  mapActivity,
  mapAddon,
  patchAddon,
  patchEulaPolicy,
  postAgreement,
} from '../../src/data/api';
import { ADDON_STATUS, VERSION_STATUS } from '../../src/data/statuses';

function mockJson(payload: unknown) {
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValue({ ok: true, status: 200, json: async () => payload }),
  );
}

describe('mapAddon', () => {
  it('maps a public static theme to a live theme', () => {
    const addon = mapAddon({
      slug: 'sunset',
      name: { 'en-US': 'Sunset', de: 'Sonnenuntergang' },
      type: 'statictheme',
      status: 'public',
      last_updated: '2025-05-14T10:00:00Z',
      current_version: { version: '3.2.1' },
      previews: [{ image_url: 'https://cdn/preview.png' }],
      channels: ['listed'],
    });

    expect(addon).toMatchObject({
      slug: 'sunset',
      name: 'Sunset', // en-US preferred out of the localized map
      kind: 'theme',
      icon: 'themes',
      status: ADDON_STATUS.public,
      visibility: 'visible',
      version: '3.2.1',
      lastUpdated: 'May 14 2025',
      previewUrl: 'https://cdn/preview.png',
    });
  });

  it('decodes HTML entities in the plain-text fields (name, summary)', () => {
    const addon = mapAddon({
      slug: 'x',
      name: { 'en-US': 'Tom &amp; Jerry' },
      type: 'extension',
      status: 'public',
      summary: { 'en-US': 'A &amp; B &lt; C' },
      channels: ['listed'],
    });
    expect(addon.name).toBe('Tom & Jerry');
    expect(addon.summary).toBe('A & B < C');
  });

  it('treats an author-disabled add-on as invisible and surfaces the raw status label', () => {
    const addon = mapAddon({
      slug: 'grammarly',
      name: { 'en-US': 'Grammarly' },
      type: 'extension',
      status: 'nominated',
      is_disabled: true,
      channels: ['listed'],
    });

    expect(addon).toMatchObject({
      kind: 'extension',
      visibility: 'invisible',
      status: ADDON_STATUS.nominated,
      version: '—', // no current_version
    });
  });

  it('maps the listing-detail fields, resolving outgoing URLs and slugs', () => {
    const addon = mapAddon({
      slug: 'tab-organizer',
      guid: '{tab-organizer-guid}',
      name: { 'en-US': 'Tab Organizer' },
      type: 'extension',
      status: 'public',
      url: 'https://amo.test/addon/tab-organizer',
      summary: { 'en-US': 'Organize tabs' },
      description: null,
      developer_comments: { 'en-US': 'Pure content script.' },
      homepage: {
        url: { 'en-US': 'https://tabs.example' },
        outgoing: { 'en-US': 'https://outgoing.example' },
      },
      support_email: { 'en-US': 'help@tabs.example' },
      average_daily_users: 1597,
      ratings: { average: 3, count: 5 },
      categories: ['alerts-updates', 'tabs'],
      has_eula: true,
      is_experimental: false,
      current_version: {
        version: '1.0',
        license: { name: { 'en-US': 'MPL 2.0' } },
      },
      channels: ['listed'],
    });

    expect(addon).toMatchObject({
      rating: 3,
      reviewCount: 5,
      averageDailyUsers: 1597,
      listingUrl: 'https://amo.test/addon/tab-organizer',
      summary: 'Organize tabs',
      developerComments: 'Pure content script.',
      homepageUrl: 'https://tabs.example',
      supportEmail: 'help@tabs.example',
      categories: ['alerts-updates', 'tabs'],
      flags: { hasEula: true, hasPrivacyPolicy: false, experimental: false },
      license: 'MPL 2.0',
      uuid: '{tab-organizer-guid}',
    });
    // Null/absent fields stay undefined rather than empty strings.
    expect(addon.description).toBeUndefined();
    expect(addon.supportUrl).toBeUndefined();
  });
});

describe('mapActivity', () => {
  it('reads status and channel off the version, not the title text', () => {
    const update = mapActivity({
      id: 42,
      addon: { slug: 'my-addon', name: { 'en-US': 'My Add-on' } },
      title: 'Your version is approved.',
      comments: 'Congrats!',
      date: '2025-09-02T00:00:00Z',
      user: { name: 'Add-ons Review Team' },
      versions: [
        {
          version: '3.2.1',
          channel: 'listed',
          file: { status: 'public' },
          reviewed: '2025-09-01T00:00:00Z',
        },
      ],
    });

    expect(update).toMatchObject({
      id: '42',
      versionStatus: VERSION_STATUS.public,
      channel: 'listed',
      version: '3.2.1',
      date: 'Sep 2 2025',
      user: 'Add-ons Review Team',
      addonName: 'My Add-on',
      addonSlug: 'my-addon',
    });
  });

  it('reports a reviewed, disabled file as rejected', () => {
    const update = mapActivity({
      id: 43,
      addon: {},
      // Title says "approved" — the old regex would have believed it.
      title: 'Version approved',
      versions: [
        {
          version: '1.0',
          file: { status: 'disabled' },
          reviewed: '2025-09-01T00:00:00Z',
        },
      ],
    });
    expect(update.versionStatus?.label).toBe('Rejected');
  });

  it('leaves an activity with no version unstatused', () => {
    const update = mapActivity({
      id: 7,
      addon: {},
      title: 'Add-on disabled',
    });
    expect(update.versionStatus).toBeUndefined();
    expect(update.channel).toBeUndefined();
  });

  it('leaves the user unset when the action had none', () => {
    expect(mapActivity({ id: 8, addon: {}, user: null }).user).toBeUndefined();
  });
});

describe('localized / formatDate', () => {
  it('falls back across localized shapes', () => {
    expect(localized('Plain')).toBe('Plain');
    expect(localized({ fr: 'Bonjour' })).toBe('Bonjour'); // first value, no en-US
    expect(localized(undefined)).toBe('');
  });

  it('returns empty string for missing or invalid dates', () => {
    expect(formatDate(undefined)).toBe('');
    expect(formatDate('not-a-date')).toBe('');
  });
});

describe('endpoints', () => {
  it('fetchAddons maps the paginated envelope through mapAddon', async () => {
    mockJson({
      results: [
        { slug: 'a', name: 'A', type: 'extension', status: 'public' },
        { slug: 't', name: 'T', type: 'statictheme', status: 'public' },
      ],
    });

    const addons = await fetchAddons();
    expect(addons.map((a) => a.kind)).toEqual(['extension', 'theme']);
  });

  it('fetchAddons tolerates a missing results array', async () => {
    mockJson({});
    expect(await fetchAddons()).toEqual([]);
  });

  it('fetchUpdates maps the activity feed through mapActivity', async () => {
    mockJson({
      results: [
        {
          id: 1,
          title: 'Approved!',
          versions: [{ file: { status: 'public' } }],
        },
      ],
    });
    const updates = await fetchUpdates();
    expect(updates).toHaveLength(1);
    expect(updates[0]).toMatchObject({
      id: '1',
      versionStatus: VERSION_STATUS.public,
    });
  });

  it('fetchActivity filters by add-on and pages, reporting the total', async () => {
    mockJson({ results: [{ id: 1, addon: {} }], count: 42 });

    const page = await fetchActivity('my-addon', 3);

    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).toContain('addon=my-addon');
    expect(String(url)).toContain('page=3');
    // The total is the count across all pages, not this page's length.
    expect(page).toMatchObject({ total: 42 });
    expect(page.items).toHaveLength(1);
  });

  it('fetchProfile reads the account name', async () => {
    mockJson({ name: 'Kate' });
    expect(await fetchProfile()).toEqual({ name: 'Kate' });
  });

  it('patchAddon maps domain edit fields to the API body and PATCHes', async () => {
    mockJson({ slug: 'x', name: 'New', type: 'extension', status: 'public' });
    await patchAddon('x', {
      name: 'New',
      homepage: 'https://h.example',
      is_experimental: true,
    });

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe('/api/v5/addons/addon/x/?lang=en-US');
    expect(init?.method).toBe('PATCH');
    expect(JSON.parse(String(init?.body))).toEqual({
      name: { 'en-US': 'New' },
      homepage: { 'en-US': 'https://h.example' },
      is_experimental: true,
    });
  });

  it('patchAddon sends categories as a bare slug array (not localized)', async () => {
    mockJson({ slug: 'x', name: 'X', type: 'extension', status: 'public' });
    await patchAddon('x', { categories: ['bookmarks', 'tabs'] });
    const [, init] = vi.mocked(fetch).mock.calls[0];
    expect(JSON.parse(String(init?.body))).toEqual({
      categories: ['bookmarks', 'tabs'],
    });
  });

  it('fetchCategories returns slug/name/type triples', async () => {
    mockJson([
      { id: 1, name: 'Bookmarks', slug: 'bookmarks', type: 'extension' },
    ]);
    expect(await fetchCategories()).toEqual([
      { slug: 'bookmarks', name: 'Bookmarks', type: 'extension' },
    ]);
  });

  it('fetchEulaPolicy localizes the eula and privacy text', async () => {
    mockJson({ eula: { 'en-US': 'Terms' }, privacy_policy: null });
    expect(await fetchEulaPolicy('x')).toEqual({
      eula: 'Terms',
      privacyPolicy: '',
    });
  });

  it('patchEulaPolicy PATCHes the localized policy fields', async () => {
    mockJson({});
    await patchEulaPolicy('x', { eula: 'New terms', privacyPolicy: '' });
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe('/api/v5/addons/addon/x/eula_policy/?lang=en-US');
    expect(init?.method).toBe('PATCH');
    expect(JSON.parse(String(init?.body))).toEqual({
      eula: { 'en-US': 'New terms' },
      privacy_policy: { 'en-US': '' },
    });
  });

  it('fetchAgreement returns the agreement state as it was fetched', async () => {
    const state = {
      display_name: 'my_display_name',
      last_developer_agreement_change: '2020-01-10T12:00:00',
    };
    mockJson(state);
    expect(await fetchAgreement()).toEqual(state);
  });

  it('postAgreement POSTs to the agreement endpoint', async () => {
    mockJson({});
    const payload = { last_developer_agreement_change: '2020-01-10T12:00:00' };

    await postAgreement(payload);
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe('/api/v5/developers/agreement/');
    expect(init).toMatchObject({
      method: 'POST',
      body: JSON.stringify(payload),
    });
  });
});
