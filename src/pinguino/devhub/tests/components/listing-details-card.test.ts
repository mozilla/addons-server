import { describe, expect, it, vi } from 'vitest';

const { updateAddon, updateEulaPolicy, fetchEulaPolicy } = vi.hoisted(() => ({
  updateAddon: vi.fn(async () => {}),
  updateEulaPolicy: vi.fn(async () => {}),
  fetchEulaPolicy: vi.fn(async () => ({ eula: '', privacyPolicy: '' })),
}));
vi.mock('../../src/data', () => ({
  updateAddon,
  updateEulaPolicy,
  fetchEulaPolicy,
  categoriesQuery: () => () => ({
    data: [
      { slug: 'bookmarks', name: 'Bookmarks', type: 'extension' },
      { slug: 'tabs', name: 'Tabs', type: 'extension' },
      { slug: 'other', name: 'Other', type: 'extension' },
      { slug: 'shopping', name: 'Shopping', type: 'extension' },
    ],
    isPending: false,
    isError: false,
  }),
}));

import type { ListingDetailsCard } from '../../src/components/addon-listing/listing-details-card';
import '../../src/components/addon-listing/listing-details-card';
import type { Addon } from '../../src/data';
import { ApiError } from '../../src/data/http';
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

async function card(addon: Partial<Addon> = {}) {
  const el = await mount<ListingDetailsCard>('listing-details-card', {
    addon: { ...base, ...addon },
  });
  return { el, root: el.shadowRoot as ShadowRoot };
}

async function enterEdit(addon: Partial<Addon> = {}) {
  const { el, root } = await card(addon);
  root.querySelector<HTMLElement>('.card-head moz-button')?.click();
  await el.updateComplete;
  return { el, root };
}

const save = (root: ShadowRoot) =>
  [...root.querySelectorAll<HTMLElement>('.card-actions moz-button')]
    .find((b) => b.textContent?.includes('Save'))
    ?.click();

describe('listing-details-card', () => {
  it('renders categories as chips', async () => {
    const { root } = await card({
      categories: ['Appearance', 'Privacy & Security'],
    });
    const chips = [
      ...root.querySelectorAll('.categories moz-status-badge'),
    ].map((c) => c.textContent?.trim());
    expect(chips).toEqual(['Appearance', 'Privacy & Security']);
  });

  it('renders the four flags as checkboxes, checked per the add-on', async () => {
    const { root } = await card({
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
    const { root } = await card({ summary: undefined });
    const summaryField = [...root.querySelectorAll('.field')].find(
      (f) => f.querySelector('dt')?.textContent?.trim() === 'Summary',
    );
    expect(summaryField?.querySelector('.muted')?.textContent).toBe('—');
  });

  it('shows the form when Edit is clicked', async () => {
    const { root } = await enterEdit();
    const labels = [...root.querySelectorAll('.form moz-input-text')].map((i) =>
      i.getAttribute('label'),
    );
    expect(labels).toContain('Add-on name');
    expect(root.querySelector('.form moz-textarea')).not.toBeNull();
  });

  it('PATCHes only the changed fields on Save', async () => {
    updateAddon.mockClear();
    const { el, root } = await enterEdit({ summary: 'Old summary' });

    const nameInput = [...root.querySelectorAll('.form moz-input-text')].find(
      (i) => i.getAttribute('label') === 'Add-on name',
    ) as HTMLInputElement;
    nameInput.value = 'Renamed';
    nameInput.dispatchEvent(new Event('input'));
    await el.updateComplete;

    save(root);
    await vi.waitFor(() =>
      expect(updateAddon).toHaveBeenCalledWith('ad-blocker', {
        name: 'Renamed',
      }),
    );
  });

  it('offers the type-matched categories and PATCHes the chosen slugs', async () => {
    updateAddon.mockClear();
    const { el, root } = await enterEdit();

    const boxes = [...root.querySelectorAll('.cat-grid moz-checkbox')];
    expect(boxes.map((b) => b.getAttribute('label'))).toEqual([
      'Bookmarks',
      'Tabs',
      'Other',
      'Shopping',
    ]);

    const tabs = boxes.find(
      (b) => b.getAttribute('label') === 'Tabs',
    ) as HTMLInputElement;
    tabs.checked = true;
    tabs.dispatchEvent(new Event('change'));
    await el.updateComplete;

    save(root);
    await vi.waitFor(() =>
      expect(updateAddon).toHaveBeenCalledWith('ad-blocker', {
        categories: ['tabs'],
      }),
    );
  });

  it('maps a 400 field error onto its input', async () => {
    updateAddon.mockRejectedValueOnce(
      new ApiError(
        400,
        'name: Ensure this field has no more than 50 characters.',
        {
          name: 'Ensure this field has no more than 50 characters.',
        },
      ),
    );
    const { el, root } = await enterEdit();

    const nameInput = [...root.querySelectorAll('.form moz-input-text')].find(
      (i) => i.getAttribute('label') === 'Add-on name',
    ) as HTMLInputElement;
    nameInput.value = 'x'.repeat(99);
    nameInput.dispatchEvent(new Event('input'));
    await el.updateComplete;

    save(root);
    await vi.waitFor(() => {
      const input = [...root.querySelectorAll('.form moz-input-text')].find(
        (i) => i.getAttribute('label') === 'Add-on name',
      );
      expect(input?.getAttribute('error')).toBe(
        'Ensure this field has no more than 50 characters.',
      );
    });
    // Field-level errors don't also raise the card-level bar.
    expect(root.querySelector('.form moz-message-bar')).toBeNull();
  });

  it('reveals a textarea when a policy is checked and saves its text', async () => {
    updateEulaPolicy.mockClear();
    const { el, root } = await enterEdit();

    const eulaBox = [...root.querySelectorAll('.policy moz-checkbox')].find(
      (b) =>
        b.getAttribute('label') ===
        'This add-on has an End-User License Agreement',
    ) as HTMLInputElement;
    eulaBox.checked = true;
    eulaBox.dispatchEvent(new Event('change'));
    await el.updateComplete;

    const textarea = root.querySelector(
      '.policy moz-textarea',
    ) as HTMLTextAreaElement;
    expect(textarea).not.toBeNull();
    textarea.value = 'Be nice.';
    textarea.dispatchEvent(new Event('input'));
    await el.updateComplete;

    save(root);
    await vi.waitFor(() =>
      expect(updateEulaPolicy).toHaveBeenCalledWith('ad-blocker', {
        eula: 'Be nice.',
      }),
    );
  });
});
