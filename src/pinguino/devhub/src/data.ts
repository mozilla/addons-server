// Mock data for the signed-in DevHub landing. Stand-in until the AMO API is wired.

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

export const developer = 'Kate';

export const addons: Addon[] = [
  {
    slug: 'remove-youtube-shorts',
    name: 'Remove YouTube Shorts',
    kind: 'extension',
    icon: 'extension',
    statusLabel: 'Live add-on',
    version: '3.2.1',
    visibility: 'live',
    distribution: 'enterprise',
  },
  {
    slug: 'ad-blocker',
    name: 'Ad Blocker',
    kind: 'extension',
    icon: 'extension',
    statusLabel: 'Live add-on',
    version: '3.2.1',
    visibility: 'live',
    distribution: 'amo',
  },
  {
    slug: 'grammarly',
    name: 'Grammarly',
    kind: 'extension',
    icon: 'extension',
    statusLabel: 'Live add-on',
    version: '3.2.1',
    visibility: 'hidden',
    distribution: 'self',
  },
  {
    slug: 'bright-sunshine-pink',
    name: 'Bright Sunshine Pink',
    kind: 'theme',
    icon: 'sparkles',
    statusLabel: 'Live theme',
    version: '3.2.1',
    visibility: 'live',
    distribution: 'amo',
    gradient: 'linear-gradient(90deg, #ffd1e8, #ffe9a8)',
  },
  {
    slug: 'sunset',
    name: 'Sunset',
    kind: 'theme',
    icon: 'sparkles',
    statusLabel: 'Live theme',
    version: '3.2.1',
    visibility: 'live',
    distribution: 'self',
    gradient: 'linear-gradient(90deg, #ffb98a, #ffe27a)',
  },
  {
    slug: 'blue-river',
    name: 'Blue River',
    kind: 'theme',
    icon: 'sparkles',
    statusLabel: 'Live theme',
    version: '3.2.1',
    visibility: 'hidden',
    distribution: 'amo',
    gradient: 'linear-gradient(90deg, #8ad4ff, #c9f3ff)',
  },
];

export const updates: Update[] = [
  {
    id: 'u1',
    approved: true,
    title: 'Your Version is approved.',
    message: 'Congrats! "Tab Organizer 3.2.1" is approved.',
    version: '3.2.1',
    versionStatus: 'Approved',
    tags: ['Live', 'AMO'],
    date: 'Sep 2 2025',
  },
  {
    id: 'u2',
    approved: false,
    title: 'Your Version is flagged.',
    message:
      'Dear Miss Kate, we wanted to update you about your extension "Tab Organizer V3.0". The latest version needs a notice: it now includes enhanced sorting features and improved performance. Please address it promptly.',
    version: '3.2.1',
    versionStatus: 'Pending Approval',
    tags: ['Live', 'AMO'],
    date: 'Sep 2 2025',
  },
  {
    id: 'u3',
    approved: true,
    title: 'Your Version is approved.',
    message: 'Congrats! "Tab Organizer 3.2.1" is approved.',
    version: '3.2.1',
    versionStatus: 'Approved',
    tags: ['Live', 'AMO'],
    date: 'Sep 2 2025',
  },
];

export const extensions = addons.filter((a) => a.kind === 'extension');
export const themes = addons.filter((a) => a.kind === 'theme');
