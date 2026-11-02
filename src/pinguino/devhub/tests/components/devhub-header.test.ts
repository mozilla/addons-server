import { beforeEach, describe, expect, it, vi } from 'vitest';

// The header's signed-in/out UI keys off the profile query controller. Drive it
// through a mutable state object so each test can pick the auth state without
// touching the network.
const { profileState } = vi.hoisted(() => ({
  profileState: {
    data: undefined as
      | { id: string; name: string; pictureUrl?: string }
      | undefined,
    isPending: false,
    isError: false,
  },
}));

vi.mock('../../src/data', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../src/data')>();
  return {
    ...actual,
    profileQuery: () => () => profileState,
  };
});

import type { DevhubAccountMenu } from '../../src/components/devhub-account-menu';
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
    it('shows a log-in link and no account menu when signed out', async () => {
      signedOut();
      const root = (await header()).shadowRoot as ShadowRoot;

      expect(root.querySelector('a.login')).not.toBeNull();
      expect(root.querySelector('devhub-account-menu')).toBeNull();
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

    it('shows neither log-in nor account menu while the profile is loading', async () => {
      loading();
      const root = (await header()).shadowRoot as ShadowRoot;

      expect(root.querySelector('a.login')).toBeNull();
      expect(root.querySelector('devhub-account-menu')).toBeNull();
    });

    it('delegates to devhub-account-menu with the profile when signed in', async () => {
      signedIn({ name: 'Kate', id: '1234' });
      const root = (await header()).shadowRoot as ShadowRoot;

      const menu = root.querySelector<DevhubAccountMenu>('devhub-account-menu');
      expect(menu).not.toBeNull();
      expect(menu?.profile).toEqual({
        id: '1234',
        name: 'Kate',
        pictureUrl: 'https://cdn.test/avatar.png',
      });
      // The header hands off the signed-in UI entirely; no log-in link.
      expect(root.querySelector('a.login')).toBeNull();
    });
  });
});
