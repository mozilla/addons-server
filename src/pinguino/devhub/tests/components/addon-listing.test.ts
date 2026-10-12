import { describe, expect, it, vi } from 'vitest';

const {
  updateAddon,
  updateEulaPolicy,
  fetchEulaPolicy,
  updateAuthor,
  removeAuthor,
  createAuthor,
  updateIcon,
  createPreview,
  removePreview,
  updatePreview,
  authors,
  pending,
} = vi.hoisted(() => ({
  updateAddon: vi.fn(async () => {}),
  updateEulaPolicy: vi.fn(async () => {}),
  fetchEulaPolicy: vi.fn(async () => ({ eula: '', privacyPolicy: '' })),
  updateAuthor: vi.fn(async () => {}),
  removeAuthor: vi.fn(async () => {}),
  createAuthor: vi.fn(async () => {}),
  updateIcon: vi.fn(async () => {}),
  createPreview: vi.fn(async () => {}),
  removePreview: vi.fn(async () => {}),
  updatePreview: vi.fn(async () => {}),
  // Mutable so tests can seed the authorsQuery result.
  authors: {
    value: [] as Array<{
      userId: number;
      name: string;
      email: string;
      role: string;
      listed: boolean;
    }>,
  },
  // Likewise for the pending-authors group.
  pending: {
    value: [] as Array<{
      userId: number;
      name: string;
      email: string;
      role: string;
      listed: boolean;
    }>,
  },
}));
vi.mock('../../src/data', () => ({
  updateAddon,
  updateEulaPolicy,
  fetchEulaPolicy,
  updateAuthor,
  removeAuthor,
  createAuthor,
  updateIcon,
  createPreview,
  removePreview,
  updatePreview,
  // Controller stubs: return the reactive-result reader.
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
  authorsQuery: () => () => ({
    data: authors.value,
    isPending: false,
    isError: false,
  }),
  pendingAuthorsQuery: () => () => ({
    data: pending.value,
    isPending: false,
    isError: false,
  }),
}));

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

async function listing(addon: Partial<Addon>, section?: string) {
  const el = await mount<AddonListing>('addon-listing', {
    addon: { ...base, ...addon },
    ...(section ? { section } : {}),
  });
  return el.shadowRoot as ShadowRoot;
}

describe('addon-listing', () => {
  it('shows one section at a time with the nav linking to each page', async () => {
    const root = await listing({});
    // Only the default (listing-details) card is rendered.
    expect(root.querySelector('moz-card#listing-details')).not.toBeNull();
    expect(root.querySelector('moz-card#graphic-assets')).toBeNull();
    expect(root.querySelector('moz-card#authors')).toBeNull();

    const navTargets = [...root.querySelectorAll('moz-page-nav-button')].map(
      (b) => b.getAttribute('href'),
    );
    expect(navTargets).toEqual([
      '/pinguino/addon/ad-blocker/edit/listing-details',
      '/pinguino/addon/ad-blocker/edit/graphic-assets',
      '/pinguino/addon/ad-blocker/edit/authors',
      '/pinguino/addon/ad-blocker/edit/technical-details',
    ]);
  });

  it('renders the requested section card (and highlights the nav)', async () => {
    const root = await listing({}, 'authors');
    expect(root.querySelector('moz-card#authors')).not.toBeNull();
    expect(root.querySelector('moz-card#listing-details')).toBeNull();
    // `current` is a property binding (highlights the active nav item).
    const nav = root.querySelector('moz-page-nav') as { current?: string };
    expect(nav.current).toBe('authors');
  });

  it('renders categories as chips on the listing-details section', async () => {
    const root = await listing({
      categories: ['Appearance', 'Privacy & Security'],
    });
    const chips = [
      ...root.querySelectorAll('.categories moz-status-badge'),
    ].map((c) => c.textContent?.trim());
    expect(chips).toEqual(['Appearance', 'Privacy & Security']);
  });

  it('renders authors (email + role) from the authors endpoint', async () => {
    authors.value = [
      {
        userId: 1,
        name: 'Kate',
        email: 'kate@example.com',
        role: 'owner',
        listed: true,
      },
      {
        userId: 2,
        name: 'Lee',
        email: 'lee@example.com',
        role: 'developer',
        listed: true,
      },
    ];
    const root = await listing({}, 'authors');
    const text = root.querySelector('#authors')?.textContent ?? '';
    expect(text).toContain('kate@example.com');
    expect(text).toContain('Owner'); // role is capitalised for display
    expect(text).toContain('lee@example.com');
    expect(text).toContain('Developer');
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
    const root = await listing({ summary: undefined });
    const labels = [...root.querySelectorAll('.field dt')].map((d) =>
      d.textContent?.trim(),
    );
    expect(labels).toContain('Summary');
    // The empty summary renders a muted dash rather than being omitted.
    const summaryField = [...root.querySelectorAll('.field')].find(
      (f) => f.querySelector('dt')?.textContent?.trim() === 'Summary',
    );
    expect(summaryField?.querySelector('.muted')?.textContent).toBe('—');
  });

  it('shows a fallback when the graphic-assets section has no screenshots', async () => {
    const root = await listing({ screenshots: [] }, 'graphic-assets');
    expect(root.querySelector('#graphic-assets')?.textContent).toContain(
      'No screenshots uploaded yet.',
    );
  });

  it('shows each screenshot caption when viewing graphic assets', async () => {
    const root = await listing(
      {
        screenshots: [
          { id: 1, src: 'a.png', caption: 'First shot' },
          { id: 2, src: 'b.png' },
        ],
      },
      'graphic-assets',
    );
    const captions = [...root.querySelectorAll('.shot .shot-caption')].map(
      (c) => c.textContent?.trim(),
    );
    expect(captions).toEqual(['First shot', 'No caption']);
  });
});

describe('addon-listing edit', () => {
  async function enterEdit(addon: Partial<Addon> = {}) {
    const el = await mount<AddonListing>('addon-listing', {
      addon: { ...base, ...addon },
    });
    const root = el.shadowRoot as ShadowRoot;
    root.querySelector<HTMLElement>('#listing-details moz-button')?.click();
    await el.updateComplete;
    return { el, root };
  }

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

    const saveBtn = [
      ...root.querySelectorAll<HTMLElement>('.card-actions moz-button'),
    ].find((b) => b.textContent?.includes('Save'));
    saveBtn?.click();

    await vi.waitFor(() =>
      expect(updateAddon).toHaveBeenCalledWith('ad-blocker', {
        name: 'Renamed',
      }),
    );
  });

  const save = (root: ShadowRoot) =>
    [...root.querySelectorAll<HTMLElement>('.card-actions moz-button')]
      .find((b) => b.textContent?.includes('Save'))
      ?.click();

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

describe('addon-listing section editing', () => {
  async function editSection(section: string, addon: Partial<Addon> = {}) {
    const el = await mount<AddonListing>('addon-listing', {
      addon: { ...base, ...addon },
      section,
    });
    const root = el.shadowRoot as ShadowRoot;
    root.querySelector<HTMLElement>('.card-head moz-button')?.click();
    await el.updateComplete;
    return { el, root };
  }

  const saveEdit = (root: ShadowRoot) =>
    [...root.querySelectorAll<HTMLElement>('.card-actions moz-button')]
      .find((b) => b.textContent?.includes('Save'))
      ?.click();

  it('authors: changing a role PATCHes that author on Save', async () => {
    updateAuthor.mockClear();
    authors.value = [
      {
        userId: 7,
        name: 'Lee',
        email: 'lee@example.com',
        role: 'developer',
        listed: true,
      },
    ];
    const { el, root } = await editSection('authors');

    const select = root.querySelector(
      '.author-edit .role-select',
    ) as HTMLSelectElement;
    select.value = 'owner';
    select.dispatchEvent(new Event('change'));
    await el.updateComplete;

    // Batched: nothing persists until Save.
    expect(updateAuthor).not.toHaveBeenCalled();
    saveEdit(root);

    await vi.waitFor(() =>
      expect(updateAuthor).toHaveBeenCalledWith('ad-blocker', 7, {
        role: 'owner',
      }),
    );
  });

  it('authors: "Add new author" appends an email row', async () => {
    authors.value = [
      {
        userId: 7,
        name: 'Lee',
        email: 'lee@example.com',
        role: 'developer',
        listed: true,
      },
    ];
    const { el, root } = await editSection('authors');

    expect(root.querySelectorAll('.author-edit')).toHaveLength(1);
    [...root.querySelectorAll<HTMLElement>('.card-actions moz-button')]
      .find((b) => b.textContent?.includes('Add new author'))
      ?.click();
    await el.updateComplete;

    const rows = root.querySelectorAll('.author-edit');
    expect(rows).toHaveLength(2);
    // The new row takes an email (the add-by-email field is not yet wired to a
    // create call; the v5 API has no session email->user_id lookup).
    const newEmail = rows[1].querySelector('moz-input-text');
    expect(newEmail?.getAttribute('label')).toBe("Author's email");
    expect(newEmail?.getAttribute('type')).toBe('email');
  });

  it('technical: saving developer comments PATCHes the add-on', async () => {
    updateAddon.mockClear();
    const { el, root } = await editSection('technical-details');

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

  it('graphic assets: choosing an icon file uploads it', async () => {
    updateIcon.mockClear();
    const { el, root } = await editSection('graphic-assets');

    const input = root.querySelector('moz-input-file') as HTMLElement;
    Object.defineProperty(input, 'files', {
      configurable: true,
      value: [new File(['x'], 'icon.png', { type: 'image/png' })],
    });
    input.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
    await el.updateComplete;

    await vi.waitFor(() => expect(updateIcon).toHaveBeenCalledOnce());
  });

  it('graphic assets: editing a screenshot caption saves it', async () => {
    updatePreview.mockClear();
    const { el, root } = await editSection('graphic-assets', {
      screenshots: [{ id: 9, src: 'a.png', caption: 'Old' }],
    });

    const textarea = root.querySelector(
      '.shot moz-textarea',
    ) as HTMLTextAreaElement;
    textarea.value = 'New caption';
    textarea.dispatchEvent(new Event('input'));
    await el.updateComplete;

    // Captions are batched: the card's Save button persists them.
    expect(updatePreview).not.toHaveBeenCalled();
    [...root.querySelectorAll<HTMLElement>('.card-actions moz-button')]
      .find((b) => b.textContent?.includes('Save'))
      ?.click();

    await vi.waitFor(() =>
      expect(updatePreview).toHaveBeenCalledWith(
        'ad-blocker',
        9,
        'New caption',
      ),
    );
  });
});
