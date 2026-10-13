import { describe, expect, it, vi } from 'vitest';

const { updateAddon } = vi.hoisted(() => ({
  updateAddon: vi.fn(async () => {}),
}));
vi.mock('../../src/data', () => ({ updateAddon }));

import type { TechnicalDetailsCard } from '../../src/components/addon-listing/technical-details-card';
import '../../src/components/addon-listing/technical-details-card';
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

describe('technical-details-card', () => {
  it('saving developer comments PATCHes the add-on', async () => {
    updateAddon.mockClear();
    const el = await mount<TechnicalDetailsCard>('technical-details-card', {
      addon: base,
    });
    const root = el.shadowRoot as ShadowRoot;
    root.querySelector<HTMLElement>('.card-head moz-button')?.click();
    await el.updateComplete;

    const textarea = root.querySelector(
      '.form moz-textarea',
    ) as HTMLTextAreaElement;
    textarea.value = 'Pure content script.';
    textarea.dispatchEvent(new Event('input'));
    await el.updateComplete;

    root
      .querySelector<HTMLElement>('.card-actions moz-button[variant="primary"]')
      ?.click();
    await vi.waitFor(() =>
      expect(updateAddon).toHaveBeenCalledWith('ad-blocker', {
        developerComments: 'Pure content script.',
      }),
    );
  });
});
