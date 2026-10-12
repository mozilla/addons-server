// AMO API endpoints for the DevHub. Each function fetches over ./http and maps
// the v5 response onto our domain types. Caching, dedup, and lifetime live in
// the query layer (./queries), not here.

import { apiFetch } from './http';
import type {
  Addon,
  AddonAuthor,
  AddonAuthorAdd,
  AddonAuthorRole,
  AddonKind,
  AddonListingEdit,
  AgreementAcceptState,
  AgreementState,
  Category,
  Developer,
  EulaPolicy,
  EulaPolicyEdit,
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
  previews?: {
    id?: number;
    image_url?: string;
    thumbnail_url?: string;
    caption?: Localized | null;
  }[];
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
    screenshots: a.previews?.map((p) => ({
      id: p.id,
      src: p.image_url ?? p.thumbnail_url ?? '',
      caption: undefinedIfEmpty(localized(p.caption ?? undefined)),
    })),

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
    // Raw slugs; the manage view resolves readable names via fetchCategories.
    categories: a.categories,
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

// Reverse of the listing-detail mapping: domain edit fields -> the add-on PATCH
// endpoint's writable fields. Only keys present on `edit` are sent, so callers
// can PATCH just what changed. Translated fields (name/summary/urls/…) must be
// sent as { lang: value } objects, not bare strings; we target the add-on's
// default locale (en-US for now).
export async function patchAddon(
  slug: string,
  edit: AddonListingEdit,
): Promise<Addon> {
  const t = (value: string | undefined) => ({ 'en-US': value ?? '' });
  const body: Record<string, unknown> = {};
  if ('name' in edit) body.name = t(edit.name);
  if ('summary' in edit) body.summary = t(edit.summary);
  if ('description' in edit) body.description = t(edit.description);
  if ('homepageUrl' in edit) body.homepage = t(edit.homepageUrl);
  if ('supportEmail' in edit) body.support_email = t(edit.supportEmail);
  if ('supportUrl' in edit) body.support_url = t(edit.supportUrl);
  if ('categories' in edit) body.categories = edit.categories;
  if ('developerComments' in edit) {
    body.developer_comments = t(edit.developerComments);
  }
  if ('experimental' in edit) body.is_experimental = edit.experimental;
  if ('requiresPayment' in edit) body.requires_payment = edit.requiresPayment;

  const data = await apiFetch<ApiAddon>(`/addons/addon/${slug}/?lang=en-US`, {
    method: 'PATCH',
    body,
  });
  return mapAddon(data);
}

// --- Authors (ownership) ---

interface ApiAuthor {
  user_id: number;
  name: string;
  email: string;
  role: AddonAuthorRole;
  listed: boolean;
}

export async function fetchAuthors(slug: string): Promise<AddonAuthor[]> {
  const data = await apiFetch<ApiAuthor[]>(
    `/addons/addon/${slug}/authors/?lang=en-US`,
  );
  return data.map((a) => ({
    userId: a.user_id,
    name: a.name,
    email: a.email,
    role: a.role,
    listed: a.listed,
  }));
}

// Authors invited but not yet accepted. Same shape as confirmed authors; the
// listing shows them in their own "pending confirmation" group.
export async function fetchPendingAuthors(
  slug: string,
): Promise<AddonAuthor[]> {
  const data = await apiFetch<ApiAuthor[]>(
    `/addons/addon/${slug}/pending-authors/?lang=en-US`,
  );
  return data.map((a) => ({
    userId: a.user_id,
    name: a.name,
    email: a.email,
    role: a.role,
    listed: a.listed,
  }));
}

export async function patchAuthor(
  slug: string,
  userId: number,
  edit: { role?: AddonAuthorRole; listed?: boolean },
): Promise<void> {
  await apiFetch(`/addons/addon/${slug}/authors/${userId}/`, {
    method: 'PATCH',
    body: edit,
  });
}

export async function deleteAuthor(
  slug: string,
  userId: number,
): Promise<void> {
  await apiFetch(`/addons/addon/${slug}/authors/${userId}/`, {
    method: 'DELETE',
  });
}

// Adds an author via the pending-authors endpoint. The invite/accept lifecycle
// is handled server-side; we just post the invitation.
export async function addAuthor(
  slug: string,
  add: AddonAuthorAdd,
): Promise<void> {
  await apiFetch(`/addons/addon/${slug}/pending-authors/`, {
    method: 'POST',
    body: { user_id: add.userId, role: add.role, listed: add.listed },
  });
}

// --- Graphic assets (multipart uploads) ---

export async function uploadIcon(slug: string, file: File): Promise<Addon> {
  const form = new FormData();
  form.append('icon', file);
  const data = await apiFetch<ApiAddon>(`/addons/addon/${slug}/?lang=en-US`, {
    method: 'PATCH',
    body: form,
  });
  return mapAddon(data);
}

export async function addPreview(slug: string, file: File): Promise<void> {
  const form = new FormData();
  form.append('image', file);
  await apiFetch(`/addons/addon/${slug}/previews/`, {
    method: 'POST',
    body: form,
  });
}

// Updates a screenshot's caption. Like other translated fields, it must be
// sent as a { lang: value } object (bare strings are rejected).
export async function patchPreview(
  slug: string,
  previewId: number,
  caption: string,
): Promise<void> {
  await apiFetch(`/addons/addon/${slug}/previews/${previewId}/?lang=en-US`, {
    method: 'PATCH',
    body: { caption: { 'en-US': caption } },
  });
}

export async function deletePreview(
  slug: string,
  previewId: number,
): Promise<void> {
  await apiFetch(`/addons/addon/${slug}/previews/${previewId}/`, {
    method: 'DELETE',
  });
}

// The static listing categories (slug + readable name), used both to render
// category names and to offer the choices in the edit form.
export async function fetchCategories(): Promise<Category[]> {
  const data = await apiFetch<Category[]>('/addons/categories/');
  return data.map((c) => ({ slug: c.slug, name: c.name, type: c.type }));
}

// EULA and privacy policy live on their own endpoint; the list API only exposes
// the has_* booleans, so the edit form fetches the text here.
export async function fetchEulaPolicy(slug: string): Promise<EulaPolicy> {
  const data = await apiFetch<{
    eula?: Localized | null;
    privacy_policy?: Localized | null;
  }>(`/addons/addon/${slug}/eula_policy/?lang=en-US`);
  return {
    eula: localized(data.eula ?? undefined),
    privacyPolicy: localized(data.privacy_policy ?? undefined),
  };
}

export async function patchEulaPolicy(
  slug: string,
  edit: EulaPolicyEdit,
): Promise<void> {
  const body: Record<string, unknown> = {};
  if ('eula' in edit) body.eula = { 'en-US': edit.eula ?? '' };
  if ('privacyPolicy' in edit) {
    body.privacy_policy = { 'en-US': edit.privacyPolicy ?? '' };
  }
  await apiFetch(`/addons/addon/${slug}/eula_policy/?lang=en-US`, {
    method: 'PATCH',
    body,
  });
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
