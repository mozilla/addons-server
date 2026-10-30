import type { AddonVisibility, StatusInfo } from './statuses';

export interface Developer {
  id: string;
  name: string;
  pictureUrl?: string;
}

export type AddonKind = 'extension' | 'theme';
export type AddonDistribution = 'listed' | 'unlisted' | 'enterprise';
export type FileStatus = 'public' | 'disabled' | 'unreviewed';

// The API's writable role values.
export type AddonAuthorRole = 'owner' | 'developer';

export interface AddonAuthor {
  name: string;
  // The add-on list API only carries the name; the authors endpoint adds the
  // rest, so these are optional.
  userId?: number;
  email?: string;
  role?: AddonAuthorRole;
  listed?: boolean;
}

// Fields for adding an author (via the pending-authors endpoint).
export interface AddonAuthorAdd {
  userId: number;
  role: AddonAuthorRole;
  listed: boolean;
}

export interface AddonScreenshot {
  id?: number;
  src: string;
  caption?: string;
}

export interface Addon {
  slug: string;
  name: string;
  kind: AddonKind;
  icon: string;
  status: StatusInfo;
  version: string;
  // Display string ("Sep 2 2025"); the API mapper formats ISO dates to this.
  lastUpdated: string;
  visibility: AddonVisibility;
  channels?: AddonDistribution[];
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
  listingUrl?: string;
  supportEmail?: string;
  supportUrl?: string;
  summary?: string;
  description?: string;
  categories?: string[];
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
  currentVersion?: Version;
}

export interface Version {
  id: number;
  version: string;
  channel: AddonDistribution;
  file: {
    id: number;
    url: string;
    size: number;
    status: FileStatus;
    created?: string;
  };
  release_notes: Record<string, string> | string | null;
  approval_notes: string;
  source: string | null;
  edit_url: string;
  is_disabled: boolean;
  license?: {
    id: number;
    is_custom: boolean;
    name: Record<string, string> | string;
    url: string | null;
  } | null;
  reviewed?: string | null;
}

// The subset of listing fields editable from the manage page's Listing Details
// card. Keyed by the API's writable field names so the edit form, its field
// errors, and the PATCH body all line up without renaming; patchAddon only
// localizes the translated fields. Seeding from the camelCase Addon read model
// is the one place names are translated (in the card).
export interface AddonListingEdit {
  name?: string;
  slug?: string;
  summary?: string;
  description?: string;
  homepage?: string;
  support_email?: string;
  support_url?: string;
  categories?: string[];
  is_experimental?: boolean;
  requires_payment?: boolean;
  developer_comments?: string;
  is_disabled?: boolean;
}

// A listing category (from /addons/categories/). `type` matches the API's
// 'extension' | 'statictheme'.
export interface Category {
  slug: string;
  name: string;
  type: string;
}

// EULA and privacy-policy text live on a separate endpoint from the rest of the
// listing, so they have their own read/edit shapes.
export interface EulaPolicy {
  eula: string;
  privacyPolicy: string;
}

// A null value clears that policy; a string sets it.
export interface EulaPolicyEdit {
  eula?: string | null;
  privacyPolicy?: string | null;
}

export interface Update {
  id: string;
  title: string;
  message: string;
  version: string;
  // Both absent when the entry touches no version (e.g. an add-on-level event).
  versionStatus?: StatusInfo;
  channel?: AddonDistribution;
  date: string;
  // Absent when the action had no acting user. Reviewer actions arrive already
  // anonymised by the API, so this is safe to show to the developer as-is.
  user?: string;
  addonName: string;
  addonSlug: string;
}

// `total` counts every page, not this one — a short page isn't the last.
export interface ActivityPage {
  items: Update[];
  total: number;
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

export interface FileUpload {
  uuid: string;
  channel: AddonDistribution;
  processed: boolean;
  submitted: boolean;
  url: string;
  valid: boolean;
  validation: ValidationResult | null;
  version: string | null;
}

export interface ValidationMessage {
  type: 'error' | 'warning' | 'notice';
  message: string;
  description?: string;
  file?: string | null;
  line?: number | null;
}

export interface ValidationResult {
  errors: number;
  warnings: number;
  notices: number;
  messages: ValidationMessage[];
}
