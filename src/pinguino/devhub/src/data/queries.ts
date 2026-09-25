// Query definitions: stable keys, per-query lifetimes, and the mock-vs-API
// branch in one place. Components attach these controllers and read reactive
// { data, isPending, isError } — they never call fetch or manage loading state.

import type { QueryObserverResult } from '@tanstack/lit-query';
import { createQueryController } from '@tanstack/lit-query';
import type { ReactiveControllerHost } from 'lit';
import { fetchAddons, fetchProfile, fetchUpdates } from './api';
import { apiConfigured, author } from './http';
import { developer, mockAddons, mockUpdates } from './mock';
import { queryClient } from './query-client';
import type { Addon } from './types';

// Keys identify cache entries. The add-on list and a single add-on share one
// key so navigating to a detail view reuses the cached list, not a new request.
export const queryKeys = {
  profile: ['profile'] as const,
  addons: ['addons', author] as const,
  updates: (versionIds: number[]) => ['updates', ...versionIds] as const,
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

// Updates depend on the add-on list, so this reads the add-ons result and only
// runs once it has settled. The options getter re-runs on host updates, so it
// enables itself when the add-ons query resolves.
export function updatesQuery(
  host: ReactiveControllerHost,
  getAddons: () => QueryObserverResult<Addon[]>,
) {
  return createQueryController(
    host,
    () => {
      const { data = [], isSuccess } = getAddons();
      const versionIds = data
        .map((a) => a.versionId)
        .filter((v): v is number => v != null);
      return {
        queryKey: queryKeys.updates(versionIds),
        queryFn: () =>
          apiConfigured ? fetchUpdates(data) : Promise.resolve(mockUpdates),
        enabled: isSuccess,
      };
    },
    queryClient,
  );
}
