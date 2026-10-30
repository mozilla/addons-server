// Tracks which URL the "switch back to the classic DevHub" link should restore.
//
// When we first load we may redirect (e.g. /developers/themes -> /developers).
// We want switching back to return to the *original* incoming URL, not the
// redirected one — while the user is still on the page that redirect landed on.

function currentUrl(): string {
  return location.pathname + location.search;
}

// Capture the first load url at module-eval time, before client-side redirects.
const initialUrl = currentUrl();

// The URL the initial redirect(s) settled on, recorded once the app has mounted.
let landingUrl: string | null = null;

export function recordLanding(): void {
  landingUrl = currentUrl();
}

export function pickSwitchBackPath(
  initial: string,
  landing: string | null,
  current: string,
): string {
  return landing !== null && current === landing ? initial : current;
}

export function switchBackPath(): string {
  return pickSwitchBackPath(initialUrl, landingUrl, currentUrl());
}
