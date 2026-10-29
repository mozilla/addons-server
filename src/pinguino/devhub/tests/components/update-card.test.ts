// @vitest-environment jsdom
// update-card sanitizes its HTML via DOMPurify, which needs jsdom (happy-dom
// strips the allowed tags). See tests/utils/sanitizeHTML.test.ts.
import { describe, expect, it } from 'vitest';
import type { UpdateCard } from '../../src/components/update-card';
import '../../src/components/update-card';
import { type Update, VERSION_STATUS } from '../../src/data';
import { mount } from '../helpers/fixture';

const baseUpdate: Update = {
  id: 'u1',
  title: 'Your version is approved.',
  message: 'Congrats!',
  version: '3.2.1',
  versionStatus: VERSION_STATUS.public,
  addonName: 'Ad Blocker',
  channel: 'listed',
  date: 'Sep 2 2025',
  user: 'Kate',
  addonSlug: 'ad-blocker',
};

async function card(item: Partial<Update>) {
  const el = await mount<UpdateCard>('update-card', {
    item: { ...baseUpdate, ...item },
  });
  return el.shadowRoot as ShadowRoot;
}

describe('update-card', () => {
  it('renders an approved update with a success dot and status badge', async () => {
    const root = await card({ versionStatus: VERSION_STATUS.public });

    expect(root.querySelector('moz-status-dot')?.getAttribute('type')).toBe(
      'success',
    );
    const badge = root.querySelector('.foot moz-status-badge');
    expect(badge?.getAttribute('type')).toBe('success');
    expect(badge?.textContent?.trim()).toBe('Approved');
  });

  it('renders a flagged update with a warning dot and status badge', async () => {
    const root = await card({
      versionStatus: VERSION_STATUS.unreviewed,
    });

    expect(root.querySelector('moz-status-dot')?.getAttribute('type')).toBe(
      'warning',
    );
    expect(
      root.querySelector('.foot moz-status-badge')?.getAttribute('type'),
    ).toBe('warning');
  });

  it('omits the status badge when there is no version status', async () => {
    const root = await card({ versionStatus: undefined });
    expect(root.querySelector('.foot moz-status-badge')).toBeNull();
  });

  // Only the headline is bold; a `.title p` rule once caught the name too.
  it('emphasises the headline but not the add-on name', async () => {
    const root = await card({});
    const name = root.querySelector('.addon-name') as HTMLElement;
    const headline = root.querySelector('.headline') as HTMLElement;

    expect(getComputedStyle(headline).fontWeight).toBe('600');
    expect(getComputedStyle(name).fontWeight).not.toBe('600');
  });

  it('renders the title, add-on name, message, date and version', async () => {
    const root = await card({});

    expect(root.querySelector('.title')?.textContent).toContain(
      'Your version is approved.',
    );
    expect(root.querySelector('.addon-name')?.textContent?.trim()).toBe(
      'Ad Blocker',
    );
    expect(root.querySelector('.message')?.textContent?.trim()).toBe(
      'Congrats!',
    );
    const foot = root.querySelector('.foot')?.textContent ?? '';
    expect(foot).toContain('Sep 2 2025 by Kate');
    expect(foot).toContain('Version: 3.2.1');
  });

  it('shows the date alone when the action had no acting user', async () => {
    const root = await card({ user: undefined });
    const foot = root.querySelector('.foot')?.textContent ?? '';
    expect(foot).toContain('Sep 2 2025');
    expect(foot).not.toContain('by');
  });

  it('shows the version channel as a distribution badge', async () => {
    const root = await card({ channel: 'unlisted' });
    expect(
      root
        .querySelector('.foot distribution-badge')
        ?.getAttribute('distribution'),
    ).toBe('unlisted');
  });

  it('omits the distribution badge for an entry with no version', async () => {
    const root = await card({ channel: undefined });
    expect(root.querySelector('.foot distribution-badge')).toBeNull();
  });

  it('renders HTML in the title and message as real DOM, not escaped text', async () => {
    const root = await card({
      title: '<a href="https://amo.test/a">My Add-on</a> status changed.',
      message: 'See <a href="https://amo.test/x">the review</a> for details.',
    });

    const titleLink = root.querySelector('.title a');
    expect(titleLink?.getAttribute('href')).toBe('https://amo.test/a');
    expect(titleLink?.textContent).toBe('My Add-on');

    const messageLink = root.querySelector('.message a');
    expect(messageLink?.getAttribute('href')).toBe('https://amo.test/x');
    expect(messageLink?.textContent).toBe('the review');
  });

  it('sanitizes untrusted markup, keeping links but dropping scripts', async () => {
    const root = await card({
      title: '<a href="/x" onclick="evil()">ok</a><script>evil()</script>',
      message: '<img src=x onerror="evil()">text',
    });

    const link = root.querySelector('.title a');
    expect(link?.getAttribute('href')).toBe('/x');
    expect(link?.getAttribute('onclick')).toBeNull();
    expect(root.querySelector('.title script')).toBeNull();
    // <img> isn't in the allowlist, so only its text survives.
    expect(root.querySelector('.message img')).toBeNull();
    expect(root.querySelector('.message')?.textContent?.trim()).toBe('text');
  });
});
