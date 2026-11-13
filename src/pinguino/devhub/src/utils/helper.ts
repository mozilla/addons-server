import type { Routes } from '@lit-labs/router';

// Prompt a redirect. `path` is absolute, or relative to `routes` when given.
export function navigateTo(
  path: string,
  { routes, replace = false }: { routes?: Routes; replace?: boolean } = {},
) {
  const href = routes ? routes.link(path) : path;
  if (replace) window.history.replaceState({}, '', href);
  else window.history.pushState({}, '', href);
  window.dispatchEvent(new PopStateEvent('popstate'));
  return false;
}

export function emit(el: HTMLElement, type: string, detail: unknown) {
  el.dispatchEvent(
    new CustomEvent(type, { detail, bubbles: true, composed: true }),
  );
}

// Mirrors olympia's slugify.
export function slugify(text = ''): string {
  return text
    .replace(/[^\p{L}\p{N}\p{Z}\-_~]/gu, '')
    .replace(/\p{Z}/gu, ' ')
    .trim()
    .replace(/[-\s]+/g, '-')
    .toLowerCase();
}
