// Query definitions: stable keys, and per-query lifetimes
// in one place. Components attach these controllers and read reactive
// { data, isPending, isError } — they never call fetch or manage loading state.

import {
  createInfiniteQueryController,
  createQueryController,
  type InfiniteData,
} from '@tanstack/lit-query';
import type { ReactiveControllerHost } from 'lit';
import { LOCALE } from '../base';
import {
  addAuthor,
  addPreview,
  deleteAddon,
  deleteAuthor,
  deletePreview,
  deleteSession,
  deleteVersion,
  fetchActivity,
  fetchAddon,
  fetchAddonSource,
  fetchAddons,
  fetchAgreement,
  fetchAppVersions,
  fetchAuthors,
  fetchCategories,
  fetchEulaPolicy,
  fetchLatestVersion,
  fetchNavAddons,
  fetchPendingAuthors,
  fetchProfile,
  fetchSiteStatus,
  fetchUpload,
  fetchVersion,
  fetchVersions,
  patchAddon,
  patchAuthor,
  patchEulaPolicy,
  patchPreview,
  patchVersion,
  patchVersionLicense,
  postAddon,
  postAgreement,
  postReviewNote,
  postUpload,
  postVersion,
  uploadIcon,
} from './api';
import { errorStatus } from './http';
import { isAddonOwner } from './permissions';
import { queryClient } from './query-client';
import type { AddonVisibility } from './statuses';
import type {
  ActivityPage,
  AddonAuthorAdd,
  AddonAuthorRole,
  AddonCreate,
  AddonDistribution,
  AddonKind,
  AddonListingEdit,
  AddonPage,
  AgreementAcceptState,
  EulaPolicyEdit,
  FileUpload,
  Version,
  VersionEdit,
  VersionLicenseEdit,
} from './types';

// Keys identify cache entries. Every add-on entry hangs off the `addons`
// prefix, so invalidating that covers both kind lists and any single add-on we
// fetched on its own.
export const queryKeys = {
  profile: ['profile'] as const,
  siteStatus: ['site-status'] as const,
  addons: ['addons'] as const,
  addonList: (kind: AddonKind) => ['addons', 'list', kind] as const,
  addon: (slug: string) => ['addons', 'detail', slug] as const,
  addonNav: (limit: number) => ['addons', 'nav', limit] as const,
  agreement: ['agreement'] as const,
  categories: ['categories'] as const,
  upload: (uuid: string) => ['upload', uuid] as const,
  version: (slug: string, id: number) => ['version', slug, id] as const,
  versions: (slug: string) => ['versions', slug] as const,
  latestVersion: (slug: string) => ['latest-version', slug] as const,
  appVersions: (app: string | undefined) => ['app-versions', app] as const,
};

// Keyed by add-on/version and page; a missing slug (the all-add-ons feed) normalises to
// null so it stays a stable, distinct cache entry.
const activityKey = (
  slug: string | undefined,
  page: number,
  version?: number,
) => ['activity', slug ?? null, version ?? null, page] as const;

// The infinite (scroll-to-load) variant of the feed. Shares the 'activity'
// prefix so one invalidate refreshes both the paged and infinite caches.
// A version-scoped feed nests under its add-on's key, so invalidating the
// add-on's feed also refreshes its versions' feeds.
const activityInfiniteKey = (slug: string | undefined, version?: number) =>
  version
    ? (['activity', 'infinite', slug ?? null, version] as const)
    : (['activity', 'infinite', slug ?? null] as const);

// The static category list rarely changes, so keep it for the session.
export function categoriesQuery(host: ReactiveControllerHost) {
  return createQueryController(
    host,
    () => ({
      queryKey: queryKeys.categories,
      queryFn: fetchCategories,
      staleTime: Number.POSITIVE_INFINITY,
    }),
    queryClient,
  );
}

// The signed-in developer. Session-lived, so it survives navigation without a
// refetch; invalidate queryKeys.profile explicitly after a profile edit.
export function profileQuery(host: ReactiveControllerHost) {
  return createQueryController(
    host,
    () => ({
      queryKey: queryKeys.profile,
      queryFn: fetchProfile,
    }),
    queryClient,
  );
}

// Standalone site status, used as a fallback when the profile query can't
// supply it (signed out, or any other profile failure). Gated by `getEnabled`
// so the request only fires once, and if, that fallback is actually needed.
export function siteStatusQuery(
  host: ReactiveControllerHost,
  getEnabled: () => boolean = () => true,
) {
  return createQueryController(
    host,
    () => ({
      queryKey: queryKeys.siteStatus,
      queryFn: fetchSiteStatus,
      enabled: getEnabled(),
    }),
    queryClient,
  );
}

const ADDON_KINDS: readonly AddonKind[] = ['extension', 'theme'];

const retryServerErrors = (count: number, error: Error) =>
  errorStatus(error) >= 500 && count < 1;

// One list per kind, because the API pages extensions and themes together: ask
// once and a developer with over a page of add-ons gets an arbitrary split of
// the two, under a `count` covering only what came back.
//
// These are the signed-in developer's own add-ons, so asking while signed out
// only earns a 401; `getEnabled` lets a caller wait for the profile first.
export function addonsQuery(
  host: ReactiveControllerHost,
  kind: AddonKind,
  getEnabled: () => boolean = () => true,
) {
  return createQueryController(
    host,
    () => ({
      queryKey: queryKeys.addonList(kind),
      queryFn: () => fetchAddons(kind),
      enabled: getEnabled(),
    }),
    queryClient,
  );
}

export type AddonsQuery = ReturnType<typeof addonsQuery>;

export function navAddonsQuery(
  host: ReactiveControllerHost,
  limit: number,
  getEnabled: () => boolean = () => true,
) {
  return createQueryController(
    host,
    () => ({
      queryKey: queryKeys.addonNav(limit),
      queryFn: () => fetchNavAddons(limit),
      enabled: getEnabled(),
    }),
    queryClient,
  );
}

// Read without an observer, so the manage page neither triggers the
// dashboard's list requests nor waits on them.
function addonFromLists(slug: string, uuid?: string) {
  for (const kind of ADDON_KINDS) {
    const state = queryClient.getQueryState<AddonPage>(
      queryKeys.addonList(kind),
    );
    const addon = state?.data?.results.find(
      (a) => a.slug === slug || (uuid !== undefined && a.uuid === uuid),
    );
    if (addon) return { addon, updatedAt: state?.dataUpdatedAt };
  }
}

// Those lists are only one page deep, so a miss means fetching the add-on
// itself rather than calling it missing.
export function addonQuery(
  host: ReactiveControllerHost,
  getSlug: () => string,
) {
  // A rename refetches the list before the URL catches up, so until it does
  // the add-on is found by the GUID it last had rather than looking deleted.
  let seen: { slug: string; uuid?: string } | undefined;
  return createQueryController(
    host,
    () => {
      const slug = getSlug();
      const seed = addonFromLists(
        slug,
        seen?.slug === slug ? seen.uuid : undefined,
      );
      if (seed) seen = { slug, uuid: seed.addon.uuid };
      return {
        queryKey: queryKeys.addon(slug),
        queryFn: () => fetchAddon(slug),
        enabled: Boolean(slug),
        // Dated to the list fetch, so a seed ages with its source.
        initialData: seed?.addon,
        initialDataUpdatedAt: seed?.updatedAt,
        retry: retryServerErrors,
      };
    },
    queryClient,
  );
}

export async function getAddon(slug: string) {
  const pages = await Promise.all(
    ADDON_KINDS.map((kind) =>
      queryClient.query({
        queryKey: queryKeys.addonList(kind),
        queryFn: () => fetchAddons(kind),
      }),
    ),
  );
  const listed = pages
    .flatMap((page) => page.results)
    .find((a) => a.slug === slug);
  if (listed) return listed;
  // Beyond the first page of the lists, only the API can say it doesn't exist.
  return await queryClient
    .query({
      queryKey: queryKeys.addon(slug),
      queryFn: () => fetchAddon(slug),
      retry: retryServerErrors,
    })
    .catch(() => undefined);
}

export function themePreviewQuery(
  host: ReactiveControllerHost,
  getSlug: () => string,
  getEnabled: () => boolean = () => true,
) {
  return createQueryController(
    host,
    () => ({
      queryKey: ['theme-preview', getSlug()],
      queryFn: async () => {
        const addon = await fetchAddon(getSlug());
        if (addon.previewUrl) {
          await queryClient.invalidateQueries({ queryKey: queryKeys.addons });
        }
        return addon;
      },
      enabled: Boolean(getSlug()) && getEnabled(),
      refetchInterval: (query) => (query.state.data?.previewUrl ? false : 1000),
    }),
    queryClient,
  );
}

// Persist Listing Details edits, then refresh the cached add-on lists so the
// manage view (which reads from it) reflects the saved values.
export async function updateAddon(slug: string, edit: AddonListingEdit) {
  const updated = await patchAddon(slug, edit);
  await queryClient.invalidateQueries({ queryKey: queryKeys.addons });
  return updated;
}

// Hide or unhide a listing. `invisible` is the author's own setting, which the
// API takes as `is_disabled`; Mozilla's own disabling isn't writable here.
export async function setAddonVisibility(
  slug: string,
  visibility: AddonVisibility,
) {
  return updateAddon(slug, { is_disabled: visibility === 'invisible' });
}

// Permanently delete an add-on. Invalidating alone isn't enough: it marks the
// list stale and refetches only *active* observers, and the manage view is
// unmounting as this resolves — so the deleted add-on would sit in the cache
// and render on the dashboard. Drop it by hand, then invalidate so the
// server's own list still replaces ours.
export async function removeAddon(slug: string) {
  await deleteAddon(slug);
  queryClient.removeQueries({ queryKey: queryKeys.addon(slug) });
  for (const kind of ADDON_KINDS) {
    queryClient.setQueryData(queryKeys.addonList(kind), (page?: AddonPage) => {
      if (!page) return page;
      const results = page.results.filter((addon) => addon.slug !== slug);
      return results.length === page.results.length
        ? page
        : { results, count: page.count - 1 };
    });
  }
  // The dashboard lists the add-on twice: as a card, and by name in the
  // activity feed. The feed drops a deleted add-on's entries server-side, so
  // this one has to go too or the dashboard keeps naming what we just deleted.
  queryClient.setQueryData(
    activityInfiniteKey(undefined),
    (data?: InfiniteData<ActivityPage>) => {
      if (!data) return data;
      let removed = 0;
      const pages = data.pages.map((page) => {
        const items = page.items.filter((item) => item.addonSlug !== slug);
        removed += page.items.length - items.length;
        return { items, total: page.total };
      });
      if (!removed) return data;
      return {
        ...data,
        pages: pages.map((page) => ({ ...page, total: page.total - removed })),
      };
    },
  );
  await queryClient.invalidateQueries({ queryKey: queryKeys.addons });
  await queryClient.invalidateQueries({ queryKey: ['activity'] });
}

const eulaPolicyKey = (slug: string) => ['eula-policy', slug] as const;

// The EULA/privacy text (separate endpoint), for the view-mode preview or the
// unsanitized source for the edit form. Gated by `getEnabled` so it
// only fetches when the add-on actually has a policy.
export function eulaPolicyQuery(
  host: ReactiveControllerHost,
  getSlug: () => string,
  getEnabled: () => boolean = () => true,
  showSource = false,
) {
  return createQueryController(
    host,
    () => ({
      queryKey: [...eulaPolicyKey(getSlug()), showSource],
      queryFn: () => fetchEulaPolicy(getSlug(), showSource),
      enabled: getEnabled(),
    }),
    queryClient,
  );
}

export function addonSourceQuery(
  host: ReactiveControllerHost,
  getSlug: () => string,
  getEnabled: () => boolean = () => true,
) {
  return createQueryController(
    host,
    () => ({
      queryKey: [...queryKeys.addons, 'source', getSlug()],
      queryFn: () => fetchAddonSource(getSlug()),
      enabled: getEnabled(),
    }),
    queryClient,
  );
}

// One version.
export function versionQuery(
  host: ReactiveControllerHost,
  getSlug: () => string,
  getId: () => number,
  getEnabled: () => boolean = () => true,
  showSource = false,
) {
  return createQueryController(
    host,
    () => {
      const key = queryKeys.version(getSlug(), getId());
      return {
        queryKey: showSource ? [...key, 'source'] : key,
        queryFn: () => fetchVersion(getSlug(), getId(), showSource),
        enabled: Boolean(getSlug() && getId() && getEnabled()),
      };
    },
    queryClient,
  );
}

export function getLatestVersion(slug: string) {
  return queryClient.query({
    queryKey: queryKeys.latestVersion(slug),
    queryFn: () => fetchLatestVersion(slug),
  });
}

export function getVersions(slug: string) {
  return queryClient.query({
    queryKey: queryKeys.versions(slug),
    queryFn: () => fetchVersions(slug, LOCALE ?? 'en-US'),
  });
}

// `loaded` is one page at the API's default of 25, so a longer history can
// deep-link to a version past it — fetch that one rather than calling it gone.
export async function getVersion(slug: string, id: number, loaded: Version[]) {
  return (
    loaded.find((v) => v.id === id) ??
    (await queryClient
      .query({
        queryKey: queryKeys.version(slug, id),
        queryFn: () => fetchVersion(slug, id),
        retry: retryServerErrors,
      })
      .catch(() => undefined))
  );
}

// EULA/privacy text is a separate endpoint; refresh the add-on list after so the
// has_* badges reflect the change, and the policy text so the preview updates.
export async function updateEulaPolicy(slug: string, edit: EulaPolicyEdit) {
  await patchEulaPolicy(slug, edit);
  await queryClient.invalidateQueries({ queryKey: queryKeys.addons });
  await queryClient.invalidateQueries({ queryKey: eulaPolicyKey(slug) });
}

// --- Authors ---

const authorsKey = (slug: string) => ['authors', slug] as const;
const pendingAuthorsKey = (slug: string) => ['pending-authors', slug] as const;

export function authorsQuery(
  host: ReactiveControllerHost,
  getSlug: () => string,
) {
  return createQueryController(
    host,
    () => ({
      queryKey: authorsKey(getSlug()),
      queryFn: () => fetchAuthors(getSlug()),
    }),
    queryClient,
  );
}

// Authors invited but not yet confirmed, shown in their own group.
export function pendingAuthorsQuery(
  host: ReactiveControllerHost,
  getSlug: () => string,
) {
  return createQueryController(
    host,
    () => ({
      queryKey: pendingAuthorsKey(getSlug()),
      queryFn: () => fetchPendingAuthors(getSlug()),
    }),
    queryClient,
  );
}

// Whether the signed-in developer owns this add-on, from the two queries that
// answer it together. Both are shared keys, so a page that already shows the
// authors or the profile pays nothing extra to ask.
export function addonOwnershipQuery(
  host: ReactiveControllerHost,
  getSlug: () => string,
) {
  const authors = authorsQuery(host, getSlug);
  const profile = profileQuery(host);
  return () => isAddonOwner(authors().data, profile().data?.id);
}

export async function updateAuthor(
  slug: string,
  userId: number,
  edit: { role?: AddonAuthorRole; listed?: boolean },
) {
  await patchAuthor(slug, userId, edit);
  await queryClient.invalidateQueries({ queryKey: authorsKey(slug) });
}

export async function removeAuthor(slug: string, userId: number) {
  await deleteAuthor(slug, userId);
  await queryClient.invalidateQueries({ queryKey: authorsKey(slug) });
}

// A new author starts as a pending invitation, so refresh that group too.
export async function createAuthor(slug: string, add: AddonAuthorAdd) {
  await addAuthor(slug, add);
  await queryClient.invalidateQueries({ queryKey: authorsKey(slug) });
  await queryClient.invalidateQueries({ queryKey: pendingAuthorsKey(slug) });
}

// --- Graphic assets --- (refresh the add-on list so icon/screenshots update)

export async function updateIcon(slug: string, file: File) {
  await uploadIcon(slug, file);
  await queryClient.invalidateQueries({ queryKey: queryKeys.addons });
}

export async function createPreview(slug: string, file: File) {
  await addPreview(slug, file);
  await queryClient.invalidateQueries({ queryKey: queryKeys.addons });
}

export async function updatePreview(
  slug: string,
  previewId: number,
  caption: string,
) {
  await patchPreview(slug, previewId, caption);
  await queryClient.invalidateQueries({ queryKey: queryKeys.addons });
}

export async function removePreview(slug: string, previewId: number) {
  await deletePreview(slug, previewId);
  await queryClient.invalidateQueries({ queryKey: queryKeys.addons });
}

// Keyed by add-on and page, so paging back and forth is served from cache. An
// undefined slug spans all of the user's add-ons (the dashboard feed).
export function activityQuery(
  host: ReactiveControllerHost,
  getSlug: (() => string) | undefined,
  getPage: () => number,
  getVersion?: () => number,
) {
  return createQueryController(
    host,
    () => {
      const slug = getSlug?.();
      const page = getPage();
      const version = getVersion?.();
      return {
        queryKey: activityKey(slug, page, version),
        queryFn: () => fetchActivity(slug, page, version),
        // Wait for a slug only when one is expected; the all-add-ons feed fetches
        // immediately.
        enabled: !getSlug || Boolean(slug),
      };
    },
    queryClient,
  );
}

export async function replyToVersion(
  slug: string,
  id: number,
  comments: string,
) {
  await postReviewNote(slug, id, comments);
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ['activity', slug] }),
    queryClient.invalidateQueries({ queryKey: activityInfiniteKey(slug) }),
  ]);
}

// The feed as an infinite query: each page is fetched on demand as the reader
// scrolls. `getNextPageParam` stops once we've loaded every row the server has.
export function activityInfiniteQuery(
  host: ReactiveControllerHost,
  getSlug?: () => string,
  getVersion?: () => number,
) {
  return createInfiniteQueryController(
    host,
    () => {
      const slug = getSlug?.();
      const version = getVersion?.();
      return {
        queryKey: activityInfiniteKey(slug, version),
        queryFn: ({ pageParam }) => fetchActivity(slug, pageParam, version),
        initialPageParam: 1,
        getNextPageParam: (lastPage: ActivityPage, pages: ActivityPage[]) => {
          const loaded = pages.reduce((n, page) => n + page.items.length, 0);
          return loaded < lastPage.total ? pages.length + 1 : undefined;
        },
        // Wait for a slug only when one is expected; the all-add-ons feed fetches
        // immediately.
        enabled: !getSlug || Boolean(slug),
      };
    },
    queryClient,
  );
}

// Fetches developer agreement information.
export function agreementQuery(host: ReactiveControllerHost) {
  return createQueryController(
    host,
    () => ({
      queryKey: queryKeys.agreement,
      queryFn: fetchAgreement,
    }),
    queryClient,
  );
}

export async function hasReadAgreement() {
  const agreement = await queryClient.query({
    queryKey: queryKeys.agreement,
    queryFn: fetchAgreement,
    staleTime: 'static',
  });
  return Boolean(agreement.has_read_developer_agreement);
}

// Accepts the agreement and refreshes the cached status.
export async function acceptAgreement(payload: AgreementAcceptState) {
  await postAgreement(payload);
  await queryClient.invalidateQueries({ queryKey: queryKeys.agreement });
}

// The same upload validates differently as a new add-on and as a new version,
// so each gets its own entry under the upload's key.
const uploadKey = (uuid: string, versionOf = '') =>
  [...queryKeys.upload(uuid), versionOf] as const;

// Creates a new FileUpload.
export async function createUpload(
  file: File,
  channel: AddonDistribution,
  versionOf?: string,
): Promise<FileUpload> {
  const upload = await postUpload(file, channel);
  // Only the detail endpoint runs the full check, so a processed response
  // (validation ran eagerly) must not stand in for it.
  if (!upload.processed) {
    queryClient.setQueryData(uploadKey(upload.uuid, versionOf), upload);
  }
  return upload;
}

export function getUpload(
  uuid: string,
  versionOf?: string,
): Promise<FileUpload> {
  return queryClient.fetchQuery({
    queryKey: uploadKey(uuid, versionOf),
    queryFn: () => fetchUpload(uuid, versionOf),
    retry: false,
  });
}

export function uploadQuery(
  host: ReactiveControllerHost,
  getUuid: () => string,
  getVersionOf: () => string = () => '',
) {
  return createQueryController(
    host,
    () => ({
      queryKey: uploadKey(getUuid(), getVersionOf()),
      queryFn: () => fetchUpload(getUuid(), getVersionOf() || undefined),
      enabled: Boolean(getUuid()),
      refetchInterval: (query) => (query.state.data?.processed ? false : 1000),
    }),
    queryClient,
  );
}

// Create a version from a FileUpload.
export async function createVersion(
  slug: string,
  uuid: string,
  license?: VersionLicenseEdit,
): Promise<Version> {
  const version = await (license
    ? postVersion(slug, uuid, license)
    : postVersion(slug, uuid));
  queryClient.setQueryData(queryKeys.version(slug, version.id), version);
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.upload(uuid) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.versions(slug) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.latestVersion(slug) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.addons }),
  ]);
  return version;
}

export function versionsQuery(
  host: ReactiveControllerHost,
  getSlug: () => string,
  getPage: () => number,
) {
  return createQueryController(
    host,
    () => {
      const slug = getSlug();
      const page = getPage();
      return {
        queryKey: [...queryKeys.versions(slug), page],
        queryFn: () => fetchVersions(slug, LOCALE ?? 'en-US', page),
        enabled: Boolean(slug),
      };
    },
    queryClient,
  );
}

export async function addonFromUpload(create: AddonCreate) {
  const created = await postAddon(create);
  const { addon, version } = created;
  queryClient.setQueryData(queryKeys.version(addon.slug, version.id), version);
  await Promise.all([
    queryClient.invalidateQueries({
      queryKey: queryKeys.upload(create.version.upload),
    }),
    queryClient.invalidateQueries({ queryKey: queryKeys.addons }),
  ]);
  // After the invalidate, or this is immediately marked stale and refetched.
  queryClient.setQueryData(queryKeys.addon(addon.slug), addon);
  return created;
}

async function _updateVersion(
  slug: string,
  id: number,
  body: FormData | object,
): Promise<Version> {
  const version = await patchVersion(slug, id, body);
  queryClient.setQueryData(queryKeys.version(slug, id), version);
  await queryClient.invalidateQueries({ queryKey: queryKeys.versions(slug) });
  return version;
}

export async function updateVersion(
  slug: string,
  id: number,
  { release_notes, approval_notes, ...edit }: VersionEdit,
  source?: File | null,
) {
  const body = {
    ...edit,
    ...(approval_notes !== undefined && { approval_notes }),
    ...(release_notes !== undefined && {
      release_notes: { [LOCALE ?? 'en-US']: release_notes },
    }),
    ...(source === null && { source: null }),
  };
  let version: Version | undefined;
  if (Object.keys(body).length) version = await patchVersion(slug, id, body);
  if (source) {
    const form = new FormData();
    form.append('source', source);
    version = await patchVersion(slug, id, form);
  }
  if (version) queryClient.setQueryData(queryKeys.version(slug, id), version);
  await Promise.all([
    queryClient.invalidateQueries({
      queryKey: [...queryKeys.version(slug, id), 'source'],
    }),
    queryClient.invalidateQueries({ queryKey: queryKeys.versions(slug) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.addons }),
  ]);
}

export async function disableVersion(slug: string, id: number) {
  await _updateVersion(slug, id, { is_disabled: true });
  await queryClient.invalidateQueries({ queryKey: queryKeys.addons });
}

export async function removeVersion(slug: string, id: number) {
  await deleteVersion(slug, id);
  queryClient.removeQueries({ queryKey: queryKeys.version(slug, id) });
  void queryClient.invalidateQueries({ queryKey: queryKeys.addons });
  queryClient.invalidateQueries({ queryKey: queryKeys.versions(slug) });
}

export async function uploadVersionSource(
  slug: string,
  id: number,
  file: File,
) {
  const body = new FormData();
  body.append('source', file);
  await _updateVersion(slug, id, body);
}

export async function updateVersionLicense(
  slug: string,
  id: number,
  license: string | undefined,
  custom?: { name: string; text: string },
) {
  const version = await patchVersionLicense(slug, id, license, custom);
  queryClient.setQueryData(queryKeys.version(slug, id), version);
  const isCurrent = ADDON_KINDS.some((kind) =>
    queryClient
      .getQueryData<AddonPage>(queryKeys.addonList(kind))
      ?.results.some((a) => a.slug === slug && a.currentVersion?.id === id),
  );
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.versions(slug) }),
    isCurrent && queryClient.invalidateQueries({ queryKey: queryKeys.addons }),
  ]);
}

export async function uploadVersionNotes(
  slug: string,
  id: number,
  releaseNotes?: string,
  reviewerNotes?: string,
  langCode: string = LOCALE ?? 'en-US',
) {
  await _updateVersion(slug, id, {
    ...(reviewerNotes && { approval_notes: reviewerNotes }),
    ...(releaseNotes && { release_notes: { [langCode]: releaseNotes } }),
  });
}

// The versions an application can be marked compatible with.
export function appVersionsQuery(
  host: ReactiveControllerHost,
  getApp: () => string | undefined,
) {
  return createQueryController(
    host,
    () => ({
      queryKey: queryKeys.appVersions(getApp()),
      queryFn: () => fetchAppVersions(getApp() ?? ''),
      enabled: Boolean(getApp()),
      // Supported app versions rarely change.
      staleTime: Number.POSITIVE_INFINITY,
    }),
    queryClient,
  );
}

// Ends the current session server-side. Callers reload afterwards so the app
// rebuilds as signed-out; the reload discards the cache, so no invalidation here.
export async function logout() {
  await deleteSession();
}
