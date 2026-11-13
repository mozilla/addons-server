// Page titles attempt to mirror the Django devhub convention.
//   "<page> :: <context> :: Add-ons for Firefox"
//
// Pages set their title from the `updated()` lifecycle hook.
const SITE_TITLE = 'Add-ons for Firefox';
export const DEVHUB_TITLE = 'Developer Hub';
const SEPARATOR = ' :: ';

export function formatPageTitle(
  segments: Array<string | null | undefined>,
): string {
  // Filter out empty segments and join with the separator.
  return segments.filter(Boolean).join(SEPARATOR);
}

export function setPageTitle(page?: string | null, context?: string): void {
  document.title = formatPageTitle([page, context ?? DEVHUB_TITLE, SITE_TITLE]);
}
