import { beforeEach, describe, expect, it, vi } from 'vitest';

type SiteStatus = {
  readOnly: boolean;
  siteNotice: string | null;
  submissionNotice: string | null;
};

// The header's signed-in/out UI keys off the profile query controller, and the
// site-status banner falls back to the standalone site-status query when the
// profile errors. Drive both through mutable state so each test picks the auth
// state and fallback result without touching the network.
const { profileState, siteStatusState } = vi.hoisted(() => ({
  profileState: {
    data: undefined as
      | {
          id: string;
          name: string;
          pictureUrl?: string;
          siteStatus?: SiteStatus;
        }
      | undefined,
    isPending: false,
    isError: false,
  },
  siteStatusState: {
    data: undefined as SiteStatus | undefined,
    // The enabled predicate the header handed to siteStatusQuery, captured so a
    // test can assert the fallback is gated on the profile having errored.
    enabled: undefined as (() => boolean) | undefined,
  },
}));

vi.mock('../../src/data', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../src/data')>();
  return {
    ...actual,
    profileQuery: () => () => profileState,
    // Mirror the real controller: data is only available while enabled, so the
    // fallback never contributes a status until the profile has errored.
    siteStatusQuery: (_host: unknown, getEnabled?: () => boolean) => {
      siteStatusState.enabled = getEnabled;
      return () => ({
        data: getEnabled?.() ? siteStatusState.data : undefined,
      });
    },
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
  siteStatus = {
    readOnly: false,
    siteNotice: null,
    submissionNotice: null,
  },
}: {
  name?: string;
  id?: string;
  pictureUrl?: string;
  siteStatus?: SiteStatus;
} = {}) {
  Object.assign(profileState, {
    data: { id, name, pictureUrl, siteStatus },
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
  beforeEach(() => {
    signedOut();
    // Start each test with no fallback status; the relevant tests opt in.
    siteStatusState.data = undefined;
    siteStatusState.enabled = undefined;
  });

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

    it('shows log-in while the profile is loading', async () => {
      loading();
      const root = (await header()).shadowRoot as ShadowRoot;

      expect(root.querySelector('a.login')).not.toBeNull();
      expect(root.querySelector('devhub-account-menu')).toBeNull();
    });

    it('delegates to devhub-account-menu with the profile when signed in', async () => {
      signedIn({ name: 'Kate', id: '1234' });
      const root = (await header()).shadowRoot as ShadowRoot;

      const menu = root.querySelector<DevhubAccountMenu>('devhub-account-menu');
      expect(menu).not.toBeNull();
      expect(menu?.profile).toMatchObject({
        id: '1234',
        name: 'Kate',
        pictureUrl: 'https://cdn.test/avatar.png',
      });
      // The header hands off the signed-in UI entirely; no log-in link.
      expect(root.querySelector('a.login')).toBeNull();
    });
  });

  describe('site status banner', () => {
    const banner = (root: ShadowRoot) =>
      root.querySelector('#site-status-banner');

    it('is absent when signed out (no profile, so no site status)', async () => {
      signedOut();
      const root = (await header()).shadowRoot as ShadowRoot;
      expect(banner(root)).toBeNull();
    });

    it('is absent when the site is healthy (no notice, not read-only)', async () => {
      signedIn();
      const root = (await header()).shadowRoot as ShadowRoot;
      expect(banner(root)).toBeNull();
    });

    it('shows the server-provided notice when one is set', async () => {
      signedIn({
        siteStatus: {
          readOnly: false,
          siteNotice: 'Scheduled maintenance at 10pm.',
          submissionNotice: null,
        },
      });
      const root = (await header()).shadowRoot as ShadowRoot;

      const bar = banner(root);
      expect(bar).not.toBeNull();
      expect(bar?.getAttribute('type')).toBe('warning');
      expect(bar?.textContent).toContain('Scheduled maintenance at 10pm.');
    });

    it('falls back to a generic message in read-only mode with no notice', async () => {
      signedIn({
        siteStatus: {
          readOnly: true,
          siteNotice: null,
          submissionNotice: null,
        },
      });
      const root = (await header()).shadowRoot as ShadowRoot;

      const bar = banner(root);
      expect(bar).not.toBeNull();
      expect(bar?.textContent).toContain('website maintenance');
    });

    it('prefers the notice over the read-only fallback when both apply', async () => {
      signedIn({
        siteStatus: {
          readOnly: true,
          siteNotice: 'Custom notice wins.',
          submissionNotice: null,
        },
      });
      const root = (await header()).shadowRoot as ShadowRoot;

      const bar = banner(root);
      expect(bar?.textContent).toContain('Custom notice wins.');
      expect(bar?.textContent).not.toContain('website maintenance');
    });

    describe('fallback to the standalone site-status query', () => {
      it('shows the banner from the fallback when the profile has errored', async () => {
        // Signed out: the profile query errors, so the fallback supplies status.
        signedOut();
        siteStatusState.data = {
          readOnly: false,
          siteNotice: 'Fallback notice.',
          submissionNotice: null,
        };
        const root = (await header()).shadowRoot as ShadowRoot;

        const bar = banner(root);
        expect(bar).not.toBeNull();
        expect(bar?.textContent).toContain('Fallback notice.');
      });

      it('enables the fallback only once the profile has errored', async () => {
        // Mount so the header hands its enabled predicate to siteStatusQuery.
        signedOut();
        await header();
        const enabled = siteStatusState.enabled;
        expect(enabled).toBeTypeOf('function');

        // Errored profile -> fallback is needed.
        signedOut();
        expect(enabled?.()).toBe(true);

        // Pending or signed-in profile -> fallback must stay dormant so it never
        // fires early or races the profile request.
        loading();
        expect(enabled?.()).toBe(false);
        signedIn();
        expect(enabled?.()).toBe(false);
      });

      it('prefers the profile status over the fallback when signed in', async () => {
        signedIn({
          siteStatus: {
            readOnly: false,
            siteNotice: 'From profile.',
            submissionNotice: null,
          },
        });
        // A stale fallback value must not win over the live profile status.
        siteStatusState.data = {
          readOnly: false,
          siteNotice: 'From fallback.',
          submissionNotice: null,
        };
        const root = (await header()).shadowRoot as ShadowRoot;

        const bar = banner(root);
        expect(bar?.textContent).toContain('From profile.');
        expect(bar?.textContent).not.toContain('From fallback.');
      });
    });
  });
});
