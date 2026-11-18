import { beforeEach, describe, expect, it, vi } from 'vitest';

type SiteStatus = {
  readOnly: boolean;
  siteNotice: string | null;
  submissionNotice: string | null;
};

// The banner reads the profile for its site status, falling back to the
// standalone site-status query when the profile errors. Drive both through
// mutable state so each test picks the auth state and fallback result without
// touching the network.
const { profileState, siteStatusState } = vi.hoisted(() => ({
  profileState: {
    data: undefined as { siteStatus?: SiteStatus } | undefined,
    isPending: false,
    isError: false,
  },
  siteStatusState: {
    data: undefined as SiteStatus | undefined,
    // The enabled predicate the banner handed to siteStatusQuery, captured so a
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

import type { SiteStatusBanner } from '../../src/components/site-status-banner';
import '../../src/components/site-status-banner';
import { mount } from '../helpers/fixture';

function signedOut() {
  Object.assign(profileState, {
    data: undefined,
    isPending: false,
    isError: true,
  });
}

function signedIn(
  siteStatus: SiteStatus = {
    readOnly: false,
    siteNotice: null,
    submissionNotice: null,
  },
) {
  Object.assign(profileState, {
    data: { siteStatus },
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

async function banner() {
  return await mount<SiteStatusBanner>('site-status-banner');
}

const card = (el: SiteStatusBanner) =>
  (el.shadowRoot as ShadowRoot).querySelector('#site-status-card');

describe('site-status-banner', () => {
  beforeEach(() => {
    signedOut();
    // Start each test with no fallback status; the relevant tests opt in.
    siteStatusState.data = undefined;
    siteStatusState.enabled = undefined;
  });

  it('does not flash the /site fallback while the profile is loading', async () => {
    loading();
    // A fallback value is available, but it must stay gated until the profile
    // actually errors, so nothing flashes during the pending state.
    siteStatusState.data = {
      readOnly: true,
      siteNotice: 'Should not flash.',
      submissionNotice: null,
    };
    expect(card(await banner())).toBeNull();
  });

  it('is absent when signed out, and /site response is okay too', async () => {
    signedOut();
    siteStatusState.data = {
      readOnly: false,
      siteNotice: null,
      submissionNotice: null,
    };
    expect(card(await banner())).toBeNull();
  });

  it('is absent when the site is healthy (no notice, not read-only)', async () => {
    signedIn();
    expect(card(await banner())).toBeNull();
  });

  it('shows the site notice when one is set in the profile', async () => {
    signedIn({
      readOnly: false,
      siteNotice: 'Scheduled maintenance at 10pm.',
      submissionNotice: null,
    });
    const bar = card(await banner());
    expect(bar).not.toBeNull();
    expect(bar?.textContent).toContain('Scheduled maintenance at 10pm.');
  });

  it('falls back to a generic message in read-only mode with no notice', async () => {
    signedIn({ readOnly: true, siteNotice: null, submissionNotice: null });
    const bar = card(await banner());
    expect(bar).not.toBeNull();
    expect(bar?.textContent).toContain('website maintenance');
  });

  it('prefers siteNotice over the read-only fallback when both apply', async () => {
    signedIn({
      readOnly: true,
      siteNotice: 'Custom notice wins.',
      submissionNotice: null,
    });
    const bar = card(await banner());
    expect(bar?.textContent).toContain('Custom notice wins.');
    expect(bar?.textContent).not.toContain('website maintenance');
  });

  it('shows the site notice from /site, after the profile has errored', async () => {
    // Signed out: the profile query errors, so the fallback supplies status.
    signedOut();
    siteStatusState.data = {
      readOnly: false,
      siteNotice: 'Fallback notice.',
      submissionNotice: null,
    };
    const bar = card(await banner());
    expect(bar).not.toBeNull();
    expect(bar?.textContent).toContain('Fallback notice.');
  });

  it('enables the fallback to /site only once the profile has errored', async () => {
    // Mount so the banner hands its enabled predicate to siteStatusQuery.
    signedOut();
    await banner();
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
      readOnly: false,
      siteNotice: 'From profile.',
      submissionNotice: null,
    });
    // A stale fallback value must not win over the live profile status.
    // Note this is not a real scenario: /profile includes the identical site status
    siteStatusState.data = {
      readOnly: false,
      siteNotice: 'From fallback.',
      submissionNotice: null,
    };
    const bar = card(await banner());
    expect(bar?.textContent).toContain('From profile.');
    expect(bar?.textContent).not.toContain('From fallback.');
  });
});
