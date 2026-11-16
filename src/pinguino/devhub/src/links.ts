// Off-site destinations used by the navigation. The classic devhub builds the
// Extension Workshop ones from the EXTENSION_WORKSHOP_URL setting; pinguino has
// no Django template to read settings from, so the public host is fixed here.
const EXTENSION_WORKSHOP = 'https://extensionworkshop.com';

// How Extension Workshop attributes its inbound traffic from us. Deliberately
// not the classic devhub's `devhub-menu-link`, so the two can be told apart
// while both are live.
const UTM =
  'utm_source=addons.mozilla.org&utm_medium=referral&utm_content=pinguino-menu-link';

export function extensionWorkshop(path = '/', hash = ''): string {
  return `${EXTENSION_WORKSHOP}${path}?${UTM}${hash}`;
}

export const ADDONS_BLOG = 'https://blog.mozilla.org/addons/';
export const ADDONS_FORUM = 'https://discourse.mozilla.org/c/add-ons';
