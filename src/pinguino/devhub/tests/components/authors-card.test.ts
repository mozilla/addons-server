import { describe, expect, it, vi } from 'vitest';

const { updateAuthor, authors, pending } = vi.hoisted(() => ({
  updateAuthor: vi.fn(async () => {}),
  authors: {
    value: [] as Array<{
      userId: number;
      name: string;
      email: string;
      role: string;
      listed: boolean;
    }>,
  },
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
  updateAuthor,
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

import type { AuthorsCard } from '../../src/components/addon-listing/authors-card';
import '../../src/components/addon-listing/authors-card';
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

async function card() {
  const el = await mount<AuthorsCard>('authors-card', { addon: base });
  return { el, root: el.shadowRoot as ShadowRoot };
}

async function editCard() {
  const { el, root } = await card();
  root.querySelector<HTMLElement>('.card-head moz-button')?.click();
  await el.updateComplete;
  return { el, root };
}

const saveEdit = (root: ShadowRoot) =>
  [...root.querySelectorAll<HTMLElement>('.card-actions moz-button')]
    .find((b) => b.textContent?.includes('Save'))
    ?.click();

describe('authors-card', () => {
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
    const { root } = await card();
    const text = root.textContent ?? '';
    expect(text).toContain('kate@example.com');
    expect(text).toContain('Owner'); // role is capitalised for display
    expect(text).toContain('lee@example.com');
    expect(text).toContain('Developer');
  });

  it('changing a role PATCHes that author on Save', async () => {
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
    const { el, root } = await editCard();

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

  it('"Add new author" appends an email row', async () => {
    authors.value = [
      {
        userId: 7,
        name: 'Lee',
        email: 'lee@example.com',
        role: 'developer',
        listed: true,
      },
    ];
    const { el, root } = await editCard();

    expect(root.querySelectorAll('.author-edit')).toHaveLength(1);
    [...root.querySelectorAll<HTMLElement>('.card-actions moz-button')]
      .find((b) => b.textContent?.includes('Add new author'))
      ?.click();
    await el.updateComplete;

    const rows = root.querySelectorAll('.author-edit');
    expect(rows).toHaveLength(2);
    // The new row takes an email (add-by-email isn't wired to a create call;
    // the v5 API has no session email->user_id lookup).
    const newEmail = rows[1].querySelector('moz-input-text');
    expect(newEmail?.getAttribute('label')).toBe("Author's email");
    expect(newEmail?.getAttribute('type')).toBe('email');
  });
});
