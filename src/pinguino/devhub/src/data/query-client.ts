// The single TanStack Query cache for the app. Owns dedup, staleness, and
// garbage collection so components never refetch the same data on every mount.
// Per-query lifetimes are set in ./queries (e.g. the profile is session-lived).

import { QueryClient } from '@tanstack/lit-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      gcTime: 5 * 60_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

// We pass this client explicitly to each controller rather than mounting a
// QueryClientProvider, so mount it here to run cache GC for the app's lifetime.
queryClient.mount();
