import {
  type BaseRouteConfig,
  type RouteConfig,
  Router,
  Routes,
} from '@lit-labs/router';
import { html, type ReactiveControllerHost } from 'lit';

import '../components/error-page';

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

export const notFoundRoute: BaseRouteConfig = {
  render: () => html`<error-page></error-page>`,
};

// Django retries a 404 without its trailing slash (RemoveSlashMiddleware); we
// route client-side, where nothing retries, so the patterns accept it instead.
// Wildcards already absorb whatever follows, and rewriting one to match the
// slash would change which route wins for the slashless URL.
function optionalTrailingSlash(path: string): string {
  if (path === '' || path.endsWith('*') || path.endsWith('{/}?')) return path;
  return `${path.replace(/\/$/, '')}{/}?`;
}

function tolerant(routes: RouteConfig[]): RouteConfig[] {
  return routes.map((route) =>
    'path' in route
      ? { ...route, path: optionalTrailingSlash(route.path) }
      : route,
  );
}

// Routers nest: once the root hands the unmatched tail to a child, its own
// fallback can't fire. And a child without one doesn't merely skip the error
// page — goto() throws before it assigns the current route, so the outlet
// strands the page you navigated from on screen. Build every Routes here.
export function createRoutes(
  host: ReactiveControllerHost & HTMLElement,
  routes: RouteConfig[],
  options: { fallback?: BaseRouteConfig } = {},
) {
  return new Routes(host, tolerant(routes), {
    fallback: notFoundRoute,
    ...options,
  });
}

// The root router. Same pattern handling; Router adds the global click and
// popstate listeners that drive every nested Routes below it.
export function createRouter(
  host: ReactiveControllerHost & HTMLElement,
  routes: RouteConfig[],
  options: { fallback?: BaseRouteConfig } = {},
) {
  return new Router(host, tolerant(routes), {
    fallback: notFoundRoute,
    ...options,
  });
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

// Mirrors legacy DevHub's formatFileSize (static/js/zamboni/global.js). Not
// the control's own export: that one is 1024-based, so it would quote the
// server's 200 MB limit as 190.7 MB.
export function formatFileSize(bytes: number): string {
  return Intl.NumberFormat(document.documentElement.lang || undefined, {
    notation: 'compact',
    style: 'unit',
    unit: 'byte',
    unitDisplay: 'narrow',
  }).format(bytes);
}
