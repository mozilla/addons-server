import { describe, expect, it, vi } from 'vitest';

const { updateIcon, createPreview, removePreview, updatePreview } = vi.hoisted(
  () => ({
    updateIcon: vi.fn(async () => {}),
    createPreview: vi.fn(async () => {}),
    removePreview: vi.fn(async () => {}),
    updatePreview: vi.fn(async () => {}),
  }),
);
vi.mock('../../src/data', () => ({
  updateIcon,
  createPreview,
  removePreview,
  updatePreview,
}));

import type { GraphicAssetsCard } from '../../src/components/addon-listing/graphic-assets-card';
import '../../src/components/addon-listing/graphic-assets-card';
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
  const el = await mount<GraphicAssetsCard>('graphic-assets-card', {
    addon: { ...base, ...addon },
  });
  return { el, root: el.shadowRoot as ShadowRoot };
}

async function editCard(addon: Partial<Addon> = {}) {
  const { el, root } = await card(addon);
  root.querySelector<HTMLElement>('.card-head moz-button')?.click();
  await el.updateComplete;
  return { el, root };
}

describe('graphic-assets-card', () => {
  it('shows a fallback when there are no screenshots', async () => {
    const { root } = await card({ screenshots: [] });
    expect(root.textContent).toContain('No screenshots uploaded yet.');
  });

  it('shows each screenshot caption when viewing', async () => {
    const { root } = await card({
      screenshots: [
        { id: 1, src: 'a.png', caption: 'First shot' },
        { id: 2, src: 'b.png' },
      ],
    });
    const captions = [...root.querySelectorAll('.shot .shot-caption')].map(
      (c) => c.textContent?.trim(),
    );
    expect(captions).toEqual(['First shot', 'No caption']);
  });

  it('choosing an icon file uploads it', async () => {
    updateIcon.mockClear();
    const { el, root } = await editCard();

    const input = root.querySelector('moz-input-file') as HTMLElement;
    Object.defineProperty(input, 'files', {
      configurable: true,
      value: [new File(['x'], 'icon.png', { type: 'image/png' })],
    });
    input.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
    await el.updateComplete;

    await vi.waitFor(() => expect(updateIcon).toHaveBeenCalledOnce());
  });

  it('surfaces an API field error from a failed upload in the error bar', async () => {
    updateIcon.mockRejectedValueOnce(
      new ApiError(400, 'icon: Images must be square.', {
        icon: 'Images must be square.',
      }),
    );
    const { root } = await editCard();

    const input = root.querySelector('moz-input-file') as HTMLElement;
    Object.defineProperty(input, 'files', {
      configurable: true,
      value: [new File(['x'], 'icon.png', { type: 'image/png' })],
    });
    input.dispatchEvent(new Event('change', { bubbles: true, composed: true }));

    await vi.waitFor(() => {
      const bar = root.querySelector('moz-message-bar');
      expect(bar?.textContent).toContain('icon: Images must be square.');
    });
  });

  it('editing a screenshot caption saves it on the card Save', async () => {
    updatePreview.mockClear();
    const { el, root } = await editCard({
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
