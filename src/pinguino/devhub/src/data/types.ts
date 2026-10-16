export interface Developer {
  name: string;
}

export type AddonKind = 'extension' | 'theme';
export type AddonVisibility = 'live' | 'hidden';
export type AddonDistribution = 'listed' | 'unlisted' | 'enterprise';

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
}

export interface Version {
  id: number;
  version: string;
  channel: AddonDistribution;
  file: { id: number; url: string; size: number; status: string };
  release_notes: string | null;
  approval_notes: string;
  source: string | null;
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
