import { describe, expect, it, vi } from 'vitest';

const { updateAddon, updateEulaPolicy, fetchEulaPolicy, eula } = vi.hoisted(
  () => ({
    updateAddon: vi.fn(async () => {}),
    updateEulaPolicy: vi.fn(async () => {}),
    fetchEulaPolicy: vi.fn(async () => ({ eula: '', privacyPolicy: '' })),
    // Mutable so tests can seed the view-mode policy preview.
    eula: { value: { eula: '', privacyPolicy: '' } },
  }),
);
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
  eulaPolicyQuery: () => () => ({
    data: eula.value,
    isPending: false,
    isError: false,
  }),
}));

import type { ListingDetailsCard } from '../../src/components/addon-listing/listing-details-card';
import '../../src/components/addon-listing/listing-details-card';
import type { Addon } from '../../src/data';
import { ApiError } from '../../src/data/http';
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

  it('previews a present policy in a disclosure under its checkbox', async () => {
    eula.value = {
      eula: 'Be nice to users.',
      privacyPolicy: 'We keep nothing.',
    };
    const { root } = await card({
      flags: { hasEula: true, hasPrivacyPolicy: false },
    });
    const details = [...root.querySelectorAll('.flags moz-details')];
    expect(details.map((d) => d.getAttribute('heading'))).toEqual([
      'End-User License Agreement',
    ]);
    expect(details[0].textContent).toContain('Be nice to users.');
  });

  it('shows no policy preview when the add-on has none', async () => {
    eula.value = { eula: '', privacyPolicy: '' };
    const { root } = await card({ flags: {} });
    expect(root.querySelector('moz-details')).toBeNull();
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

  it('PATCHes the add-on URL (slug) when changed', async () => {
    updateAddon.mockClear();
    const { el, root } = await enterEdit();

    const urlInput = root.querySelector(
      '.url-field .url-slug',
    ) as HTMLInputElement;
    urlInput.value = 'ad-blocker-pro';
    urlInput.dispatchEvent(new Event('input'));
    await el.updateComplete;

    save(root);
    await vi.waitFor(() =>
      expect(updateAddon).toHaveBeenCalledWith('ad-blocker', {
        slug: 'ad-blocker-pro',
      }),
    );
  });

  it('redirects to the new slug URL after the add-on URL changes', async () => {
    history.pushState(
      {},
      '',
      '/developers/addon/ad-blocker/edit/listing-details',
    );
    const { el, root } = await enterEdit();

    const urlInput = root.querySelector(
      '.url-field .url-slug',
    ) as HTMLInputElement;
    urlInput.value = 'ad-blocker-pro';
    urlInput.dispatchEvent(new Event('input'));
    await el.updateComplete;

    save(root);
    await vi.waitFor(() =>
      expect(location.pathname).toBe(
        '/developers/addon/ad-blocker-pro/edit/listing-details',
      ),
    );
    history.pushState({}, '', '/');
  });

  it('shows the listing-URL base as static text beside the slug input', async () => {
    const { root } = await enterEdit({
      listingUrl: 'http://olympia.test/en-US/firefox/addon/ad-blocker',
    });
    expect(root.querySelector('.url-base')?.textContent?.trim()).toBe(
      'http://olympia.test/en-US/firefox/addon/',
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

  it('clears a policy (sends null) when its checkbox is unchecked', async () => {
    updateEulaPolicy.mockClear();
    fetchEulaPolicy.mockResolvedValueOnce({
      eula: 'Existing terms.',
      privacyPolicy: '',
    });
    const { el, root } = await enterEdit({ flags: { hasEula: true } });

    // Wait for the fetched policy text to seed the draft.
    await vi.waitFor(() => {
      const ta = root.querySelector(
        '.policy moz-textarea',
      ) as HTMLTextAreaElement;
      expect(ta?.value).toBe('Existing terms.');
    });

    const eulaBox = [...root.querySelectorAll('.policy moz-checkbox')].find(
      (b) =>
        b.getAttribute('label') ===
        'This add-on has an End-User License Agreement',
    ) as HTMLInputElement;
    eulaBox.checked = false;
    eulaBox.dispatchEvent(new Event('change'));
    await el.updateComplete;

    save(root);
    await vi.waitFor(() =>
      expect(updateEulaPolicy).toHaveBeenCalledWith('ad-blocker', {
        eula: null,
      }),
    );
  });
});
