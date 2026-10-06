import { afterEach, vi } from 'vitest';
import { queryClient } from '../src/data';

// Keep tests isolated: clear mounted elements, the shared query cache, and any
// stubbed globals/env so one test's state can't leak into the next.
afterEach(() => {
  document.body.replaceChildren();
  queryClient.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
