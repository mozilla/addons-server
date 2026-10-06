import { describe, expect, it, vi } from 'vitest';
import {
  fetchAddons,
  fetchProfile,
  fetchUpdates,
  formatDate,
  localized,
  mapActivity,
  mapAddon,
} from '../../src/data/api';

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
    });

    expect(addon).toMatchObject({
      slug: 'sunset',
      name: 'Sunset', // en-US preferred out of the localized map
      kind: 'theme',
      icon: 'themes',
      statusLabel: 'Live theme',
      visibility: 'live',
      version: '3.2.1',
      lastUpdated: 'May 14 2025',
      previewUrl: 'https://cdn/preview.png',
    });
  });

  it('treats a disabled add-on as hidden and surfaces the raw status label', () => {
    const addon = mapAddon({
      slug: 'grammarly',
      name: 'Grammarly',
      type: 'extension',
      status: 'nominated',
      is_disabled: true,
    });

    expect(addon).toMatchObject({
      kind: 'extension',
      visibility: 'hidden',
      statusLabel: 'nominated',
      version: '—', // no current_version
    });
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
      approved: true,
      versionStatus: 'Approved',
      version: '3.2.1',
      date: 'Sep 2 2025',
      addonSlug: 'my-addon',
    });
  });

  it('leaves a non-approval activity unapproved with no status', () => {
    const update = mapActivity({
      id: 7,
      addon: {},
      title: 'Version flagged for review',
    });
    expect(update).toMatchObject({ approved: false, versionStatus: '' });
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
    mockJson({ results: [{ id: 1, title: 'Approved!' }] });
    const updates = await fetchUpdates();
    expect(updates).toHaveLength(1);
    expect(updates[0]).toMatchObject({ id: '1', approved: true });
  });

  it('fetchProfile reads the account name', async () => {
    mockJson({ name: 'Kate' });
    expect(await fetchProfile()).toEqual({ name: 'Kate' });
  });
});
