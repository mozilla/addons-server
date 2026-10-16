// Query definitions: stable keys, and per-query lifetimes
// in one place. Components attach these controllers and read reactive
// { data, isPending, isError } — they never call fetch or manage loading state.

import { createQueryController } from '@tanstack/lit-query';
import type { ReactiveControllerHost } from 'lit';
import {
  fetchAddons,
  fetchAgreement,
  fetchProfile,
  fetchUpdates,
  fetchUpload,
  fetchVersion,
  patchVersion,
  postAgreement,
  postUpload,
  postVersion,
} from './api';
import { queryClient } from './query-client';
import type {
  Addon,
  AddonDistribution,
  AgreementAcceptState,
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
  upload: (uuid: string) => ['upload', uuid] as const,
  version: (slug: string, id: number) => ['version', slug, id] as const,
};

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
) {
  await _updateVersion(slug, id, {
    approval_notes: reviewerNotes ?? '',
    // TODO: https://github.com/mozilla/addons/issues/16478
    ...(releaseNotes && { release_notes: { 'en-US': releaseNotes } }),
  });
}
