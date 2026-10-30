// @lit-labs/router installs a global click handler that routes *every*
// same-origin <a> through the SPA. Links outside the app base — the classic
// Django site (e.g. /en-US/firefox/addon/...), which also appears in
// API-provided HTML like the activity feed — have no matching route and would
// hit the fallback ("Not found") until a manual refresh. A capture-phase
// listener runs before the router's and stops those clicks from reaching it, so
// the browser performs a normal full navigation instead.

export function isInAppPath(pathname: string, base: string): boolean {
  return pathname === base || pathname.startsWith(`${base}/`);
}

export function interceptOutOfAppLinks(base: string): () => void {
  const onClick = (e: MouseEvent) => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) {
      return;
    }
    const anchor = e
      .composedPath()
      .find((n): n is HTMLAnchorElement => (n as HTMLElement).tagName === 'A');
    if (!anchor || anchor.origin !== location.origin || anchor.target !== '') {
      return;
    }
    // Same-page hash links (in-page anchors, e.g. the listing side-nav) are
    // scrolled by the component that owns them. Suppress the native jump — which
    // can't reach shadow-DOM targets anyway — and keep the router out (it bails
    // on defaultPrevented) without stopping the component's own click handler.
    if (anchor.hash && anchor.pathname === location.pathname) {
      e.preventDefault();
      return;
    }
    if (!isInAppPath(anchor.pathname, base)) {
      // Keep the router's own window listener from intercepting this link;
      // leaving the default action intact lets the browser navigate fully.
      e.stopImmediatePropagation();
    }
  };
  window.addEventListener('click', onClick, { capture: true });
  return () => window.removeEventListener('click', onClick, { capture: true });
}

// The dashboard sits on the canvas tint; every other page sits on the box
// surface.
export function isDashboardPath(pathname: string, base: string): boolean {
  return pathname === base || pathname === `${base}/`;
}

// Pinguino nests an add-on's pages as tabs under one slug where classic gives
// each its own URL, so a Pinguino path means nothing to classic until it's
// translated — which it needs to be when a developer switches back. Paths with
// no classic counterpart are returned unchanged, so classic resolves or 404s
// them exactly as it does today.
export function classicPath(pathname: string, base: string): string {
  if (!isInAppPath(pathname, base)) return pathname;
  const segments = pathname.slice(base.length).split('/').filter(Boolean);
  if (segments[0] === 'addon' && segments[2] === 'feed') {
    return `${base}/feed/${segments[1]}`;
  }
  return pathname;
}

// Clamped to 1 so a junk or absent value renders the first page, not an empty one.
export function pageParam(search: string = location.search): number {
  const page = Number(new URLSearchParams(search).get('page'));
  return Number.isInteger(page) && page > 0 ? page : 1;
}
