import { describe, expect, it } from 'vitest';
import type { ThemePreview } from '../../src/components/theme-preview';
import '../../src/components/theme-preview';
import type { Addon } from '../../src/data';
import { ADDON_STATUS } from '../../src/data';
import { mount } from '../helpers/fixture';

const theme: Addon = {
  slug: 'night-sky',
  name: 'Night Sky',
  kind: 'theme',
  icon: 'themes',
  status: ADDON_STATUS.public,
  version: '1.0',
  lastUpdated: 'Aug 18 2025',
  visibility: 'visible',
  canChangeVisibility: true,
};

async function preview(addon: Partial<Addon>) {
  const el = await mount<ThemePreview>('theme-preview', {
    addon: { ...theme, ...addon },
  });
  return el.shadowRoot as ShadowRoot;
}

describe('theme-preview', () => {
  it('renders the preview image when previewUrl is present', async () => {
    const root = await preview({
      previewUrl: 'https://cdn/preview.png',
      gradient: 'linear-gradient(90deg, #fff, #000)',
    });
    expect(root.querySelector('img.preview')?.getAttribute('src')).toBe(
      'https://cdn/preview.png',
    );
    expect(root.querySelector('.bar')).toBeNull(); // image wins over gradient
  });

  it('falls back to a gradient bar without a preview', async () => {
    const root = await preview({ previewUrl: undefined, gradient: 'g' });
    expect(root.querySelector('img.preview')).toBeNull();
    expect(root.querySelector('.bar')).not.toBeNull();
  });
});
