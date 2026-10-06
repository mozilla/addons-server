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
    if (
      anchor &&
      anchor.origin === location.origin &&
      anchor.target === '' &&
      !isInAppPath(anchor.pathname, base)
    ) {
      // Keep the router's own window listener from intercepting this link;
      // leaving the default action intact lets the browser navigate fully.
      e.stopImmediatePropagation();
    }
  };
  window.addEventListener('click', onClick, { capture: true });
  return () => window.removeEventListener('click', onClick, { capture: true });
}
