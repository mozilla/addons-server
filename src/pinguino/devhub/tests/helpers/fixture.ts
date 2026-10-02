import type { LitElement } from 'lit';

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
