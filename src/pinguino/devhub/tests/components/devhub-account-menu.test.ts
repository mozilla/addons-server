import { describe, expect, it, vi } from 'vitest';

// Stub logout so the sign-out flow can be asserted without a request.
const { logoutMock } = vi.hoisted(() => ({ logoutMock: vi.fn() }));

vi.mock('../../src/data', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../src/data')>();
  return { ...actual, logout: logoutMock };
});

import type { DevhubAccountMenu } from '../../src/components/devhub-account-menu';
import '../../src/components/devhub-account-menu';
import type { Developer } from '../../src/data';
import { mount } from '../helpers/fixture';

const baseProfile: Developer = {
  id: '1234',
  name: 'Kate',
  pictureUrl: 'https://cdn.test/avatar.png',
};

async function menu(profile: Developer = baseProfile) {
  return await mount<DevhubAccountMenu>('devhub-account-menu', { profile });
}

describe('devhub-account-menu', () => {
  it('points the avatar trigger at the panel list it opens', async () => {
    // Opening, dismissing and keyboard handling belong to acorn's
    // moz-button/moz-panel-list pair; we only assert they're wired together.
    const root = (await menu()).shadowRoot as ShadowRoot;

    const trigger = root.querySelector('moz-button.trigger');
    const panel = root.querySelector('moz-panel-list');
    expect(trigger?.getAttribute('menu-id')).toBe('account-menu');
    expect(panel?.id).toBe('account-menu');
  });

  it('renders the profile picture as the circular avatar', async () => {
    const root = (
      await menu({ ...baseProfile, pictureUrl: 'https://cdn.test/me.png' })
    ).shadowRoot as ShadowRoot;

    const avatar = root.querySelector<HTMLImageElement>('.trigger img.avatar');
    expect(avatar?.getAttribute('src')).toBe('https://cdn.test/me.png');
  });

  it('falls back to an initial when there is no profile picture', async () => {
    // The field is genuinely absent (the API may omit it), not defaulted.
    const root = (await menu({ id: '1', name: 'Zoe' }))
      .shadowRoot as ShadowRoot;

    expect(root.querySelector('img.avatar')).toBeNull();
    expect(root.querySelector('.avatar--fallback')?.textContent?.trim()).toBe(
      'Z',
    );
  });

  it('offers profile and log-out items in the panel', async () => {
    const root = (await menu({ id: '1234', name: 'Kate' }))
      .shadowRoot as ShadowRoot;

    const profile = root.querySelector<HTMLElement>('moz-panel-item.profile');
    expect(profile?.textContent?.trim()).toBe('Kate');
    // moz-panel-item with href renders a link row; the href is on the host.
    // Frontend profile page; no locale in the test URL => prefix omitted.
    expect(profile?.getAttribute('href')).toBe('/firefox/user/1234/');
    expect(
      root.querySelector('moz-panel-item.logout')?.textContent?.trim(),
    ).toBe('Log out');
  });

  it('logs out via the session endpoint then reloads', async () => {
    logoutMock.mockResolvedValue(undefined);
    const reload = vi.fn();
    vi.stubGlobal('location', {
      pathname: '/',
      search: '',
      href: '',
      reload,
    });

    const root = (await menu()).shadowRoot as ShadowRoot;
    root.querySelector<HTMLElement>('moz-panel-item.logout')?.click();

    await vi.waitFor(() => expect(reload).toHaveBeenCalledOnce());
    expect(logoutMock).toHaveBeenCalledOnce();
  });
});
