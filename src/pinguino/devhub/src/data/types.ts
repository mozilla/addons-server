export interface Developer {
  name: string;
}

export type AddonKind = 'extension' | 'theme';
export type AddonVisibility = 'live' | 'hidden';
export type AddonDistribution = 'amo' | 'self' | 'enterprise';

export type AddonAuthorRole = 'Owner' | 'Developer';

export interface AddonAuthor {
  name: string;
  // The list API exposes neither the author's email nor an owner/developer
  // role, so both are optional and only rendered when present (e.g. from mock).
  email?: string;
  role?: AddonAuthorRole;
}

export interface AddonScreenshot {
  src: string;
  caption?: string;
}

export interface Addon {
  slug: string;
  name: string;
  kind: AddonKind;
  icon: string;
  statusLabel: string;
  version: string;
  // Display string ("Sep 2 2025"); the API mapper formats ISO dates to this.
  lastUpdated: string;
  visibility: AddonVisibility;
  distribution: AddonDistribution;
  // Extension logo (icon_url) and theme preview (previews[].image_url) from the
  // API; the card falls back to an icon / gradient bar when either is absent.
  iconUrl?: string;
  previewUrl?: string;
  // Fallback theme swatch when there's no preview image.
  gradient?: string;

  // Listing-detail fields for the manage page. All optional: the list API
  // doesn't return them yet, so they're mock-only and the page renders what's
  // present, falling back where absent.
  rating?: number;
  reviewCount?: number;
  averageDailyUsers?: number;
  homepageUrl?: string;
  websiteUrl?: string;
  listingUrl?: string;
  supportEmail?: string;
  supportUrl?: string;
  summary?: string;
  description?: string;
  categories?: string[];
  authors?: AddonAuthor[];
  screenshots?: AddonScreenshot[];
  license?: string;
  developerComments?: string;
  privacyPolicyUrl?: string;
  uuid?: string;
  whiteboard?: string;
  // "Title" flags from the listing form (experimental, paid, EULA, privacy).
  flags?: {
    experimental?: boolean;
    requiresPayment?: boolean;
    hasEula?: boolean;
    hasPrivacyPolicy?: boolean;
  };
}

export interface Update {
  id: string;
  approved: boolean;
  title: string;
  message: string;
  version: string;
  versionStatus: string;
  tags: string[];
  date: string;
  addonSlug: string;
}

export interface AgreementState {
  display_name: string | null;
  has_read_developer_agreement?: boolean;
  last_developer_agreement_change: string;
}

export interface AgreementAcceptState {
  last_developer_agreement_change: string;
  display_name?: string;
}
