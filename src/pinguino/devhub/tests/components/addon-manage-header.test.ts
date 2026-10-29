import { describe, expect, it } from 'vitest';
import type { AddonManageHeader } from '../../src/components/addon-manage-header';
import '../../src/components/addon-manage-header';
import type { AddonActionsMenu } from '../../src/components/addon-actions-menu';
import type { Addon } from '../../src/data';
import { ADDON_STATUS } from '../../src/data';
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
  canChangeVisibility: true,
  channels: ['listed'],
};

async function header(addon: Partial<Addon>) {
  const el = await mount<AddonManageHeader>('addon-manage-header', {
    addon: { ...base, ...addon },
  });
  return el.shadowRoot as ShadowRoot;
}

describe('addon-manage-header', () => {
  it('renders the name, a back link, and the status badge', async () => {
    const root = await header({ visibility: 'visible' });
    expect(root.querySelector('h1')?.textContent).toBe('Ad Blocker');
    expect(root.querySelector('.back a')?.getAttribute('href')).toBe(
      '/developers/',
    );
    // Breadcrumb: Dashboard › {name}.
    const crumbs = [...root.querySelectorAll('moz-breadcrumb')].map((c) =>
      c.textContent?.trim(),
    );
    expect(crumbs).toEqual(['Dashboard', 'Ad Blocker']);
    const badge = root.querySelector('listing-status-badge');
    expect(badge?.textContent?.trim()).toBe('Approved');
    expect(badge?.getAttribute('type')).toBe('success');
  });

  // Hiding the listing is the author's own doing, so it's what the header
  // reports — not the review status underneath it.
  it('shows Invisible over the review status once hidden', async () => {
    const root = await header({ visibility: 'invisible' });
    const badge = root.querySelector('listing-status-badge');
    expect(badge?.textContent?.trim()).toBe('Invisible');
    expect(badge?.getAttribute('type')).toBe('ghost');
  });

  it('hands the add-on to the actions menu', async () => {
    const root = await header({ visibility: 'invisible' });
    const menu = root.querySelector('addon-actions-menu') as AddonActionsMenu;
    expect(menu?.addon.visibility).toBe('invisible');
  });

  it('renders rating, review count and a listing link when present', async () => {
    const root = await header({
      rating: 4,
      reviewCount: 198,
      listingUrl: 'https://amo.test/addon/ad-blocker',
    });
    expect(root.querySelector('moz-five-star')?.getAttribute('rating')).toBe(
      '4',
    );
    expect(root.querySelector('.stats')?.textContent).toContain('198 reviews');
    const links = [...root.querySelectorAll('.stats a')].map((a) =>
      a.textContent?.trim(),
    );
    expect(links).toContain('View listing page');
  });

  it('omits the rating when there is none', async () => {
    const root = await header({ rating: undefined });
    expect(root.querySelector('moz-five-star')).toBeNull();
  });

  it('uses the summary as the tagline', async () => {
    const root = await header({ summary: 'Hide the Shorts shelf.' });
    expect(root.querySelector('.tagline')?.textContent?.trim()).toBe(
      'Hide the Shorts shelf.',
    );
  });
});
