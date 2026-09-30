// Built-in sample data. Used until the AMO API is configured (see ./api), and as
// the fallback when a request fails.

import type { Addon, Developer, Update } from './types';

export const developer: Developer = { name: 'Kate' };

export const mockAddons: Addon[] = [
  {
    slug: 'remove-youtube-shorts',
    name: 'Remove YouTube Shorts',
    kind: 'extension',
    icon: 'extension',
    statusLabel: 'Live add-on',
    version: '3.2.1',
    lastUpdated: 'Sep 2 2025',
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
    lastUpdated: 'Aug 18 2025',
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
    lastUpdated: 'Jul 30 2025',
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
    lastUpdated: 'Jun 2 2025',
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
    lastUpdated: 'May 14 2025',
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
    lastUpdated: 'Apr 3 2025',
    visibility: 'hidden',
    distribution: 'amo',
    gradient: 'linear-gradient(90deg, #8ad4ff, #c9f3ff)',
  },
];

export const mockUpdates: Update[] = [
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
