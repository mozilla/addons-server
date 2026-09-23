export interface Developer {
  name: string;
}

export type AddonKind = 'extension' | 'theme';
export type AddonVisibility = 'live' | 'hidden';
export type AddonDistribution = 'amo' | 'self' | 'enterprise';

export interface Addon {
  slug: string;
  name: string;
  kind: AddonKind;
  icon: string;
  statusLabel: string;
  version: string;
  // Current version's API id, used to fetch its review notes. From the API only.
  versionId?: number;
  // Display string ("Sep 2 2025"); the API mapper formats ISO dates to this.
  lastUpdated: string;
  visibility: AddonVisibility;
  distribution: AddonDistribution;
  // Themes render a colour bar instead of an icon.
  gradient?: string;
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
}
