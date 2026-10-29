// Query definitions: stable keys, and per-query lifetimes
// in one place. Components attach these controllers and read reactive
// { data, isPending, isError } — they never call fetch or manage loading state.

import { createQueryController } from '@tanstack/lit-query';
import type { ReactiveControllerHost } from 'lit';
import { LOCALE } from '../base';
import {
  addAuthor,
  addPreview,
  deleteAddon,
  deleteAuthor,
  deletePreview,
  fetchAddons,
  fetchAgreement,
  fetchAuthors,
  fetchCategories,
  fetchEulaPolicy,
  fetchPendingAuthors,
  fetchProfile,
  fetchUpdates,
  fetchUpload,
  fetchVersion,
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
  addons: ['addons'] as const,
  updates: ['updates'] as const,
  agreement: ['agreement'] as const,
  categories: ['categories'] as const,
  upload: (uuid: string) => ['upload', uuid] as const,
  version: (slug: string, id: number) => ['version', slug, id] as const,
};

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
      staleTime: Number.POSITIVE_INFINITY,
    }),
    queryClient,
  );
}

export function addonsQuery(host: ReactiveControllerHost) {
  return createQueryController(
    host,
    () => ({
      queryKey: queryKeys.addons,
      queryFn: fetchAddons,
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

// Permanently delete an add-on, then drop it from the cached list the manage
// view reads — that view is about to unmount, so it must not refetch it.
export async function removeAddon(slug: string) {
  await deleteAddon(slug);
  await queryClient.invalidateQueries({ queryKey: queryKeys.addons });
}

const eulaPolicyKey = (slug: string) => ['eula-policy', slug] as const;

// The EULA/privacy text (separate endpoint), for the view-mode preview. Gated
// by `getEnabled` so it only fetches when the add-on actually has a policy.
export function eulaPolicyQuery(
  host: ReactiveControllerHost,
  getSlug: () => string,
  getEnabled: () => boolean = () => true,
) {
  return createQueryController(
    host,
    () => ({
      queryKey: eulaPolicyKey(getSlug()),
      queryFn: () => fetchEulaPolicy(getSlug()),
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

// The activity feed is a single endpoint scoped to the session, independent of
// the add-on list.
export function updatesQuery(host: ReactiveControllerHost) {
  return createQueryController(
    host,
    () => ({
      queryKey: queryKeys.updates,
      queryFn: fetchUpdates,
    }),
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
  return version;
}

async function _updateVersion(
  slug: string,
  id: number,
  body: FormData | object,
): Promise<Version> {
  const version = await patchVersion(slug, id, body);
  queryClient.setQueryData(queryKeys.version(slug, id), version);
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
