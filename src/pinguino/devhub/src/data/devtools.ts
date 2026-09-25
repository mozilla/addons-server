// Dev-only TanStack Query devtools. Loaded via a dynamic import behind
// import.meta.env.DEV in main.ts, so it's excluded from production bundles.

import { onlineManager } from '@tanstack/lit-query';
import { TanstackQueryDevtools } from '@tanstack/query-devtools';
import { queryClient } from './query-client';

export function mountDevtools() {
  // Mount in the light DOM so the devtools' own styles aren't trapped in a
  // component shadow root.
  const host = document.createElement('div');
  document.body.appendChild(host);
  new TanstackQueryDevtools({
    client: queryClient,
    queryFlavor: 'Lit Query',
    version: '5',
    onlineManager,
  }).mount(host);
}
