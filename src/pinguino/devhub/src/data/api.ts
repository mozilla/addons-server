// AMO API endpoints for the DevHub. Each function fetches over ./http and maps
// the v5 response onto our domain types. Caching, dedup, and lifetime live in
// the query layer (./queries), not here.

import { LOCALE } from '../base';
import { apiFetch } from './http';
import {
  canChangeVisibility,
  resolveAddonStatus,
  resolveVersionStatus,
  resolveVisibility,
} from './statuses';
import type {
  ActivityPage,
  Addon,
  AddonAuthor,
  AddonAuthorAdd,
  AddonAuthorRole,
  AddonCreate,
  AddonDistribution,
  AddonKind,
  AddonListingEdit,
  AddonPage,
  AgreementAcceptState,
  AgreementState,
  Category,
  Developer,
  EulaPolicy,
  EulaPolicyEdit,
  FileStatus,
  FileUpload,
  SiteStatus,
  Update,
  Version,
  VersionLicenseEdit,
  VersionPage,
} from './types';

// Paginated envelope shared by the AMO v5 list endpoints.
interface Paginated<T> {
  results?: T[];
  count?: number;
}

// v5 always serializes translated fields as a { lang: value } object.
type Localized = Record<string, string | null>;

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
  current_version?: ApiVersion | null;
  latest_listed_version?: ApiVersion | null;
  latest_unlisted_version?: ApiVersion | null;
  latest_enterprise_version?: ApiVersion | null;
  channels: AddonDistribution[];
  submit_notification_warning?: Partial<
    Record<AddonDistribution, string | null>
  >;
}

interface ApiVersionLicense {
  slug: string | null;
  is_custom: boolean;
  name: Localized | null;
  text?: Localized | null;
}

export interface ApiVersion {
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
  release_notes: Record<string, string> | null;
  is_source_editable?: boolean;
  approval_notes: string;
  source: string | null;
  edit_url: string;
  is_disabled: boolean;
  compatibility?: Record<string, { min: string; max: string }>;
  license?: ApiVersionLicense | null;
  reviewed?: string | null;
}

// The subset of an AMO v5 activity-feed entry we read (from /activity/).
interface ApiActivity {
  addon: Partial<ApiAddon>;
  id: number;
  title?: string;
  comments?: string;
  date?: string;
  user?: { name?: string } | null;
  versions?: {
    version?: string;
    channel?: AddonDistribution;
    file?: { status?: string };
    reviewed?: string | null;
  }[];
}

interface ApiSiteStatus {
  read_only: boolean;
  notice: string | null;
  submit_notification_warning: string | null;
}

// The current account, from /accounts/profile/. `name` already falls back to a
// generated name server-side; display_name is the user-chosen label when set.
interface ApiProfile {
  id: number;
  display_name?: string;
  name: string;
  username?: string;
  picture_url?: string;
  site_status?: ApiSiteStatus;
}

export function localized(value: Localized | null | undefined): string {
  if (!value) return '';
  // TODO: this logic only works when a single locale is requested with ?lang=<LOCALE>
  // in the request. Without that, all locales are returned in a nondeterminist order,
  // so a fallback to Addon.default_locale or DEFAULT_LOCALE is necessary.
  return (
    value[LOCALE] ?? value[value._default || 0] ?? Object.values(value)[0] ?? ''
  );
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

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const month = date.toLocaleString(document.documentElement.lang, { month: 'short' });
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
    lastUpdated: formatDate(a.last_updated),
    visibility: resolveVisibility(a.is_disabled ?? false),
    canChangeVisibility: canChangeVisibility(a.status),
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
    latestListedVersion: a.latest_listed_version
      ? mapVersion(a.latest_listed_version)
      : undefined,
    latestUnlistedVersion: a.latest_unlisted_version
      ? mapVersion(a.latest_unlisted_version)
      : undefined,
    latestEnterpriseVersion: a.latest_enterprise_version
      ? mapVersion(a.latest_enterprise_version)
      : undefined,
    currentVersion: a.current_version
      ? mapVersion(a.current_version)
      : undefined,
    submissionNotice: a.submit_notification_warning,
  };
}

export function mapVersion(v: ApiVersion): Version {
  let license = null;
  if (v.license) {
    license = {
      slug: v.license.slug,
      is_custom: v.license.is_custom,
      name: localized(v.license.name),
      text: localized(v.license.text),
    };
  }
  return {
    id: v.id,
    version: v.version,
    channel: v.channel,
    file: v.file,
    release_notes: localized(v.release_notes),
    is_source_editable: v.is_source_editable,
    approval_notes: v.approval_notes,
    source: v.source,
    edit_url: v.edit_url,
    is_disabled: v.is_disabled,
    compatibility: v.compatibility,
    license: license,
    reviewed: v.reviewed,
  };
}

export function mapActivity(a: ApiActivity): Update {
  // An entry can touch several versions (e.g. a bulk approval); the feed row
  // describes the first, matching what the activity title names.
  const version = a.versions?.[0];
  return {
    id: String(a.id),
    title: a.title ?? 'Update',
    message: a.comments ?? '',
    version: version?.version ?? '',
    versionStatus: version?.file?.status
      ? resolveVersionStatus(version.file.status, {
          reviewed: version.reviewed,
        })
      : undefined,
    channel: version?.channel,
    date: formatDate(a.date),
    user: undefinedIfEmpty(decodeEntities(a.user?.name ?? '')),
    addonName: decodeEntities(localized(a.addon?.name)),
    addonSlug: a.addon?.slug ?? '',
  };
}

function mapSiteStatus(data?: ApiSiteStatus): SiteStatus {
  return {
    readOnly: data?.read_only ?? false,
    siteNotice: data?.notice ?? null,
    submissionNotice: data?.submit_notification_warning ?? null,
  };
}

export async function fetchProfile(): Promise<Developer> {
  const data = await apiFetch<ApiProfile>('/accounts/profile/');
  return {
    id: String(data.id),
    name: data.name,
    pictureUrl: data.picture_url,
    siteStatus: mapSiteStatus(data.site_status),
  };
}

export async function fetchSiteStatus(): Promise<SiteStatus> {
  const data = await apiFetch<ApiSiteStatus>('/site/');
  return mapSiteStatus(data);
}

// Dictionaries and language packs are extensions to us, as they are to
// mapAddon and to the classic devhub's dashboard.
const KIND_TYPES: Record<AddonKind, string> = {
  extension: 'extension,dictionary,language',
  theme: 'statictheme',
};

// Newest activity first. The leading `-` is load-bearing: the API sorts
// ascending by default, so dropping it buries the add-ons a developer is
// actually working on. `last_updated` covers "added" too — the server falls
// back to the creation date for an add-on that has never shipped a version.
// `-id` only breaks ties, so paging can't reshuffle same-timestamp rows.
const SORT = '-last_updated,-id';

// Lists one kind of the add-ons the authenticated session owns; no author
// param needed.
export async function fetchAddons(kind: AddonKind): Promise<AddonPage> {
  const params = new URLSearchParams({
    lang: LOCALE,
    page_size: '50',
    sort: SORT,
    type: KIND_TYPES[kind],
  });
  const data = await apiFetch<Paginated<ApiAddon>>(`/addons/addon/?${params}`);
  const results = (data.results ?? []).map(mapAddon);
  return { results, count: data.count ?? results.length };
}

// Builds an add-on request body from the edit fields. Keys already match the
// API; only keys present on `edit` are sent (so callers PATCH just what
// changed), and the translated fields are wrapped as { lang: value } objects
// (bare strings are rejected) targeting the default locale (en-US for now).
function addonBody(edit: AddonListingEdit): Record<string, unknown> {
  const t = (value: string | undefined) => ({ [LOCALE]: value ?? '' });
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
  return body;
}

// Unfiltered by type, so one request covers both kinds: the header's menu
// needs each add-on's own kind for its icon, not a count per kind.
export async function fetchNavAddons(limit: number): Promise<Addon[]> {
  const params = new URLSearchParams({
    lang: LOCALE,
    page_size: String(limit),
    sort: SORT,
  });
  const data = await apiFetch<Paginated<ApiAddon>>(`/addons/addon/?${params}`);
  return (data.results ?? []).map(mapAddon);
}

export async function patchAddon(
  slug: string,
  edit: AddonListingEdit,
): Promise<Addon> {
  const data = await apiFetch<ApiAddon>(
    `/addons/addon/${slug}/?lang=${LOCALE}`,
    {
      method: 'PATCH',
      body: addonBody(edit),
    },
  );
  return mapAddon(data);
}

function buildLicense(
  license: string | undefined,
  custom: { name: string; text: string } | undefined,
): Record<string, unknown> {
  if (custom) {
    return {
      custom_license: {
        name: { [LOCALE]: custom.name },
        text: { [LOCALE]: custom.text },
      },
    };
  }
  return license ? { license } : {};
}

export async function postAddon(
  create: AddonCreate,
): Promise<{ addon: Addon; version: Version }> {
  const { version, ...listing } = create;
  const data = await apiFetch<ApiAddon & { version: Version }>(
    `/addons/addon/?lang=${LOCALE}`,
    {
      method: 'POST',
      body: {
        ...addonBody(listing),
        version: {
          upload: version.upload,
          ...buildLicense(version.license, version.custom_license),
        },
      },
    },
  );
  return { addon: mapAddon(data), version: data.version };
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
    `/addons/addon/${slug}/authors/?lang=${LOCALE}`,
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
    `/addons/addon/${slug}/pending-authors/?lang=${LOCALE}`,
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

// Deleting an add-on is irreversible, so the API gates it behind a token from
// its own endpoint, good for 60 seconds and for this add-on only. Fetching it
// and spending it belong together — a token held any longer just expires.
export async function deleteAddon(slug: string): Promise<void> {
  const { delete_confirm: token } = await apiFetch<{ delete_confirm: string }>(
    `/addons/addon/${slug}/delete_confirm/`,
  );
  await apiFetch(
    `/addons/addon/${slug}/?delete_confirm=${encodeURIComponent(token)}`,
    { method: 'DELETE' },
  );
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
  const data = await apiFetch<ApiAddon>(
    `/addons/addon/${slug}/?lang=${LOCALE}`,
    {
      method: 'PATCH',
      body: form,
    },
  );
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
  await apiFetch(`/addons/addon/${slug}/previews/${previewId}/?lang=${LOCALE}`, {
    method: 'PATCH',
    body: { caption: { [LOCALE]: caption } },
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

export async function fetchAddon(slug: string): Promise<Addon> {
  const data = await apiFetch<ApiAddon>(`/addons/addon/${slug}/?lang=${LOCALE}`);
  return mapAddon(data);
}

export async function fetchAddonSource(slug: string): Promise<Addon> {
  const data = await apiFetch<ApiAddon>(
    `/addons/addon/${slug}/?lang=${LOCALE}&show_source=true`,
  );
  return mapAddon(data);
}

// EULA and privacy policy live on their own endpoint; the list API only exposes
// the has_* booleans, so the edit form fetches the text here.
export async function fetchEulaPolicy(
  slug: string,
  showSource = false,
): Promise<EulaPolicy> {
  const data = await apiFetch<{
    eula?: Localized | null;
    privacy_policy?: Localized | null;
  }>(
    `/addons/addon/${slug}/eula_policy/?lang=${LOCALE}${showSource ? '&show_source=true' : ''}`,
  );
  return {
    eula: localized(data.eula ?? undefined),
    privacyPolicy: localized(data.privacy_policy ?? undefined),
  };
}

// Any translated field is cleared per locale, and the API rejects nulling the
// default locale while other translations survive — so clearing one means
// nulling every locale it currently has.
export function clearLocalized(
  current?: Localized | null,
): Record<string, null> {
  const locales = Object.keys(current ?? {}).filter(
    // A single-translation response carries `_default` alongside the locales.
    (locale) => !locale.startsWith('_'),
  );
  return Object.fromEntries(
    [...new Set([...locales, LOCALE])].map((locale) => [locale, null]),
  );
}

export async function patchEulaPolicy(
  slug: string,
  edit: EulaPolicyEdit,
): Promise<void> {
  // We only ever edit one locale, so clearing needs the full locale set: fetch it
  // without `lang` rather than trusting one locales view of the policy.
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
        ? clearLocalized(current?.eula)
        : { [LOCALE]: edit.eula };
  }
  if ('privacyPolicy' in edit) {
    body.privacy_policy =
      edit.privacyPolicy == null
        ? clearLocalized(current?.privacy_policy)
        : { [LOCALE]: edit.privacyPolicy };
  }
  await apiFetch(`/addons/addon/${slug}/eula_policy/?lang=${LOCALE}`, {
    method: 'PATCH',
    body,
  });
}

export const ACTIVITY_PAGE_SIZE = 20;

// Paged server-side, so the URL's `?page=` maps straight onto the API's paging.
// Without a slug, the feed spans all of the authenticated user's add-ons.
export async function fetchActivity(
  slug: string | undefined,
  page: number,
  version?: number,
): Promise<ActivityPage> {
  const params = new URLSearchParams({
    lang: LOCALE,
    page: String(page),
    page_size: String(ACTIVITY_PAGE_SIZE),
  });
  if (slug) {
    params.set('addon', slug);
  }
  if (version) {
    params.set('version', String(version));
  }
  const data = await apiFetch<Paginated<ApiActivity>>(`/activity/?${params}`);
  return {
    items: (data.results ?? []).map(mapActivity),
    total: data.count ?? 0,
  };
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

export type SupportCategory = 'policy' | 'technical' | 'other';

export interface SupportRequest {
  category: SupportCategory;
  summary: string;
  body: string;
}

export async function postSupport(
  payload: SupportRequest,
): Promise<SupportRequest> {
  return await apiFetch<SupportRequest>('/developers/support/', {
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

export async function fetchVersion(
  slug: string,
  id: number,
  showSource = false,
): Promise<Version> {
  return await apiFetch<Version>(
    `${versionPath(slug, id)}${showSource ? '?show_source=true' : ''}`,
  );
}

export async function fetchLatestVersion(
  slug: string,
): Promise<Version | null> {
  const data = await apiFetch<Paginated<Version>>(
    `${versionPath(slug)}?filter=all_with_unlisted&page_size=1`,
  );
  return data.results?.[0] ?? null;
}

export async function postVersion(
  slug: string,
  uploadUuid: string,
  license: VersionLicenseEdit = {},
): Promise<Version> {
  return await apiFetch<Version>(versionPath(slug), {
    method: 'POST',
    body: {
      upload: uploadUuid,
      ...buildLicense(license.license, license.custom_license),
    },
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

export const VERSION_PAGE_SIZE = 20;

export async function deleteVersion(slug: string, id: number): Promise<void> {
  await apiFetch(versionPath(slug, id), { method: 'DELETE' });
}

export async function postReviewNote(
  slug: string,
  id: number,
  comments: string,
): Promise<void> {
  await apiFetch(`${versionPath(slug, id)}reviewnotes/`, {
    method: 'POST',
    body: { comments },
  });
}

export async function fetchAppVersions(app: string): Promise<string[]> {
  const data = await apiFetch<{ versions: string[] }>(`/applications/${app}/`);
  return data.versions;
}

export async function fetchVersions(
  slug: string,
  lang: string,
  page?: number,
): Promise<VersionPage> {
  const data = await apiFetch<Paginated<Version>>(
    `${versionPath(slug)}?${new URLSearchParams({
      filter: 'all_with_unlisted',
      lang,
      ...(page && { page: String(page), page_size: String(VERSION_PAGE_SIZE) }),
    })}`,
  );
  return {
    items: data.results ?? [],
    total: data.count ?? 0,
  };
}

export async function patchVersionLicense(
  slug: string,
  id: number,
  license: string | undefined,
  custom?: { name: string; text: string },
): Promise<Version> {
  return await patchVersion(slug, id, buildLicense(license, custom));
}

// Ends the current session server-side.
// Callers should then reload so all client state is rebuilt as signed-out.
export async function deleteSession(): Promise<void> {
  await apiFetch('/accounts/session/', { method: 'DELETE' });
}
