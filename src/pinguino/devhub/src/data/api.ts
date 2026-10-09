// AMO API endpoints for the DevHub. Each function fetches over ./http and maps
// the v5 response onto our domain types. Caching, dedup, and lifetime live in
// the query layer (./queries), not here.

import { apiFetch } from './http';
import type {
  Addon,
  AddonAuthor,
  AddonKind,
  AgreementAcceptState,
  AgreementState,
  Developer,
  Update,
} from './types';

// Paginated envelope shared by the AMO v5 list endpoints.
interface Paginated<T> {
  results?: T[];
}

type Localized = string | Record<string, string>;

// AMO wraps external links as an "outgoing URL" object; sometimes it's a plain
// (localized) string. Either way we want the plain destination URL.
type ApiUrl = Localized | { url?: Localized; outgoing?: Localized } | null;

// The subset of an AMO v5 add-on we read (from /addons/addon/).
interface ApiAddon {
  slug: string;
  guid?: string;
  name: Localized;
  type: string;
  status?: string;
  is_disabled?: boolean;
  last_updated?: string;
  icon_url?: string;
  url?: string;
  summary?: Localized | null;
  description?: Localized | null;
  homepage?: ApiUrl;
  support_email?: Localized | null;
  support_url?: ApiUrl;
  average_daily_users?: number;
  ratings?: { average?: number; count?: number };
  categories?: string[];
  authors?: { name: string }[];
  previews?: { image_url?: string; thumbnail_url?: string }[];
  current_version?: { version?: string; license?: { name?: Localized } };
}

// The subset of an AMO v5 activity-feed entry we read (from /activity/).
interface ApiActivity {
  addon: Partial<ApiAddon>;
  id: number;
  title?: string;
  comments?: string;
  date?: string;
  versions?: { version?: string }[];
}

// The current account, from /accounts/profile/. `name` already falls back to a
// generated name server-side; display_name is the user-chosen label when set.
interface ApiProfile {
  display_name?: string;
  name?: string;
  username?: string;
}

export function localized(
  value: string | Record<string, string> | undefined,
): string {
  if (!value) return '';
  if (typeof value === 'string') return value;
  return value['en-US'] ?? Object.values(value)[0] ?? '';
}

// Resolve an AMO URL field (plain string, localized map, or outgoing-URL
// object) to a single destination URL.
function urlValue(value: ApiUrl | undefined): string {
  if (!value) return '';
  if (typeof value === 'string') return value;
  // An outgoing-URL object carries `url`; a plain localized map does not.
  if ('url' in value) return localized(value.url);
  return localized(value as Record<string, string>);
}

// "alerts-updates" -> "Alerts Updates" for display; the API gives slugs.
function prettyCategory(slug: string): string {
  return slug
    .split('-')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

function undefinedIfEmpty(s: string): string | undefined {
  return s === '' ? undefined : s;
}

export function formatDate(iso: string | undefined): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const month = date.toLocaleString('en-US', { month: 'short' });
  return `${month} ${date.getUTCDate()} ${date.getUTCFullYear()}`;
}

export function mapAddon(a: ApiAddon): Addon {
  const kind: AddonKind = a.type === 'statictheme' ? 'theme' : 'extension';
  const live = a.status === 'public' && !a.is_disabled;
  const preview = a.previews?.[0];

  return {
    slug: a.slug,
    name: localized(a.name),
    kind,
    icon: kind === 'theme' ? 'themes' : 'extension',
    statusLabel: live
      ? kind === 'theme'
        ? 'Live theme'
        : 'Live add-on'
      : (a.status ?? 'Unknown'),
    version: a.current_version?.version ?? '—',
    lastUpdated: formatDate(a.last_updated),
    visibility: live ? 'live' : 'hidden',
    // Distribution isn't exposed by the list API yet; default until it is.
    distribution: 'amo',
    iconUrl: a.icon_url,
    previewUrl: preview?.image_url ?? preview?.thumbnail_url,

    // Listing-detail fields for the manage page (absent ones stay undefined).
    rating: a.ratings?.average,
    reviewCount: a.ratings?.count,
    averageDailyUsers: a.average_daily_users,
    listingUrl: a.url,
    homepageUrl: undefinedIfEmpty(urlValue(a.homepage)),
    supportEmail: undefinedIfEmpty(localized(a.support_email ?? undefined)),
    supportUrl: undefinedIfEmpty(urlValue(a.support_url)),
    summary: undefinedIfEmpty(localized(a.summary ?? undefined)),
    description: undefinedIfEmpty(localized(a.description ?? undefined)),
    categories: a.categories?.map(prettyCategory),
    // TODO: The list API gives author names only - no email or owner/developer role.
    authors: a.authors?.map((au): AddonAuthor => ({ name: au.name })),
    license: undefinedIfEmpty(localized(a.current_version?.license?.name)),
    uuid: a.guid,
  };
}

export function mapActivity(a: ApiActivity): Update {
  const title = a.title ?? 'Update';
  // Best-effort: the feed has no explicit approved flag, so infer it from the
  // human-readable title/comments. Revisit if the API adds a status field.

  const approved = /approv/i.test(`${title} ${a.comments ?? ''}`);
  return {
    id: String(a.id),
    approved,
    title,
    message: a.comments ?? '',
    version: a.versions?.[0]?.version ?? '',
    versionStatus: approved ? 'Approved' : '',
    tags: [],
    date: formatDate(a.date),
    addonSlug: a.addon?.slug ?? '',
  };
}

export async function fetchProfile(): Promise<Developer> {
  const data = await apiFetch<ApiProfile>('/accounts/profile/');
  return { name: data.name || '' };
}

// Lists the add-ons the authenticated session owns; no author param needed.
export async function fetchAddons(): Promise<Addon[]> {
  const data = await apiFetch<Paginated<ApiAddon>>(
    '/addons/addon/?lang=en-US&page_size=50',
  );
  return (data.results ?? []).map(mapAddon);
}

// The authenticated user's activity across all their add-ons, in one request.
export async function fetchUpdates(): Promise<Update[]> {
  const data = await apiFetch<Paginated<ApiActivity>>(
    '/activity/?lang=en-US&page_size=50',
  );
  return (data.results ?? []).map(mapActivity);
}

export async function fetchAgreement(): Promise<AgreementState> {
  return await apiFetch<AgreementState>('/developers/agreement/');
}

export async function postAgreement(
  payload: AgreementAcceptState,
): Promise<unknown> {
  return await apiFetch('/developers/agreement/', {
    method: 'POST',
    body: payload,
  });
}
