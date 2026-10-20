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

async function openMenu(el: DevhubAccountMenu) {
  const root = el.shadowRoot as ShadowRoot;
  root.querySelector<HTMLButtonElement>('.trigger')?.click();
  await el.updateComplete;
  return root;
}

describe('devhub-account-menu', () => {
  it('shows the avatar trigger collapsed with no menu initially', async () => {
    const root = (await menu()).shadowRoot as ShadowRoot;

    const trigger = root.querySelector('.trigger');
    expect(trigger).not.toBeNull();
    expect(trigger?.getAttribute('aria-expanded')).toBe('false');
    expect(root.querySelector('[role="menu"]')).toBeNull();
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

  it('opens a menu with profile and log-out items when the trigger is clicked', async () => {
    const root = await openMenu(await menu({ id: '1234', name: 'Kate' }));

    expect(root.querySelector('[role="menu"]')).not.toBeNull();
    expect(root.querySelector('.trigger')?.getAttribute('aria-expanded')).toBe(
      'true',
    );

    const profile = root.querySelector<HTMLAnchorElement>('a.profile');
    expect(profile?.textContent?.trim()).toBe('Kate');
    // Frontend profile page; no locale in the test URL => prefix omitted.
    expect(profile?.getAttribute('href')).toBe('/firefox/user/1234/');
    expect(root.querySelector('button.logout')?.textContent?.trim()).toBe(
      'Log out',
    );
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

    const root = await openMenu(await menu());
    root.querySelector<HTMLButtonElement>('button.logout')?.click();

    await vi.waitFor(() => expect(reload).toHaveBeenCalledOnce());
    expect(logoutMock).toHaveBeenCalledOnce();
  });

  it('closes the menu on a click outside the component', async () => {
    const el = await menu();
    const root = await openMenu(el);
    expect(root.querySelector('[role="menu"]')).not.toBeNull();

    document.body.click();
    await el.updateComplete;
    expect(root.querySelector('[role="menu"]')).toBeNull();
  });

  it('closes the menu on Escape', async () => {
    const el = await menu();
    const root = await openMenu(el);
    expect(root.querySelector('[role="menu"]')).not.toBeNull();

    el.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }),
    );
    await el.updateComplete;
    expect(root.querySelector('[role="menu"]')).toBeNull();
  });
});
