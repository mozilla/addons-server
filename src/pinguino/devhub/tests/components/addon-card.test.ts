import { describe, expect, it } from 'vitest';
import type { AddonCard } from '../../src/components/addon-card';
import '../../src/components/addon-card';
import type { Addon } from '../../src/data';
import { mount } from '../helpers/fixture';

// Assertions read this component's own shadow root, not acorn's moz-* internals,
// so acorn needn't upgrade for these to be meaningful.
const baseAddon: Addon = {
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

async function card(addon: Partial<Addon>) {
  const el = await mount<AddonCard>('addon-card', {
    addon: { ...baseAddon, ...addon },
  });
  return el.shadowRoot as ShadowRoot;
}

describe('addon-card', () => {
  it('renders an extension with its icon and visibility/distribution badges', async () => {
    const root = await card({
      kind: 'extension',
      visibility: 'live',
      distribution: 'amo',
    });

    expect(root.querySelector('.kind')?.textContent?.trim()).toBe('Extension');
    expect(root.querySelector('moz-icon')).not.toBeNull();
    expect(root.querySelector('.preview')).toBeNull();

    const badges = [...root.querySelectorAll('.tags moz-status-badge')].map(
      (b) => b.textContent?.trim(),
    );
    expect(badges).toEqual(['Live', 'AMO']);
  });

  it('renders the uploaded logo for an extension with an iconUrl', async () => {
    const root = await card({
      kind: 'extension',
      iconUrl: 'https://cdn/logo.png',
    });
    expect(root.querySelector('img.logo')?.getAttribute('src')).toBe(
      'https://cdn/logo.png',
    );
    expect(root.querySelector('moz-icon')).toBeNull();
  });

  it('renders a theme preview image when previewUrl is present', async () => {
    const root = await card({
      kind: 'theme',
      previewUrl: 'https://cdn/preview.png',
      gradient: 'linear-gradient(90deg, #fff, #000)',
    });

    expect(root.querySelector('.kind')?.textContent?.trim()).toBe('Theme');
    expect(root.querySelector('img.preview')?.getAttribute('src')).toBe(
      'https://cdn/preview.png',
    );
    expect(root.querySelector('.bar')).toBeNull(); // image wins over gradient
  });

  it('falls back to a gradient bar when a theme has no preview', async () => {
    const root = await card({
      kind: 'theme',
      previewUrl: undefined,
      gradient: 'g',
    });
    expect(root.querySelector('img.preview')).toBeNull();
    expect(root.querySelector('.bar')).not.toBeNull();
  });

  it('maps a hidden / self-distributed add-on to the right badges', async () => {
    const root = await card({ visibility: 'hidden', distribution: 'self' });
    const badges = [...root.querySelectorAll('.tags moz-status-badge')].map(
      (b) => b.textContent?.trim(),
    );
    expect(badges).toEqual(['Hidden', 'Self']);
  });
});
