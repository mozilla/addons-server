import { beforeEach, describe, expect, it, vi } from 'vitest';

const {
  updateAddon,
  updateEulaPolicy,
  addonFromUpload,
  createVersion,
  updateVersionLicense,
  eula,
  eulaSource,
  source,
  version,
} = vi.hoisted(() => ({
  updateAddon: vi.fn(async () => {}),
  updateEulaPolicy: vi.fn(async () => {}),
  addonFromUpload: vi.fn(),
  createVersion: vi.fn(),
  updateVersionLicense: vi.fn(async () => {}),
  // Mutable so tests can seed the view-mode policy preview.
  eula: { value: { eula: '', privacyPolicy: '' } },
  eulaSource: { value: { eula: '', privacyPolicy: '' } },
  source: { value: {} as Partial<Addon> },
  version: { value: undefined as unknown },
}));
vi.mock('../../src/data', () => ({
  updateAddon,
  updateEulaPolicy,
  addonFromUpload,
  createVersion,
  updateVersionLicense,
  addonSourceQuery: () => () => ({
    data: source.value,
    isPending: false,
    isError: false,
  }),
  versionQuery: () => () => ({
    data: version.value,
    isPending: false,
    isError: false,
  }),
  categoriesQuery: () => () => ({
    data: [
      { slug: 'bookmarks', name: 'Bookmarks', type: 'extension' },
      { slug: 'tabs', name: 'Tabs', type: 'extension' },
      { slug: 'other', name: 'Other', type: 'extension' },
      { slug: 'shopping', name: 'Shopping', type: 'extension' },
      { slug: 'nature', name: 'Nature', type: 'statictheme' },
    ],
    isPending: false,
    isError: false,
  }),
  eulaPolicyQuery:
    (_host: unknown, _slug: unknown, _enabled: unknown, showSource = false) =>
    () => ({
      data: showSource ? eulaSource.value : eula.value,
      isPending: false,
      isError: false,
    }),
}));

import { SITE_URL } from '../../src/base';
import type { ListingDetailsCard } from '../../src/components/addon-listing/listing-details-card';
import '../../src/components/addon-listing/listing-details-card';
import type { Addon } from '../../src/data';
import { ApiError } from '../../src/data/http';
import { ADDON_STATUS } from '../../src/data/statuses';
import { DEFAULT_VERSION, mount } from '../helpers/fixture';

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

async function card(
  addon: Partial<Addon> = {},
  props: Partial<ListingDetailsCard> = {},
) {
  const el = await mount<ListingDetailsCard>('listing-details-card', {
    addon: { ...base, ...addon },
    ...props,
  });
  return { el, root: el.shadowRoot as ShadowRoot };
}

async function enterEdit(
  addon: Partial<Addon> = {},
  props: Partial<ListingDetailsCard> = {},
) {
  const { el, root } = await card(addon, props);
  root.querySelector<HTMLElement>('.card-head moz-button')?.click();
  await el.updateComplete;
  return { el, root };
}

const save = (root: ShadowRoot) =>
  [...root.querySelectorAll<HTMLElement>('.card-actions moz-button')]
    .find((b) => b.textContent?.includes('Save'))
    ?.click();

async function licenseRoot(root: ShadowRoot) {
  const field = root.querySelector('license-field');
  await field?.updateComplete;
  return field?.shadowRoot as ShadowRoot;
}

const licenseGroup = (license: ShadowRoot) =>
  license.querySelector('moz-radio-group') as HTMLElement & { value: string };

const newAddon = { ...base, summary: 'Blocks ads' };
const mountNew = async (addon: Addon = newAddon) => {
  const el = await mount<ListingDetailsCard>('listing-details-card', {
    addon,
    editOnly: true,
    upload: 'upload-uuid',
  });
  const root = el.shadowRoot as ShadowRoot;
  const license = await licenseRoot(root);
  const input = (tag: string, label: string) =>
    [
      ...root.querySelectorAll(`.form ${tag}`),
      ...license.querySelectorAll(tag),
    ].find((i) => i.getAttribute('label') === label) as HTMLInputElement;
  return { el, root, input, group: licenseGroup(license) };
};

describe('listing-details-card', () => {
  beforeEach(() => {
    eulaSource.value = { eula: '', privacyPolicy: '' };
    source.value = {};
  });

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

  it('populates the editable description and policy fields from their source', async () => {
    updateAddon.mockClear();
    source.value = { description: '*foo* _bar_' };
    eulaSource.value = { eula: '_bar_ *foo*', privacyPolicy: '' };

    const { root } = await enterEdit({
      description: '<strong>foo</strong> bar.',
      flags: { hasEula: true },
    });

    const [_, description, eulaText] = [
      ...root.querySelectorAll('.form moz-textarea'),
    ] as HTMLTextAreaElement[];
    expect(description.value).toBe('*foo* _bar_');
    expect(eulaText.value).toBe('_bar_ *foo*');

    // Doesn't update with no changes.
    save(root);
    await vi.waitFor(() => expect(root.querySelector('.form')).toBeNull());
    expect(updateAddon).not.toHaveBeenCalled();
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

  it('shows the site URL base as static text beside the slug input', async () => {
    const { root } = await enterEdit();
    expect(root.querySelector('.url-base')?.textContent?.trim()).toBe(
      `${SITE_URL}/…/`,
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

  it('displays theme with its own categories', async () => {
    const { root } = await enterEdit({ kind: 'theme' });
    expect(
      [...root.querySelectorAll('.cat-grid moz-checkbox')].map((b) =>
        b.getAttribute('label'),
      ),
    ).toEqual(['Nature']);
    expect(root.querySelectorAll('.form > moz-checkbox, .policy')).toHaveLength(
      0,
    );
  });

  it('does not show license for an existing add-on', async () => {
    const existing = {
      license: 'MIT License',
      currentVersion: { ...DEFAULT_VERSION, id: 9 },
    };
    const { root } = await card(existing);
    const labels = [...root.querySelectorAll('.field dt')].map((dt) =>
      dt.textContent?.trim(),
    );
    expect(labels).not.toContain('License');

    const editing = await enterEdit(existing);
    expect(editing.root.querySelector('license-field')).toBeNull();
  });

  describe('a new submission version', () => {
    beforeEach(() => {
      updateVersionLicense.mockClear();
    });

    it('offers a new add-on the add-on licenses', async () => {
      const { group } = await mountNew();
      expect(
        [...group.querySelectorAll('moz-radio')].map((r) =>
          r.getAttribute('value'),
        ),
      ).toEqual([
        'MPL-2.0',
        'Apache-2.0',
        'GPL-2.0-only',
        'GPL-3.0-only',
        'LGPL-2.1-only',
        'LGPL-3.0-only',
        'AGPL-3.0-only',
        'MIT',
        'ISC',
        'BSD-2-Clause',
        'Unlicense',
        'all-rights-reserved',
        'other',
      ]);
    });

    it('offers a new theme the theme licenses', async () => {
      const { group } = await mountNew({ ...newAddon, kind: 'theme' });
      expect(
        [...group.querySelectorAll('moz-radio')].map((r) =>
          r.getAttribute('value'),
        ),
      ).toEqual([
        'CC-BY-4.0',
        'CC-BY-NC-4.0',
        'CC-BY-NC-ND-4.0',
        'CC-BY-NC-SA-4.0',
        'CC-BY-ND-4.0',
        'CC-BY-SA-4.0',
        'cc-all-rights-reserved',
      ]);
    });

    it('can edit its license', async () => {
      version.value = {
        id: 9,
        license: {
          slug: 'MIT',
          is_custom: false,
          name: { 'en-US': 'MIT License' },
        },
      };
      const { el, root } = await enterEdit({}, { versionId: 9 });
      const group = licenseGroup(await licenseRoot(root));
      expect(group.value).toBe('MIT');

      group.value = 'MPL-2.0';
      group.dispatchEvent(new Event('change'));
      await el.updateComplete;
      save(root);
      await vi.waitFor(() =>
        expect(updateVersionLicense).toHaveBeenCalledWith(
          'ad-blocker',
          9,
          'MPL-2.0',
          undefined,
        ),
      );
    });

    it('can take a custom license, with name and text', async () => {
      const { el, root } = await enterEdit({}, { versionId: 9 });
      const group = licenseGroup(await licenseRoot(root));
      group.value = 'other';
      group.dispatchEvent(new Event('change'));
      await el.updateComplete;
      const license = await licenseRoot(root);
      const nameInput = license.querySelector(
        'moz-input-text[label="License name"]',
      ) as HTMLInputElement;
      const textInput = license.querySelector(
        'moz-textarea[label="License text"]',
      ) as HTMLTextAreaElement;

      save(root);
      await vi.waitFor(() =>
        expect(nameInput.getAttribute('error')).toBe('Enter the license name.'),
      );
      expect(textInput.getAttribute('error')).toBe('Enter the license text.');
      expect(updateVersionLicense).not.toHaveBeenCalled();

      nameInput.value = 'My License';
      nameInput.dispatchEvent(new Event('input'));
      textInput.value = 'Foo';
      textInput.dispatchEvent(new Event('input'));
      await el.updateComplete;
      save(root);
      await vi.waitFor(() =>
        expect(updateVersionLicense).toHaveBeenCalledWith(
          'ad-blocker',
          9,
          undefined,
          { name: 'My License', text: 'Foo' },
        ),
      );
    });
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
    eulaSource.value = { eula: 'Existing terms.', privacyPolicy: '' };
    const { el, root } = await enterEdit({ flags: { hasEula: true } });

    const ta = root.querySelector(
      '.policy moz-textarea',
    ) as HTMLTextAreaElement;
    expect(ta?.value).toBe('Existing terms.');

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

  it('does not render card in embedded mode', async () => {
    const el = await mount<ListingDetailsCard>('listing-details-card', {
      addon: base,
      embedded: true,
    });
    const root = el.shadowRoot as ShadowRoot;
    expect(root.querySelector('moz-card')).toBeNull();
    expect(root.querySelector('.card-head h2')?.textContent).toBe(
      'Listing details',
    );
    expect(root.querySelector('.card-head moz-button')).toBeNull();
    expect(root.querySelector('dl')).not.toBeNull();
  });

  it('does not show edit button in edit-only mode', async () => {
    const el = await mount<ListingDetailsCard>('listing-details-card', {
      addon: base,
      editOnly: true,
    });
    await el.updateComplete;
    const root = el.shadowRoot as ShadowRoot;
    expect(root.querySelector('.card-head moz-button')).toBeNull();
    expect(root.querySelector('.form')).not.toBeNull();
  });

  describe('edit-only', () => {
    it('creates the add-on when it does not exist', async () => {
      addonFromUpload.mockResolvedValueOnce({
        addon: { ...base, slug: 'new-addon' },
        version: { id: 3 },
      });
      const { el, root, input, group } = await mountNew();
      const created = vi.fn();
      el.addEventListener('addon-create', created);

      // Starts from the manifest details.
      expect(input('moz-input-text', 'Add-on name').value).toBe('Ad Blocker');
      expect(input('moz-textarea', 'Summary').value).toBe('Blocks ads');
      expect(
        (root.querySelector('.url-slug') as HTMLInputElement | null)?.value,
      ).toBe('ad-blocker');

      const tabs = [...root.querySelectorAll('.cat-grid moz-checkbox')].find(
        (b) => b.getAttribute('label') === 'Tabs',
      ) as HTMLInputElement;
      tabs.checked = true;
      tabs.dispatchEvent(new Event('change'));
      group.value = 'MPL-2.0';
      group.dispatchEvent(new Event('change'));
      await el.updateComplete;

      expect(await el.save()).toBe(true);

      // Only saves what changed.
      expect(addonFromUpload).toHaveBeenCalledWith({
        categories: ['tabs'],
        version: { upload: 'upload-uuid', license: 'MPL-2.0' },
      });
      expect(created.mock.calls[0][0].detail).toEqual({
        addon: { ...base, slug: 'new-addon' },
        version: { id: 3 },
      });
    });
  });
});
