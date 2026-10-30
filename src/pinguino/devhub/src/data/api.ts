// AMO API endpoints for the DevHub. Each function fetches over ./http and maps
// the v5 response onto our domain types. Caching, dedup, and lifetime live in
// the query layer (./queries), not here.

import { apiFetch } from './http';
import {
  resolveAddonStatus,
  resolveVisibility,
  VERSION_STATUS,
} from './statuses';
import type {
  Addon,
  AddonAuthor,
  AddonAuthorAdd,
  AddonAuthorRole,
  AddonDistribution,
  AddonKind,
  AddonListingEdit,
  AgreementAcceptState,
  AgreementState,
  Category,
  Developer,
  EulaPolicy,
  EulaPolicyEdit,
  FileUpload,
  Update,
  Version,
} from './types';

// Paginated envelope shared by the AMO v5 list endpoints.
interface Paginated<T> {
  results?: T[];
}

// v5 always serializes translated fields as a { lang: value } object.
type Localized = Record<string, string>;

// AMO wraps external links as an "outgoing URL" object; its `url`/`outgoing`
// are themselves translated. We want the plain destination URL.
type ApiUrl = { url?: Localized; outgoing?: Localized } | null;

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
  developer_comments?: Localized | null;
  homepage?: ApiUrl;
  support_email?: Localized | null;
  support_url?: ApiUrl;
  average_daily_users?: number;
  ratings?: { average?: number; count?: number };
  categories?: string[];
  is_experimental?: boolean;
  requires_payment?: boolean;
  has_eula?: boolean;
  has_privacy_policy?: boolean;
  previews?: {
    id?: number;
    image_url?: string;
    thumbnail_url?: string;
    caption?: Localized | null;
  }[];
  current_version?: { version?: string; license?: { name?: Localized } };
  channels: AddonDistribution[];
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
  id: number;
  display_name?: string;
  name: string;
  username?: string;
  picture_url?: string;
}

export function localized(
  value: string | Record<string, string> | undefined,
): string {
  if (!value) return '';
  if (typeof value === 'string') return value;
  return value['en-US'] ?? Object.values(value)[0] ?? '';
}

// Resolve an AMO outgoing-URL field to its (translated) destination URL.
function urlValue(value: ApiUrl | undefined): string {
  if (!value) return '';
  return localized(value.url);
}

function undefinedIfEmpty(s: string): string | undefined {
  return s === '' ? undefined : s;
}

// The API returns the cleaned translation (`localized_string_clean`), which
// HTML-escapes `& < >`. For plain-text fields that's the only transform, so we
// decode it back for display/editing. (HTML fields like description are also
// linkified and need the raw value from the API — not handled here.)
function decodeEntities(s: string): string {
  if (!s.includes('&')) return s;
  const el = document.createElement('textarea');
  el.innerHTML = s;
  return el.value;
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
  const preview = a.previews?.[0];

  return {
    slug: a.slug,
    name: decodeEntities(localized(a.name)),
    kind,
    icon: kind === 'theme' ? 'themes' : 'extension',
    status: resolveAddonStatus(a.status),
    version: a.current_version?.version ?? '—',
    lastUpdated: formatDate(a.last_updated),
    visibility: resolveVisibility(a.is_disabled ?? false),
    channels: a.channels,
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
    summary: undefinedIfEmpty(
      decodeEntities(localized(a.summary ?? undefined)),
    ),
    description: undefinedIfEmpty(localized(a.description ?? undefined)),
    developerComments: undefinedIfEmpty(
      localized(a.developer_comments ?? undefined),
    ),
    // Raw slugs; the manage view resolves readable names via fetchCategories.
    categories: a.categories,
    flags: {
      experimental: a.is_experimental ?? false,
      requiresPayment: a.requires_payment ?? false,
      hasEula: a.has_eula ?? false,
      hasPrivacyPolicy: a.has_privacy_policy ?? false,
    },
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
    title,
    message: a.comments ?? '',
    version: a.versions?.[0]?.version ?? '',
    versionStatus: approved ? VERSION_STATUS.public : undefined,
    tags: [],
    date: formatDate(a.date),
    addonSlug: a.addon?.slug ?? '',
  };
}

export async function fetchProfile(): Promise<Developer> {
  const data = await apiFetch<ApiProfile>('/accounts/profile/');
  return {
    id: String(data.id),
    name: data.name,
    pictureUrl: data.picture_url,
  };
}

// Lists the add-ons the authenticated session owns; no author param needed.
export async function fetchAddons(): Promise<Addon[]> {
  const data = await apiFetch<Paginated<ApiAddon>>(
    '/addons/addon/?lang=en-US&page_size=50',
  );
  return (data.results ?? []).map(mapAddon);
}

// Builds the add-on PATCH body from the edit fields. Keys already match the
// API; only keys present on `edit` are sent (so callers PATCH just what
// changed), and the translated fields are wrapped as { lang: value } objects
// (bare strings are rejected) targeting the default locale (en-US for now).
export async function patchAddon(
  slug: string,
  edit: AddonListingEdit,
): Promise<Addon> {
  const t = (value: string | undefined) => ({ 'en-US': value ?? '' });
  const TRANSLATED = [
    'name',
    'summary',
    'description',
    'homepage',
    'support_email',
    'support_url',
    'developer_comments',
  ] as const;
  const body: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(edit)) {
    body[key] = (TRANSLATED as readonly string[]).includes(key)
      ? t(value as string | undefined)
      : value;
  }

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

// Any translated field is cleared per locale, and the API rejects nulling the
// default locale while other translations survive — so clearing one means
// nulling every locale it currently has.
export function clearTranslations(
  current?: Localized | null,
): Record<string, null> {
  const locales = Object.keys(current ?? {}).filter(
    // A single-translation response carries `_default` alongside the locales.
    (locale) => !locale.startsWith('_'),
  );
  return Object.fromEntries(
    [...new Set([...locales, 'en-US'])].map((locale) => [locale, null]),
  );
}

export async function patchEulaPolicy(
  slug: string,
  edit: EulaPolicyEdit,
): Promise<void> {
  // We only ever edit en-US, so clearing needs the full locale set: fetch it
  // without `lang` rather than trusting the en-US view of the policy.
  const current =
    ('eula' in edit && edit.eula == null) ||
    ('privacyPolicy' in edit && edit.privacyPolicy == null)
      ? await apiFetch<{
          eula?: Localized | null;
          privacy_policy?: Localized | null;
        }>(`/addons/addon/${slug}/eula_policy/`)
      : null;

  const body: Record<string, unknown> = {};
  if ('eula' in edit) {
    body.eula =
      edit.eula == null
        ? clearTranslations(current?.eula)
        : { 'en-US': edit.eula };
  }
  if ('privacyPolicy' in edit) {
    body.privacy_policy =
      edit.privacyPolicy == null
        ? clearTranslations(current?.privacy_policy)
        : { 'en-US': edit.privacyPolicy };
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

export async function postUpload(
  file: File,
  channel: AddonDistribution,
): Promise<FileUpload> {
  const body = new FormData();
  body.append('upload', file);
  body.append('channel', channel);
  return await apiFetch<FileUpload>('/addons/upload/', {
    method: 'POST',
    body,
  });
}

export async function fetchUpload(uuid: string): Promise<FileUpload> {
  return await apiFetch<FileUpload>(`/addons/upload/${uuid}/`);
}

const versionPath = (slug: string, id?: number) => {
  return `/addons/addon/${encodeURIComponent(slug)}/versions/${id ? `${id}/` : ''}`;
};

export async function fetchVersion(slug: string, id: number): Promise<Version> {
  return await apiFetch<Version>(versionPath(slug, id));
}

export async function postVersion(
  slug: string,
  uploadUuid: string,
): Promise<Version> {
  return await apiFetch<Version>(versionPath(slug), {
    method: 'POST',
    body: { upload: uploadUuid },
  });
}

export async function patchVersion(
  slug: string,
  id: number,
  body: object,
): Promise<Version> {
  return await apiFetch<Version>(versionPath(slug, id), {
    method: 'PATCH',
    body,
  });
}

// Ends the current session server-side.
// Callers should then reload so all client state is rebuilt as signed-out.
export async function deleteSession(): Promise<void> {
  await apiFetch('/accounts/session/', { method: 'DELETE' });
}
