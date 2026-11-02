import type { LitElement } from 'lit';
import type { Version } from '../../src/data/types';

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
