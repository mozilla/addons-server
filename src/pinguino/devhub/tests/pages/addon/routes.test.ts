import 'urlpattern-polyfill';

import type { LitElement } from 'lit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { queryClient, queryKeys } from '../../../src/data';
import '../../../src/pages/addon/main';
import '../../../src/pages/addon/versions/submit/main';
import {
  addonPageRequests,
  EMPTY_PAGE,
  mount,
  seedAddons,
  settle,
  stubRequests,
} from '../../helpers/fixture';

function setAgreement(accepted: boolean) {
  queryClient.setQueryData(queryKeys.agreement, {
    display_name: 'me',
    has_read_developer_agreement: accepted,
    last_developer_agreement_change: '2020-01-10T12:00:00',
  });
}

// The routed pages load their own data; these tests only check the routing.
beforeEach(() => {
  stubRequests({
    ...addonPageRequests('addon-slug'),
    '/api/v5/addons/addon/': EMPTY_PAGE,
    '/api/v5/developers/agreement/': {
      display_name: 'me',
      has_read_developer_agreement: true,
      last_developer_agreement_change: '2020-01-10T12:00:00',
    },
  });
});

type RouterHost = LitElement & {
  _routes: { goto(path: string): Promise<void> };
};

async function goto(tag: string, path: string) {
  const el = await mount<RouterHost>(tag);
  await el._routes.goto(path);
  await settle(el);
  return el.shadowRoot as ShadowRoot;
}

describe('addon-routes', () => {
  it('renders the add-on page for a slug/tab', async () => {
    const root = await goto('addon-routes', 'addon-slug/edit');
    const page = root.querySelector('devhub-addon');
    expect(page).not.toBeNull();
    expect(page?.slug).toBe('addon-slug');
    expect(page?.tab).toBe('edit');
  });

  it('redirects a bare slug to its edit tab', async () => {
    // The bare :slug route has an `enter` redirect and renders nothing itself.
    const root = await goto('addon-routes', 'addon-slug');
    expect(root.querySelector('devhub-addon')).toBeNull();
  });

  it('redirects ownership to the edit authors section', async () => {
    // The :slug/ownership route redirects via `enter` and renders nothing.
    const root = await goto('addon-routes', 'addon-slug/ownership');
    expect(root.querySelector('devhub-addon')).toBeNull();
  });

  it('carries the tab and the ?page= onto the add-on page', async () => {
    history.replaceState({}, '', '?page=4');
    const root = await goto('addon-routes', 'addon-slug/feed');
    const page = root.querySelector('devhub-addon');
    expect(page?.tab).toBe('feed');
    expect(page?.page).toBe(4);
    history.replaceState({}, '', location.pathname);
  });

  it('hands submit/* to the submit routes', async () => {
    const root = await goto('addon-routes', 'submit/agreement');
    expect(root.querySelector('submit-routes')).not.toBeNull();
  });

  it('stubs pages that are not reimplemented yet', async () => {
    const root = await goto('addon-routes', 'validate');
    expect(root.querySelector('coming-soon')).not.toBeNull();
  });

  it('shows the error page for a path no nested route claims', async () => {
    const root = await goto('addon-routes', 'slug/edit/section/extra');
    expect(root.querySelector('error-page')).not.toBeNull();
  });
});

describe('addon-routes submission', () => {
  it("hands a created add-on's <slug>/submit/* to the submit routes", async () => {
    const root = await goto('addon-routes', 'addon-slug/submit/details');
    expect(root.querySelector('submit-routes')?.slug).toBe('addon-slug');
    expect(root.querySelector('devhub-addon')).toBeNull();
  });
});

describe('submit-routes', () => {
  beforeEach(() => setAgreement(false));

  it('renders the agreement page', async () => {
    const root = await goto('submit-routes', 'agreement');
    const page = root.querySelector('devhub-agreement');
    expect(page).not.toBeNull();
    expect(root.querySelector('devhub-agreement')?.next).toBe('distribution');
  });

  it('goes to submission once the agreement is accepted', async () => {
    setAgreement(true);
    const root = await goto('submit-routes', 'agreement');
    expect(root.querySelector('devhub-agreement')).toBeNull();
    expect(location.pathname).toMatch(/\/distribution$/);
  });

  it("renders a theme's agreement", async () => {
    const root = await goto('submit-routes', 'theme/agreement');
    const page = root.querySelector('devhub-agreement');
    expect(page).not.toBeNull();
    expect(root.querySelector('devhub-agreement')?.next).toBe(
      'theme/distribution',
    );
  });

  it('goes to theme submission once the agreement is accepted', async () => {
    setAgreement(true);
    const root = await goto('submit-routes', 'theme/agreement');
    expect(root.querySelector('devhub-agreement')).toBeNull();
    expect(location.pathname).toMatch(/\/theme\/distribution$/);
  });
});

describe('version-submit-routes', () => {
  it('renders the agreement page', async () => {
    setAgreement(false);
    const root = await goto('version-submit-routes', 'agreement');
    expect(root.querySelector('devhub-agreement')).not.toBeNull();
  });

  it('goes to the submission once the agreement is accepted', async () => {
    setAgreement(true);
    const root = await goto('version-submit-routes', 'agreement');
    expect(root.querySelector('devhub-agreement')).toBeNull();
  });

  // submit/* is a catch-all: unknown steps go to the submission flow, which
  // routes them itself, rather than to the error page.
  it('hands an unknown submit step to the submission flow', async () => {
    setAgreement(true);
    const root = await goto('submit-routes', 'bogus');
    expect(root.querySelector('addon-submission')).not.toBeNull();
    expect(root.querySelector('error-page')).toBeNull();
  });

  // Two navigations on purpose: the previous match mustn't be stranded.
  it('replaces the previous page rather than stranding it', async () => {
    setAgreement(true);
    const el = await mount<RouterHost>('submit-routes');
    await el._routes.goto('theme/agreement');
    await settle(el);
    await el._routes.goto('bogus');
    await settle(el);
    expect(el.shadowRoot?.querySelector('devhub-agreement')).toBeNull();
    expect(el.shadowRoot?.querySelector('addon-submission')).not.toBeNull();
  });
});

describe('version-routes', () => {
  it('shows the error page when the API has no such add-on', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })),
    );
    seedAddons([]);
    const el = await mount<LitElement & { slug: string }>('version-routes', {
      slug: 'unknown',
    });

    await vi.waitFor(async () => {
      await settle(el);
      expect(el.shadowRoot?.querySelector('error-page')).not.toBeNull();
    });
  });
});
