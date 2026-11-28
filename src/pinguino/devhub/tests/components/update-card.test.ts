// @vitest-environment jsdom
// update-card sanitizes its HTML via DOMPurify, which needs jsdom (happy-dom
// strips the allowed tags). See tests/utils/sanitizeHTML.test.ts.
import { describe, expect, it } from 'vitest';
import type { UpdateCard } from '../../src/components/update-card';
import '../../src/components/update-card';
import type { Update } from '../../src/data';
import { DEFAULT_VERSION, mount } from '../helpers/fixture';

const baseUpdate: Update = {
  id: 'u1',
  title: 'Your version is approved.',
  message: 'Congrats!',
  version: {
    ...DEFAULT_VERSION,
    version: '3.2.1',
  },
  addonName: 'Ad Blocker',
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
  it('renders an approved version update with a success dot and public version badge', async () => {
    const version = { ...DEFAULT_VERSION };
    version.file.status = 'public';
    const root = await card({ version: version });

    expect(root.querySelector('moz-status-dot')?.getAttribute('type')).toBe(
      'success',
    );
    const badge = root.querySelector('.foot version-badge');
    expect(badge?.getAttribute('status')).toBe('public');
    expect(badge?.getAttribute('user-disabled')).toBeNull();
  });

  it('renders an unreviewed version update with a warning dot and unreviewed version badge', async () => {
    const version = { ...DEFAULT_VERSION };
    version.file.status = 'unreviewed';
    const root = await card({ version: version });

    expect(root.querySelector('moz-status-dot')?.getAttribute('type')).toBe(
      'warning',
    );
    const badge = root.querySelector('.foot version-badge');
    expect(badge?.getAttribute('status')).toBe('unreviewed');
    expect(badge?.getAttribute('user-disabled')).toBeNull();
  });

  it('renders a rejected version update with a critical dot and disabled version badge', async () => {
    const version = { ...DEFAULT_VERSION };
    version.file.status = 'disabled';
    const root = await card({ version: version });

    expect(root.querySelector('moz-status-dot')?.getAttribute('type')).toBe(
      'critical',
    );
    const badge = root.querySelector('.foot version-badge');
    expect(badge?.getAttribute('status')).toBe('disabled');
    expect(badge?.getAttribute('user-disabled')).toBeNull();
  });

  it('renders a user disabled version update with a warning dot and user disabled version badge', async () => {
    const version = { ...DEFAULT_VERSION, is_disabled: true };
    version.file.status = 'disabled';
    const root = await card({ version: version });

    expect(root.querySelector('moz-status-dot')?.getAttribute('type')).toBe(
      'warning',
    );
    const badge = root.querySelector('.foot version-badge');
    expect(badge?.getAttribute('status')).toBe('disabled');
    expect(badge?.getAttribute('user-disabled')).toBe('');
  });

  it('omits the status badge when there is no version', async () => {
    const root = await card({ version: undefined });
    expect(root.querySelector('.foot moz-status-badge')).toBeNull();
  });

  // The title's own links go to the public listing; View is the DevHub side.
  it('points View at the Versions tab for an entry about a version', async () => {
    const root = await card({
      version: { ...DEFAULT_VERSION, version: '3.2.1' },
    });
    expect(root.querySelector('moz-button')?.getAttribute('href')).toBe(
      '/developers/addon/ad-blocker/versions',
    );
  });

  it('points View at the add-on when no version is involved', async () => {
    const root = await card({ version: undefined });
    expect(root.querySelector('moz-button')?.getAttribute('href')).toBe(
      '/developers/addon/ad-blocker',
    );
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
    const root = await card({
      version: { ...DEFAULT_VERSION, channel: 'unlisted' },
    });
    expect(
      root
        .querySelector('.foot distribution-badge')
        ?.getAttribute('distribution'),
    ).toBe('unlisted');
  });

  it('omits the distribution badge for an entry with no version', async () => {
    const root = await card({ version: undefined });
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
