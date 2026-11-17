import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import type { DevhubHomeBanner } from '../../src/components/devhub-home-banner';
import '../../src/components/devhub-home-banner';
import { PREVIEW_BLOG_POST } from '../../src/links';
import { mount } from '../helpers/fixture';

// The banner reads its state straight from document.cookie, so the suite drives
// it by writing the cookie rather than mocking anything.
const COOKIE = 'devhub-preview-banner-dismissed';

const clearDismissal = () => {
  // biome-ignore lint/suspicious/noDocumentCookie: can't use because local dev
  document.cookie = `${COOKIE}=; path=/; max-age=0`;
};
const setDismissed = () => {
  // biome-ignore lint/suspicious/noDocumentCookie: can't use because local dev
  document.cookie = `${COOKIE}=1; path=/`;
};

async function banner() {
  return await mount<DevhubHomeBanner>('devhub-home-banner');
}

const root = (el: DevhubHomeBanner) => el.shadowRoot as ShadowRoot;

describe('devhub-home-banner', () => {
  // Keep each test isolated from the dismissal cookie the others may set.
  beforeEach(clearDismissal);
  afterEach(clearDismissal);

  it('shows the preview card, not the page header, before dismissal', async () => {
    const el = await banner();
    expect(root(el).querySelector('#preview-banner-card')).not.toBeNull();
    expect(root(el).querySelector('moz-page-header')).toBeNull();
  });

  it('points the learn-more link at the preview blog post', async () => {
    const el = await banner();
    const link = root(el).querySelector<HTMLAnchorElement>(
      '.preview-banner-message a',
    );
    expect(link?.getAttribute('href')).toBe(PREVIEW_BLOG_POST);
  });

  it('swaps the card for the page header when dismissed, recording a cookie', async () => {
    const el = await banner();
    root(el).querySelector<HTMLElement>('.preview-banner-dismiss')?.click();
    await el.updateComplete;

    expect(root(el).querySelector('#preview-banner-card')).toBeNull();
    expect(
      root(el).querySelector('moz-page-header')?.getAttribute('heading'),
    ).toBe('Welcome to the Developer Hub.');
    // The dismissal is persisted so it survives a reload.
    expect(document.cookie).toContain(`${COOKIE}=1`);
  });

  it('starts on the page header when the dismissal cookie is already set', async () => {
    setDismissed();
    const el = await banner();
    expect(root(el).querySelector('moz-page-header')).not.toBeNull();
    expect(root(el).querySelector('#preview-banner-card')).toBeNull();
  });
});
