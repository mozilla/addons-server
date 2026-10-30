import { describe, expect, it, vi } from 'vitest';
import {
  clearTranslations,
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
  patchVersion,
  postAgreement,
  postUpload,
  postVersion,
} from '../../src/data/api';
import { ADDON_STATUS, VERSION_STATUS } from '../../src/data/statuses';
import { DEFAULT_VERSION } from '../helpers/fixture';

function mockJson(payload: unknown) {
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValue({ ok: true, status: 200, json: async () => payload }),
  );
}

const lastCall = () => vi.mocked(fetch).mock.calls[0];

describe('mapAddon', () => {
  it('maps a public static theme to a live theme', () => {
    const addon = mapAddon({
      slug: 'sunset',
      name: { 'en-US': 'Sunset', de: 'Sonnenuntergang' },
      type: 'statictheme',
      status: 'public',
      last_updated: '2025-05-14T10:00:00Z',
      current_version: { ...DEFAULT_VERSION, version: '3.2.1' },
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
        ...DEFAULT_VERSION,
        version: '1.0',
        license: {
          id: 1,
          is_custom: false,
          name: { 'en-US': 'MPL 2.0' },
          url: null,
        },
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
  it('infers approval from the title and sets a matching status', () => {
    const update = mapActivity({
      id: 42,
      addon: { slug: 'my-addon' },
      title: 'Your version is approved.',
      comments: 'Congrats!',
      date: '2025-09-02T00:00:00Z',
      versions: [{ version: '3.2.1' }],
    });

    expect(update).toMatchObject({
      id: '42',
      versionStatus: VERSION_STATUS.public,
      version: '3.2.1',
      date: 'Sep 2 2025',
      addonSlug: 'my-addon',
    });
  });

  it('leaves a non-approval activity with no version status', () => {
    const update = mapActivity({
      id: 7,
      addon: {},
      title: 'Version flagged for review',
    });
    expect(update.versionStatus).toBeUndefined();
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

describe('clearTranslations', () => {
  it('nulls every locale the field is translated into', () => {
    expect(clearTranslations({ 'en-US': 'Terms', fr: 'Conditions' })).toEqual({
      'en-US': null,
      fr: null,
    });
  });

  it('always nulls en-US, even for an absent or fallback-only field', () => {
    expect(clearTranslations(undefined)).toEqual({ 'en-US': null });
    expect(clearTranslations({ fr: 'Conditions' })).toEqual({
      fr: null,
      'en-US': null,
    });
  });

  it('ignores the `_default` marker of a single-translation response', () => {
    expect(clearTranslations({ fr: 'Conditions', _default: 'fr' })).toEqual({
      fr: null,
      'en-US': null,
    });
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
    mockJson({ results: [{ id: 1, title: 'Approved!' }] });
    const updates = await fetchUpdates();
    expect(updates).toHaveLength(1);
    expect(updates[0]).toMatchObject({
      id: '1',
      versionStatus: VERSION_STATUS.public,
    });
  });

  it('fetchProfile maps the id, name and picture url', async () => {
    mockJson({ id: 99, name: 'Kate', picture_url: 'https://cdn/a.png' });
    expect(await fetchProfile()).toEqual({
      id: '99',
      name: 'Kate',
      pictureUrl: 'https://cdn/a.png',
    });
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

  it('patchEulaPolicy clears a policy by nulling every existing locale', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({
            eula: { 'en-US': 'Terms', fr: 'Conditions' },
            privacy_policy: null,
          }),
        })
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({}),
        }),
    );

    await patchEulaPolicy('x', { eula: null, privacyPolicy: 'Kept' });

    // One lookup, unscoped by `lang` so it sees every locale.
    expect(vi.mocked(fetch).mock.calls).toHaveLength(2);
    const [lookupUrl] = vi.mocked(fetch).mock.calls[0];
    expect(lookupUrl).toBe('/api/v5/addons/addon/x/eula_policy/');
    const [, init] = vi.mocked(fetch).mock.calls[1];
    expect(JSON.parse(String(init?.body))).toEqual({
      eula: { 'en-US': null, fr: null },
      privacy_policy: { 'en-US': 'Kept' },
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
    const [url, init] = lastCall();
    expect(url).toBe('/api/v5/developers/agreement/');
    expect(init).toMatchObject({
      method: 'POST',
      body: JSON.stringify(payload),
    });
  });
});

describe('submission endpoints', () => {
  it('postUpload POSTs the file and channel as FormData', async () => {
    mockJson({ uuid: 'foo' });
    const file = new File(['zip'], 'addon.zip');

    await postUpload(file, 'unlisted');

    const [url, init] = lastCall();
    expect(url).toBe('/api/v5/addons/upload/');
    const body = init?.body as FormData;
    expect(body.get('channel')).toBe('unlisted');
    expect((body.get('upload') as File).name).toBe('addon.zip');
  });

  it('postVersion POSTs the upload uuid to the versions list', async () => {
    mockJson({ id: 1 });
    await postVersion('my addon', 'foo');

    const [url, init] = lastCall();
    expect(url).toBe('/api/v5/addons/addon/my%20addon/versions/');
    expect(init).toMatchObject({
      method: 'POST',
      body: JSON.stringify({ upload: 'foo' }),
    });
  });

  it('patchVersion PATCHes the version detail', async () => {
    mockJson({ id: 1 });
    await patchVersion('slug', 1, { is_disabled: true });

    const [url, init] = lastCall();
    expect(url).toBe('/api/v5/addons/addon/slug/versions/1/');
    expect(init).toMatchObject({
      method: 'PATCH',
      body: JSON.stringify({ is_disabled: true }),
    });
  });
});
