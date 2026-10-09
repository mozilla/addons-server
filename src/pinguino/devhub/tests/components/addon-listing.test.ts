import { describe, expect, it } from 'vitest';
import type { AddonListing } from '../../src/components/addon-listing';
import '../../src/components/addon-listing';
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

async function listing(addon: Partial<Addon>) {
  const el = await mount<AddonListing>('addon-listing', {
    addon: { ...base, ...addon },
  });
  return el.shadowRoot as ShadowRoot;
}

describe('addon-listing', () => {
  it('renders the four section cards and a nav that targets each', async () => {
    const root = await listing({});
    for (const id of [
      'listing-details',
      'graphic-assets',
      'authors',
      'technical-details',
    ]) {
      expect(root.querySelector(`moz-card#${id}`)).not.toBeNull();
    }
    const navTargets = [...root.querySelectorAll('moz-page-nav-button')].map(
      (b) => b.getAttribute('href'),
    );
    expect(navTargets).toEqual([
      '#listing-details',
      '#graphic-assets',
      '#authors',
      '#technical-details',
    ]);
    expect(root.querySelector('moz-page-nav')?.hasAttribute('scrollspy')).toBe(
      true,
    );
  });

  it('scrolls the matching section into view when a nav item is activated', async () => {
    const root = await listing({});
    const card = root.querySelector('#authors') as HTMLElement;
    let scrolledTo: Element | undefined;
    card.scrollIntoView = function scrollIntoView() {
      scrolledTo = this;
    };
    root.querySelector('moz-page-nav')?.dispatchEvent(
      new CustomEvent('moz-page-nav:change', {
        detail: { value: 'authors' },
      }),
    );
    expect(scrolledTo).toBe(card);
  });

  it('renders categories as chips and authors with their roles', async () => {
    const root = await listing({
      categories: ['Appearance', 'Privacy & Security'],
      authors: [
        { name: 'Kate', email: 'kate@example.com', role: 'Owner' },
        { name: 'Lee', email: 'lee@example.com', role: 'Developer' },
      ],
    });
    const chips = [
      ...root.querySelectorAll('.categories moz-status-badge'),
    ].map((c) => c.textContent?.trim());
    expect(chips).toEqual(['Appearance', 'Privacy & Security']);

    const authors = root.querySelector('#authors')?.textContent ?? '';
    expect(authors).toContain('Kate');
    expect(authors).toContain('Owner');
    expect(authors).toContain('lee@example.com');
  });

  it('renders the four flags as checkboxes, checked per the add-on', async () => {
    const root = await listing({
      flags: { experimental: true, hasPrivacyPolicy: true },
    });
    const boxes = [...root.querySelectorAll('.flags moz-checkbox')];
    expect(boxes).toHaveLength(4);
    const byLabel = Object.fromEntries(
      boxes.map((b) => [b.getAttribute('label'), b.hasAttribute('checked')]),
    );
    expect(byLabel.Experimental).toBe(true);
    expect(byLabel['This add-on has a Privacy Policy']).toBe(true);
    expect(byLabel['This add-on has an End-User License Agreement']).toBe(
      false,
    );
  });

  it('always renders core fields, showing a dash when a value is absent', async () => {
    const root = await listing({ summary: undefined, screenshots: [] });
    const labels = [...root.querySelectorAll('.field dt')].map((d) =>
      d.textContent?.trim(),
    );
    expect(labels).toContain('Summary');
    // The empty summary renders a muted dash rather than being omitted.
    const summaryField = [...root.querySelectorAll('.field')].find(
      (f) => f.querySelector('dt')?.textContent?.trim() === 'Summary',
    );
    expect(summaryField?.querySelector('.muted')?.textContent).toBe('—');
    expect(root.querySelector('#graphic-assets')?.textContent).toContain(
      'No screenshots uploaded yet.',
    );
  });
});
