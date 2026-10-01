// Query definitions: stable keys, per-query lifetimes, and the mock-vs-API
// branch in one place. Components attach these controllers and read reactive
// { data, isPending, isError } — they never call fetch or manage loading state.

import { createQueryController } from '@tanstack/lit-query';
import type { ReactiveControllerHost } from 'lit';
import {
  fetchAddons,
  fetchAgreement,
  fetchProfile,
  fetchUpdates,
  postAgreement,
} from './api';
import { apiConfigured } from './http';
import {
  developer,
  mockAddons,
  mockReadAgreement,
  mockUnreadAgreement,
  mockUpdates,
} from './mock';
import { queryClient } from './query-client';
import type { Addon, AgreementAcceptState } from './types';

// Keys identify cache entries. The add-on list and a single add-on share one
// key so navigating to a detail view reuses the cached list, not a new request.
export const queryKeys = {
  profile: ['profile'] as const,
  addons: ['addons'] as const,
  updates: ['updates'] as const,
  agreement: ['agreement'] as const,
};

// The signed-in developer. Session-lived, so it survives navigation without a
// refetch; invalidate queryKeys.profile explicitly after a profile edit.
export function profileQuery(host: ReactiveControllerHost) {
  return createQueryController(
    host,
    () => ({
      queryKey: queryKeys.profile,
      queryFn: () =>
        apiConfigured ? fetchProfile() : Promise.resolve(developer),
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
      queryFn: () =>
        apiConfigured ? fetchAddons() : Promise.resolve(mockAddons),
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
      queryFn: () =>
        apiConfigured ? fetchAddons() : Promise.resolve(mockAddons),
      select: (addons: Addon[]) => addons.find((a) => a.slug === getSlug()),
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
      queryFn: () =>
        apiConfigured ? fetchUpdates() : Promise.resolve(mockUpdates),
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
      queryFn: () =>
        apiConfigured ? fetchAgreement() : Promise.resolve(mockUnreadAgreement),
    }),
    queryClient,
  );
}

// Accepts the agreement and refreshes the cached status.
export async function acceptAgreement(payload: AgreementAcceptState) {
  if (apiConfigured) {
    await postAgreement(payload);
    await queryClient.invalidateQueries({ queryKey: queryKeys.agreement });
  } else {
    queryClient.setQueryData(queryKeys.agreement, () => mockReadAgreement);
  }
}
