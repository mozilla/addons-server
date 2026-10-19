import { beforeEach, describe, expect, it, vi } from 'vitest';

// The header's signed-in/out UI keys off the profile query controller. Drive it
// through a mutable state object so each test can pick the auth state without
// touching the network; the rest of the data barrel stays real, except logout
// which we stub to assert the sign-out flow without a request.
const { profileState, logoutMock } = vi.hoisted(() => ({
  profileState: {
    data: undefined as
      | { id: string; name: string; pictureUrl?: string }
      | undefined,
    isPending: false,
    isError: false,
  },
  logoutMock: vi.fn(),
}));

vi.mock('../../src/data', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../src/data')>();
  return {
    ...actual,
    profileQuery: () => () => profileState,
    logout: logoutMock,
  };
});

import type { DevhubHeader } from '../../src/components/devhub-header';
import '../../src/components/devhub-header';
import { mount } from '../helpers/fixture';

function signedOut() {
  Object.assign(profileState, {
    data: undefined,
    isPending: false,
    isError: true,
  });
}

function signedIn({
  name = 'Kate',
  id = '1234',
  pictureUrl = 'https://cdn.test/avatar.png',
}: {
  name?: string;
  id?: string;
  pictureUrl?: string;
} = {}) {
  Object.assign(profileState, {
    data: { id, name, pictureUrl },
    isPending: false,
    isError: false,
  });
}

function loading() {
  Object.assign(profileState, {
    data: undefined,
    isPending: true,
    isError: false,
  });
}

async function header() {
  return await mount<DevhubHeader>('devhub-header');
}

async function openMenu(el: DevhubHeader) {
  const root = el.shadowRoot as ShadowRoot;
  root.querySelector<HTMLButtonElement>('.trigger')?.click();
  await el.updateComplete;
  return root;
}

describe('devhub-header', () => {
  beforeEach(signedOut);

  it('shows a link to switch back to the classic devhub', async () => {
    const root = (await header()).shadowRoot as ShadowRoot;
    // rel="external" (the Django endpoint, not an in-app route) uniquely
    // identifies the switch link among the nav anchors.
    const link = root.querySelector('a[rel="external"]');
    expect(link).not.toBeNull();
    expect(link?.getAttribute('href')).toBe('/developers/switch-pinguino');
    expect(link?.textContent?.trim()).toBe(
      'Switch back to the old Developer Hub',
    );
  });

  it('on click, navigates to the endpoint with the current path', async () => {
    const root = (await header()).shadowRoot as ShadowRoot;
    const link = root.querySelector('a[rel="external"]') as HTMLAnchorElement;

    // The handler reads the live location at click time and drives a full
    // navigation, so stub it to assert the resulting URL.
    const loc = { pathname: '/developers/addon/x', search: '', href: '' };
    vi.stubGlobal('location', loc);

    const event = new MouseEvent('click', { bubbles: true, cancelable: true });
    link.dispatchEvent(event);

    // Default navigation is blocked in favour of the enriched URL.
    expect(event.defaultPrevented).toBe(true);
    expect(loc.href).toBe(
      '/developers/switch-pinguino?path=%2Fdevelopers%2Faddon%2Fx',
    );
  });

  describe('account area', () => {
    it('shows a log-in link and no account trigger when signed out', async () => {
      signedOut();
      const root = (await header()).shadowRoot as ShadowRoot;

      expect(root.querySelector('a.login')).not.toBeNull();
      expect(root.querySelector('.trigger')).toBeNull();
    });

    it('links to the login flow with the current path as the return target', async () => {
      signedOut();
      // Stub before mount so the rendered href reflects this location too.
      const loc = {
        pathname: '/en-US/developers/addon/x',
        search: '?a=1',
        href: '',
      };
      vi.stubGlobal('location', loc);

      const root = (await header()).shadowRoot as ShadowRoot;
      const link = root.querySelector('a.login') as HTMLAnchorElement;

      const expected =
        '/api/v5/accounts/login/start/?to=%2Fen-US%2Fdevelopers%2Faddon%2Fx%3Fa%3D1';
      // The href itself carries the return path (no-JS / copy / middle-click).
      expect(link.getAttribute('href')).toBe(expected);

      // Clicking drives a full navigation to the same URL, read live.
      const event = new MouseEvent('click', {
        bubbles: true,
        cancelable: true,
      });
      link.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(true);
      expect(loc.href).toBe(expected);
    });

    it('shows neither log-in nor trigger while the profile is loading', async () => {
      loading();
      const root = (await header()).shadowRoot as ShadowRoot;

      expect(root.querySelector('a.login')).toBeNull();
      expect(root.querySelector('.trigger')).toBeNull();
    });

    it('shows the avatar trigger (collapsed) and no menu when signed in', async () => {
      signedIn();
      const root = (await header()).shadowRoot as ShadowRoot;

      const trigger = root.querySelector('.trigger');
      expect(trigger).not.toBeNull();
      expect(trigger?.getAttribute('aria-expanded')).toBe('false');
      expect(root.querySelector('a.login')).toBeNull();
      expect(root.querySelector('[role="menu"]')).toBeNull();
    });

    it('renders the profile picture as the circular avatar', async () => {
      signedIn({ pictureUrl: 'https://cdn.test/me.png' });
      const root = (await header()).shadowRoot as ShadowRoot;

      const avatar = root.querySelector<HTMLImageElement>(
        '.trigger img.avatar',
      );
      expect(avatar?.getAttribute('src')).toBe('https://cdn.test/me.png');
      // No settings icon once signed in.
      expect(root.querySelector('moz-icon')).toBeNull();
    });

    it('falls back to an initial when there is no profile picture', async () => {
      // Set state directly: a `pictureUrl: undefined` arg would hit the helper's
      // default. Here the field is genuinely absent, as the API may omit it.
      Object.assign(profileState, {
        data: { id: '1', name: 'Zoe' },
        isPending: false,
        isError: false,
      });
      const root = (await header()).shadowRoot as ShadowRoot;

      expect(root.querySelector('img.avatar')).toBeNull();
      expect(root.querySelector('.avatar--fallback')?.textContent?.trim()).toBe(
        'Z',
      );
    });

    it('opens a menu with profile and log-out items when the trigger is clicked', async () => {
      signedIn({ name: 'Kate', id: '1234' });
      const root = await openMenu(await header());

      expect(root.querySelector('[role="menu"]')).not.toBeNull();
      expect(
        root.querySelector('.trigger')?.getAttribute('aria-expanded'),
      ).toBe('true');

      const profile = root.querySelector<HTMLAnchorElement>('a.profile');
      expect(profile?.textContent?.trim()).toBe('Kate');
      // Locale-prefixed frontend profile page; no locale in the test URL => en-US.
      expect(profile?.getAttribute('href')).toBe('/en-US/firefox/user/1234/');
      expect(root.querySelector('button.logout')?.textContent?.trim()).toBe(
        'Log out',
      );
    });

    it('logs out via the session endpoint then reloads', async () => {
      signedIn();
      logoutMock.mockResolvedValue(undefined);
      const reload = vi.fn();
      vi.stubGlobal('location', {
        pathname: '/',
        search: '',
        href: '',
        reload,
      });

      const root = await openMenu(await header());
      root.querySelector<HTMLButtonElement>('button.logout')?.click();

      await vi.waitFor(() => expect(reload).toHaveBeenCalledOnce());
      expect(logoutMock).toHaveBeenCalledOnce();
    });

    it('closes the menu on a click outside the header', async () => {
      signedIn();
      const el = await header();
      const root = await openMenu(el);
      expect(root.querySelector('[role="menu"]')).not.toBeNull();

      document.body.click();
      await el.updateComplete;
      expect(root.querySelector('[role="menu"]')).toBeNull();
    });

    it('closes the menu on Escape', async () => {
      signedIn();
      const el = await header();
      const root = await openMenu(el);
      expect(root.querySelector('[role="menu"]')).not.toBeNull();

      el.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }),
      );
      await el.updateComplete;
      expect(root.querySelector('[role="menu"]')).toBeNull();
    });
  });
});
