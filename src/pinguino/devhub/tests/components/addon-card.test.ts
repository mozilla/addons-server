import { describe, expect, it } from 'vitest';
import type { AddonCard } from '../../src/components/addon-card';
import '../../src/components/addon-card';
import type { Addon } from '../../src/data';
import { ADDON_STATUS } from '../../src/data';
import { DEFAULT_VERSION, mount } from '../helpers/fixture';

// Assertions read this component's own shadow root, not acorn's moz-* internals,
// so acorn needn't upgrade for these to be meaningful.
const baseAddon: Addon = {
  slug: 'ad-blocker',
  name: 'Ad Blocker',
  kind: 'extension',
  icon: 'extension',
  status: ADDON_STATUS.public,
  lastUpdated: 'Aug 18 2025',
  visibility: 'visible',
  canChangeVisibility: true,
  channels: ['listed'],
  currentVersion: { ...DEFAULT_VERSION },
};

async function card(addon: Partial<Addon>) {
  const el = await mount<AddonCard>('addon-card', {
    addon: { ...baseAddon, ...addon },
  });
  return el.shadowRoot as ShadowRoot;
}

describe('addon-card', () => {
  it('renders an extension name with its distribution badges', async () => {
    const root = await card({
      kind: 'extension',
      channels: ['listed', 'unlisted', 'enterprise'],
    });

    // No iconUrl and no theme preview — just the name in the title row.
    expect(root.querySelector('.logo')).toBeNull();
    expect(root.querySelector('theme-preview')).toBeNull();
    expect(root.querySelector('.name')?.textContent?.trim()).toBe('Ad Blocker');

    expect(
      [...root.querySelectorAll('distribution-badge')].map((b) =>
        b.getAttribute('distribution'),
      ),
    ).toEqual(['listed', 'unlisted', 'enterprise']);
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

  it("renders a theme's preview", async () => {
    const root = await card({
      kind: 'theme',
      previewUrl: 'https://cdn/preview.png',
    });

    expect(root.querySelector('theme-preview')?.addon.previewUrl).toBe(
      'https://cdn/preview.png',
    );
  });
});
