import { describe, expect, it, vi } from 'vitest';

// The shell renders the section cards, which pull from the data layer on
// connect; stub it so mounting doesn't hit the network.
vi.mock('../../src/data', () => {
  const reader = (data: unknown) => () => ({
    data,
    isPending: false,
    isError: false,
  });
  return {
    updateAddon: vi.fn(async () => {}),
    updateEulaPolicy: vi.fn(async () => {}),
    updateAuthor: vi.fn(async () => {}),
    updateIcon: vi.fn(async () => {}),
    createPreview: vi.fn(async () => {}),
    removePreview: vi.fn(async () => {}),
    updatePreview: vi.fn(async () => {}),
    categoriesQuery: () => reader([]),
    authorsQuery: () => reader([]),
    pendingAuthorsQuery: () => reader([]),
    eulaPolicyQuery: () => reader({ eula: '', privacyPolicy: '' }),
    addonSourceQuery: () => reader({}),
  };
});

import type { AddonListing } from '../../src/components/addon-listing';
import '../../src/components/addon-listing';
import type { Addon } from '../../src/data';
import { ADDON_STATUS } from '../../src/data/statuses';
import { mount } from '../helpers/fixture';

const base: Addon = {
  slug: 'ad-blocker',
  name: 'Ad Blocker',
  kind: 'extension',
  icon: 'extension',
  status: ADDON_STATUS.public,
  version: '3.2.1',
  lastUpdated: 'Aug 18 2025',
  visibility: 'visible',
  channels: ['listed'],
};

async function shell(section?: string) {
  const el = await mount<AddonListing>('addon-listing', {
    addon: base,
    ...(section ? { section } : {}),
  });
  return el.shadowRoot as ShadowRoot;
}

describe('addon-listing', () => {
  it('renders only the default section card, with the nav linking each page', async () => {
    const root = await shell();
    expect(root.querySelector('listing-details-card')).not.toBeNull();
    expect(root.querySelector('graphic-assets-card')).toBeNull();
    expect(root.querySelector('authors-card')).toBeNull();
    expect(root.querySelector('technical-details-card')).toBeNull();

    const navTargets = [...root.querySelectorAll('moz-page-nav-button')].map(
      (b) => b.getAttribute('href'),
    );
    expect(navTargets).toEqual([
      '/developers/addon/ad-blocker/edit/listing-details',
      '/developers/addon/ad-blocker/edit/graphic-assets',
      '/developers/addon/ad-blocker/edit/authors',
      '/developers/addon/ad-blocker/edit/technical-details',
    ]);
  });

  it('renders the requested section card and highlights the nav', async () => {
    const root = await shell('authors');
    expect(root.querySelector('authors-card')).not.toBeNull();
    expect(root.querySelector('listing-details-card')).toBeNull();
    // `current` is a property binding (highlights the active nav item).
    const nav = root.querySelector('moz-page-nav') as { current?: string };
    expect(nav.current).toBe('authors');
  });

  it('falls back to the default section for an unknown route', async () => {
    const root = await shell('nope');
    expect(root.querySelector('listing-details-card')).not.toBeNull();
    const nav = root.querySelector('moz-page-nav') as { current?: string };
    expect(nav.current).toBe('listing-details');
  });
});
