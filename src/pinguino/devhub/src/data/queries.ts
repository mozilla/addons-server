// Query definitions: stable keys, and per-query lifetimes
// in one place. Components attach these controllers and read reactive
// { data, isPending, isError } — they never call fetch or manage loading state.

import { createQueryController } from '@tanstack/lit-query';
import type { ReactiveControllerHost } from 'lit';
import {
  addAuthor,
  addPreview,
  deleteAuthor,
  deletePreview,
  fetchActivity,
  fetchAddons,
  fetchAgreement,
  fetchAuthors,
  fetchCategories,
  fetchEulaPolicy,
  fetchPendingAuthors,
  fetchProfile,
  fetchUpdates,
  patchAddon,
  patchAuthor,
  patchEulaPolicy,
  patchPreview,
  postAgreement,
  uploadIcon,
} from './api';
import { queryClient } from './query-client';
import type {
  Addon,
  AddonAuthorAdd,
  AddonAuthorRole,
  AddonListingEdit,
  AgreementAcceptState,
  EulaPolicyEdit,
} from './types';

// Keys identify cache entries. The add-on list and a single add-on share one
// key so navigating to a detail view reuses the cached list, not a new request.
export const queryKeys = {
  profile: ['profile'] as const,
  addons: ['addons'] as const,
  updates: ['updates'] as const,
  agreement: ['agreement'] as const,
  categories: ['categories'] as const,
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

const activityKey = (slug: string, page: number) =>
  ['activity', slug, page] as const;

// Keyed by page, so paging back and forth is served from cache.
export function activityQuery(
  host: ReactiveControllerHost,
  getSlug: () => string,
  getPage: () => number,
) {
  return createQueryController(
    host,
    () => ({
      queryKey: activityKey(getSlug(), getPage()),
      queryFn: () => fetchActivity(getSlug(), getPage()),
      enabled: Boolean(getSlug()),
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
