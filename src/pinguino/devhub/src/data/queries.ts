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
  fetchActivity,
  fetchAddonSource,
  fetchAddons,
  fetchAgreement,
  fetchAuthors,
  fetchCategories,
  fetchEulaPolicy,
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
  postAgreement,
  postUpload,
  postVersion,
  uploadIcon,
} from './api';
import { isAddonOwner } from './permissions';
import { queryClient } from './query-client';
import type { AddonVisibility } from './statuses';
import type {
  ActivityPage,
  Addon,
  AddonAuthorAdd,
  AddonAuthorRole,
  AddonDistribution,
  AddonListingEdit,
  AgreementAcceptState,
  EulaPolicyEdit,
  FileUpload,
  Version,
} from './types';

// Keys identify cache entries. The add-on list and a single add-on share one
// key so navigating to a detail view reuses the cached list, not a new request.
export const queryKeys = {
  profile: ['profile'] as const,
  siteStatus: ['site-status'] as const,
  addons: ['addons'] as const,
  agreement: ['agreement'] as const,
  categories: ['categories'] as const,
  upload: (uuid: string) => ['upload', uuid] as const,
  version: (slug: string, id: number) => ['version', slug, id] as const,
  versions: (slug: string) => ['versions', slug] as const,
};

// Keyed by add-on and page; a missing slug (the all-add-ons feed) normalises to
// null so it stays a stable, distinct cache entry.
const activityKey = (slug: string | undefined, page: number) =>
  ['activity', slug ?? null, page] as const;

// The infinite (scroll-to-load) variant of the feed. Shares the 'activity'
// prefix so one invalidate refreshes both the paged and infinite caches.
const activityInfiniteKey = (slug: string | undefined) =>
  ['activity', 'infinite', slug ?? null] as const;

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

// These are the signed-in developer's own add-ons, so asking while signed out
// only earns a 401; `getEnabled` lets a caller wait for the profile first.
export function addonsQuery(
  host: ReactiveControllerHost,
  getEnabled: () => boolean = () => true,
) {
  return createQueryController(
    host,
    () => ({
      queryKey: queryKeys.addons,
      queryFn: fetchAddons,
      enabled: getEnabled(),
    }),
    queryClient,
  );
}

// One add-on, selected from the cached list by slug — no extra request when
// arriving from the dashboard. Swap in a detail endpoint here when one exists.
export function addonQuery(
  host: ReactiveControllerHost,
  getSlug: () => string,
) {
  return createQueryController(
    host,
    () => ({
      queryKey: queryKeys.addons,
      queryFn: fetchAddons,
      select: (addons: Addon[]) => addons.find((a) => a.slug === getSlug()),
    }),
    queryClient,
  );
}

// Persist Listing Details edits, then refresh the cached add-on list so the
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
  queryClient.setQueryData(queryKeys.addons, (addons?: Addon[]) =>
    addons?.filter((addon) => addon.slug !== slug),
  );
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
) {
  return createQueryController(
    host,
    () => ({
      queryKey: queryKeys.version(getSlug(), getId()),
      queryFn: () => fetchVersion(getSlug(), getId()),
      enabled: Boolean(getSlug() && getId()),
    }),
    queryClient,
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
) {
  return createQueryController(
    host,
    () => {
      const slug = getSlug?.();
      const page = getPage();
      return {
        queryKey: activityKey(slug, page),
        queryFn: () => fetchActivity(slug, page),
        // Wait for a slug only when one is expected; the all-add-ons feed fetches
        // immediately.
        enabled: !getSlug || Boolean(slug),
      };
    },
    queryClient,
  );
}

// The feed as an infinite query: each page is fetched on demand as the reader
// scrolls. `getNextPageParam` stops once we've loaded every row the server has.
export function activityInfiniteQuery(
  host: ReactiveControllerHost,
  getSlug?: () => string,
) {
  return createInfiniteQueryController(
    host,
    () => {
      const slug = getSlug?.();
      return {
        queryKey: activityInfiniteKey(slug),
        queryFn: ({ pageParam }) => fetchActivity(slug, pageParam),
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

// Accepts the agreement and refreshes the cached status.
export async function acceptAgreement(payload: AgreementAcceptState) {
  await postAgreement(payload);
  await queryClient.invalidateQueries({ queryKey: queryKeys.agreement });
}

// Creates a new FileUpload.
export async function createUpload(
  file: File,
  channel: AddonDistribution,
): Promise<FileUpload> {
  const upload = await postUpload(file, channel);
  queryClient.setQueryData(queryKeys.upload(upload.uuid), upload);
  return upload;
}

export function uploadQuery(
  host: ReactiveControllerHost,
  getUuid: () => string,
) {
  return createQueryController(
    host,
    () => ({
      queryKey: queryKeys.upload(getUuid()),
      queryFn: () => fetchUpload(getUuid()),
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
): Promise<Version> {
  const version = await postVersion(slug, uuid);
  queryClient.setQueryData(queryKeys.version(slug, version.id), version);
  await queryClient.invalidateQueries({ queryKey: queryKeys.upload(uuid) });
  await queryClient.invalidateQueries({ queryKey: queryKeys.versions(slug) });
  return version;
}

export function versionsQuery(
  host: ReactiveControllerHost,
  getSlug: () => string,
) {
  return createQueryController(
    host,
    () => ({
      queryKey: queryKeys.versions(getSlug()),
      queryFn: () => fetchVersions(getSlug(), LOCALE ?? 'en-US'),
      enabled: Boolean(getSlug()),
    }),
    queryClient,
  );
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

export async function disableVersion(slug: string, id: number) {
  await _updateVersion(slug, id, { is_disabled: true });
  await queryClient.invalidateQueries({ queryKey: queryKeys.addons });
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

export async function uploadVersionNotes(
  slug: string,
  id: number,
  releaseNotes?: string,
  reviewerNotes?: string,
  langCode: string = LOCALE ?? 'en-US',
) {
  await _updateVersion(slug, id, {
    approval_notes: reviewerNotes ?? '',
    ...(releaseNotes && { release_notes: { [langCode]: releaseNotes } }),
  });
}

// Ends the current session server-side. Callers reload afterwards so the app
// rebuilds as signed-out; the reload discards the cache, so no invalidation here.
export async function logout() {
  await deleteSession();
}
