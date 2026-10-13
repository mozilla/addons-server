import type { IconName } from '@mozilla/acorn-web-components';

export type SectionId =
  | 'listing-details'
  | 'graphic-assets'
  | 'authors'
  | 'technical-details';

export type SectionInfo = {
  id: SectionId;
  title: string;
  description: string;
  icon: IconName;
};

// Keyed by id so each card can look up its own metadata with a total,
// non-optional access; SECTIONS is the ordered list the nav renders.
export const SECTION = {
  // TODO: "applied-policy" matches design, but acorn UX might not be happy
  'listing-details': {
    id: 'listing-details',
    title: 'Listing details',
    icon: 'applied-policy',
    description:
      'Describe your listing, categories, and promotional assets on AMO.',
  },
  'graphic-assets': {
    id: 'graphic-assets',
    title: 'Graphical assets',
    icon: 'canvas',
    description: 'The icon, banner, and screenshots shown on your listing.',
  },
  authors: {
    id: 'authors',
    title: 'Authors',
    icon: 'users',
    description: 'Developers with permission to manage this add-on.',
  },
  'technical-details': {
    id: 'technical-details',
    title: 'Technical details',
    icon: 'layer',
    description: 'Developer notes and metadata for this add-on.',
  },
} satisfies Record<SectionId, SectionInfo>;

export const SECTIONS: SectionInfo[] = Object.values(SECTION);
