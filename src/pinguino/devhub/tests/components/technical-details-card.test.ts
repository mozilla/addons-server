import { describe, expect, it, vi } from 'vitest';

const { updateAddon, source } = vi.hoisted(() => ({
  updateAddon: vi.fn(async () => {}),
  source: { value: {} as Partial<Addon> },
}));
vi.mock('../../src/data', () => ({
  updateAddon,
  addonSourceQuery: () => () => ({
    data: source.value,
    isPending: false,
    isError: false,
  }),
}));

import type { TechnicalDetailsCard } from '../../src/components/addon-listing/technical-details-card';
import '../../src/components/addon-listing/technical-details-card';
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

describe('technical-details-card', () => {
  it('populates developer comments from its source', async () => {
    source.value = { developerComments: '*foo* _bar_' };
    const el = await mount<TechnicalDetailsCard>('technical-details-card', {
      addon: {
        ...base,
        developerComments: '<strong>foo</strong> <em>bar</em>',
      },
    });
    const root = el.shadowRoot as ShadowRoot;
    root.querySelector<HTMLElement>('.card-head moz-button')?.click();
    await el.updateComplete;

    expect(
      (root.querySelector('.form moz-textarea') as HTMLTextAreaElement).value,
    ).toBe('*foo* _bar_');
    source.value = {};
  });

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
        developer_comments: 'Pure content script.',
      }),
    );
  });
});
