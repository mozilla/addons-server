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
