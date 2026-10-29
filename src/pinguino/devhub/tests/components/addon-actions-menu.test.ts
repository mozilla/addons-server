import { beforeEach, describe, expect, it, vi } from 'vitest';

const { setAddonVisibility, removeAddon, role } = vi.hoisted(() => ({
  setAddonVisibility: vi.fn(async () => {}),
  removeAddon: vi.fn(async () => {}),
  // The signed-in developer's role on this add-on, varied per test.
  role: { value: 'owner' as string | undefined },
}));

vi.mock('../../src/data', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../src/data')>()),
  setAddonVisibility,
  removeAddon,
  addonOwnershipQuery: () => () => role.value === 'owner',
}));

import type { AddonActionsMenu } from '../../src/components/addon-actions-menu';
import '../../src/components/addon-actions-menu';
import { ADDON_STATUS, type Addon } from '../../src/data';
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
  canChangeVisibility: true,
};

async function menu(addon: Partial<Addon> = {}) {
  const el = await mount<AddonActionsMenu>('addon-actions-menu', {
    addon: { ...base, ...addon },
  });
  return { el, root: el.shadowRoot as ShadowRoot };
}

const items = (root: ShadowRoot) => [
  ...root.querySelectorAll('moz-panel-item'),
];
const dialog = (root: ShadowRoot) => root.querySelector('moz-dialog');
// The confirm is the last of the dialog's footer buttons; Cancel is the first.
const confirmButton = (root: ShadowRoot) =>
  [...root.querySelectorAll('moz-button[slot="actions"]')].at(-1);

// Pick an action and wait for the dialog to catch up.
async function choose(el: AddonActionsMenu, index: number) {
  const root = el.shadowRoot as ShadowRoot;
  items(root)[index].dispatchEvent(new Event('click'));
  await el.updateComplete;
}

describe('addon-actions-menu', () => {
  beforeEach(() => {
    setAddonVisibility.mockClear();
    removeAddon.mockClear();
    role.value = 'owner';
  });

  // moz-button opens the panel itself, by id, via getRootNode().
  it('points the button at the panel it opens', async () => {
    const { root } = await menu();
    const id = root.querySelector('moz-panel-list')?.getAttribute('id');
    expect(id).toBeTruthy();
    expect(root.querySelector('moz-button')?.getAttribute('menu-id')).toBe(id);
  });

  it('offers disable and delete', async () => {
    const { root } = await menu();
    expect(items(root).map((i) => i.textContent?.trim())).toEqual([
      'Disable extension',
      'Delete extension',
    ]);
  });

  it('offers to enable again once the listing is hidden', async () => {
    const { root } = await menu({ visibility: 'invisible' });
    expect(items(root)[0].textContent?.trim()).toBe('Enable extension');
  });

  it('asks before doing anything', async () => {
    const { el, root } = await menu();
    expect(dialog(root)?.hasAttribute('open')).toBe(false);

    await choose(el, 0);
    expect(dialog(root)?.hasAttribute('open')).toBe(true);
    expect(setAddonVisibility).not.toHaveBeenCalled();
  });

  it('hides the listing once the disable is confirmed', async () => {
    const { el, root } = await menu();
    await choose(el, 0);
    confirmButton(root)?.dispatchEvent(new Event('click'));
    expect(setAddonVisibility).toHaveBeenCalledWith('ad-blocker', 'invisible');
  });

  it('unhides it when confirming from the hidden state', async () => {
    const { el, root } = await menu({ visibility: 'invisible' });
    await choose(el, 0);
    confirmButton(root)?.dispatchEvent(new Event('click'));
    expect(setAddonVisibility).toHaveBeenCalledWith('ad-blocker', 'visible');
  });

  it('deletes only once the delete is confirmed', async () => {
    const { el, root } = await menu();
    await choose(el, 1);
    expect(removeAddon).not.toHaveBeenCalled();
    confirmButton(root)?.dispatchEvent(new Event('click'));
    expect(removeAddon).toHaveBeenCalledWith('ad-blocker');
  });

  // Deleting is irreversible, so its confirm must not look like the others.
  it('marks the delete confirmation as destructive', async () => {
    const { el, root } = await menu();
    await choose(el, 1);
    expect(confirmButton(root)?.getAttribute('variant')).toBe('destructive');
    await choose(el, 0);
    expect(confirmButton(root)?.getAttribute('variant')).toBe('primary');
  });

  it('closes without acting when dismissed', async () => {
    const { el, root } = await menu();
    await choose(el, 1);
    dialog(root)?.dispatchEvent(new CustomEvent('moz-dialog:dismiss'));
    await el.updateComplete;
    expect(dialog(root)?.hasAttribute('open')).toBe(false);
    expect(removeAddon).not.toHaveBeenCalled();
  });

  // Only owners may delete; the API would refuse anyone else.
  it('disables delete for a developer, saying why', async () => {
    role.value = 'developer';
    const { root } = await menu();
    const del = items(root)[1];
    expect(del.hasAttribute('disabled')).toBe(true);
    expect(del.getAttribute('description')).toBe(
      'Only owners can delete an add-on.',
    );
    // Disabling the listing is still theirs to do.
    expect(items(root)[0].hasAttribute('disabled')).toBe(false);
  });

  it('leaves delete available to an owner, with no caveat', async () => {
    const { root } = await menu();
    const del = items(root)[1];
    expect(del.hasAttribute('disabled')).toBe(false);
    expect(del.hasAttribute('description')).toBe(false);
  });

  it('opens no dialog if the disabled delete is clicked anyway', async () => {
    role.value = 'developer';
    const { el, root } = await menu();
    await choose(el, 1);
    expect(dialog(root)?.hasAttribute('open')).toBe(false);
    expect(removeAddon).not.toHaveBeenCalled();
  });

  // Mozilla disabled or deleted it: neither action is the author's to take.
  it('renders nothing when the author has no say left', async () => {
    const { root } = await menu({ canChangeVisibility: false });
    expect(root.querySelector('moz-button')).toBeNull();
    expect(root.querySelector('moz-panel-list')).toBeNull();
    expect(dialog(root)).toBeNull();
  });

  it('keeps the dialog open and reports why a confirm failed', async () => {
    removeAddon.mockRejectedValueOnce(new Error('Add-on cannot be deleted.'));
    const { el, root } = await menu();
    await choose(el, 1);
    confirmButton(root)?.dispatchEvent(new Event('click'));

    await vi.waitFor(async () => {
      await el.updateComplete;
      expect(root.querySelector('moz-message-bar')?.textContent).toContain(
        'Add-on cannot be deleted.',
      );
    });
    expect(dialog(root)?.hasAttribute('open')).toBe(true);
  });
});
