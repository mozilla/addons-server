import { describe, expect, it } from 'vitest';
import type { AddonManageHeader } from '../../src/components/addon-manage-header';
import '../../src/components/addon-manage-header';
import type { Addon } from '../../src/data';
import { mount } from '../helpers/fixture';

const base: Addon = {
  slug: 'ad-blocker',
  name: 'Ad Blocker',
  kind: 'extension',
  icon: 'extension',
  statusLabel: 'Live add-on',
  version: '3.2.1',
  lastUpdated: 'Aug 18 2025',
  visibility: 'live',
  distribution: 'amo',
};

async function header(addon: Partial<Addon>) {
  const el = await mount<AddonManageHeader>('addon-manage-header', {
    addon: { ...base, ...addon },
  });
  return el.shadowRoot as ShadowRoot;
}

describe('addon-manage-header', () => {
  it('renders the name, a back link, and a Live badge', async () => {
    const root = await header({ visibility: 'live' });
    expect(root.querySelector('h1')?.textContent).toBe('Ad Blocker');
    expect(root.querySelector('.back a')?.getAttribute('href')).toBe(
      '/pinguino/',
    );
    // Breadcrumb: Dashboard › {name}.
    const crumbs = [...root.querySelectorAll('moz-breadcrumb')].map((c) =>
      c.textContent?.trim(),
    );
    expect(crumbs).toEqual(['Dashboard', 'Ad Blocker']);
    expect(root.querySelector('moz-status-badge')?.textContent?.trim()).toBe(
      'Live',
    );
  });

  it('shows Hidden for a hidden add-on', async () => {
    const root = await header({ visibility: 'hidden' });
    expect(root.querySelector('moz-status-badge')?.textContent?.trim()).toBe(
      'Hidden',
    );
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
