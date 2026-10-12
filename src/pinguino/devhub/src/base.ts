// Single source of truth for where the DevHub SPA is mounted. Shared by
// vite.config.ts (the build-time `base`) and the runtime router/links so the
// path is never hard-coded in more than one place.

// The URL segment the SPA lives under, e.g. "/developers/...".
export const DEVHUB_SEGMENT = 'developers';

// Vite's `base`: the segment with leading and trailing slashes.
export const VITE_BASE = `/${DEVHUB_SEGMENT}/`;

// A URL under the SPA may be locale-prefixed (e.g. /en-US/developers/...). Match
// an optional locale code followed by the segment, capturing the locale. The
// lookahead keeps it from matching a longer word that merely starts with the
// segment (e.g. /developersblog).
const MOUNT_RE = new RegExp(
  `^(?:/(\\w{2,3}(?:-\\w{2,6})?))?/${DEVHUB_SEGMENT}(?=/|$)`,
);

export interface Mount {
  /** The app's base path, locale prefix included, without a trailing slash. */
  base: string;
  /** The locale code if the URL was prefixed with one, else null. */
  locale: string | null;
}

// Resolve a pathname into the app's base (locale prefix + segment) and locale.
// Falls back to the unprefixed segment for paths outside the SPA.
export function resolveMount(pathname: string): Mount {
  const match = pathname.match(MOUNT_RE);
  return match
    ? { base: match[0], locale: match[1] ?? null }
    : { base: `/${DEVHUB_SEGMENT}`, locale: null };
}

// Rewrite a (possibly locale-prefixed) request path to Vite's unprefixed base,
// e.g. "/en-US/developers/foo" -> "/developers/foo". Used by the dev server so
// it serves locale-prefixed URLs despite its base being the unprefixed segment.
export function toViteBasePath(url: string): string {
  return url.replace(MOUNT_RE, `/${DEVHUB_SEGMENT}`);
}

// The mount resolved from the URL the browser loaded. Guarded so this module can
// also be imported by vite.config.ts in Node, where `location` is undefined.
const mount: Mount =
  typeof location === 'undefined'
    ? { base: `/${DEVHUB_SEGMENT}`, locale: null }
    : resolveMount(location.pathname);

// The app's mount path (locale prefix included) - use this instead of
// hard-coding the path in routes and links.
export const BASE = mount.base;

// The active locale code (e.g. "en-US"), or null if the URL had no locale
// prefix. The app will eventually use this to drive localisation.
export const LOCALE = mount.locale;
