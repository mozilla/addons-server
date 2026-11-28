import type { LitElement } from 'lit';
import { vi } from 'vitest';
import { queryClient, queryKeys } from '../../src/data';
import type { Addon, AddonKind, Version } from '../../src/data/types';

// Mount a Lit element, apply props, and wait for its first render. Returns the
// element so tests can read `el.shadowRoot`. Props are applied before connection
// so reactive updates are batched into the initial render.
export async function mount<T extends LitElement>(
  tag: string,
  props: Partial<T> = {},
): Promise<T> {
  const el = document.createElement(tag) as T;
  Object.assign(el, props);
  document.body.append(el);
  await el.updateComplete;
  return el;
}

// Flush pending microtasks (e.g. a settled query resolving) then the element's
// next render. Call after seeding the query cache and mounting a page.
export async function settle(el: LitElement): Promise<void> {
  await Promise.resolve();
  await el.updateComplete;
}

export const DEFAULT_VERSION: Version = {
  id: 1,
  version: '1.0.0',
  channel: 'listed',
  file: {
    id: 1,
    url: '',
    size: 0,
    status: 'public',
    created: '2025-08-18',
  },
  release_notes: null,
  approval_notes: '',
  source: null,
  edit_url: '/developers/addon/ad-blocker/versions/1',
  is_disabled: false,
};

// Seeds both kind lists, splitting `addons` by kind. `counts` overrides the
// author's totals, for tests that want them to outrun the page they seeded.
export function seedAddons(
  addons: Addon[],
  counts: Partial<Record<AddonKind, number>> = {},
) {
  for (const kind of ['extension', 'theme'] as const) {
    const results = addons.filter((addon) => addon.kind === kind);
    queryClient.setQueryData(queryKeys.addonList(kind), {
      results,
      count: counts[kind] ?? results.length,
    });
  }
}

export const PROFILE = { id: 1, name: 'Dev' };
export const EMPTY_PAGE = { results: [], count: 0 };

// An add-on as the API returns it, before mapAddon.
export function apiAddon(slug: string) {
  return {
    slug,
    name: { 'en-US': slug },
    type: 'extension',
    status: 'public',
    last_updated: '2025-08-18T00:00:00Z',
    channels: ['listed'],
  };
}

// What an add-on's manage pages request, beyond what a test seeds.
export function addonPageRequests(slug: string): Record<string, unknown> {
  const addon = `/api/v5/addons/addon/${slug}`;
  return {
    '/api/v5/accounts/profile/': PROFILE,
    '/api/v5/addons/categories/': [],
    '/api/v5/activity/': EMPTY_PAGE,
    [`${addon}/`]: apiAddon(slug),
    [`${addon}/versions/`]: EMPTY_PAGE,
    [`${addon}/authors/`]: [],
    [`${addon}/pending-authors/`]: [],
  };
}

// Answers API requests by path (without the query string) for the data a test
// doesn't assert on. Anything else still reaches the guard in tests/setup.ts.
export function stubRequests(responses: Record<string, unknown>) {
  const guard = globalThis.fetch;
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = input instanceof Request ? input.url : String(input);
      const path = new URL(url, location.origin).pathname;
      return path in responses
        ? Response.json(responses[path])
        : guard(input, init);
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}
