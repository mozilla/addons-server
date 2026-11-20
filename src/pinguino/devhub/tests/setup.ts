import { afterEach, vi } from 'vitest';
import { queryClient } from '../src/data/query-client';

// happy-dom has no ElementInternals, and acorn's form-associated components
// (moz-button among them) call attachInternals in their constructor — so any
// test that registers a real acorn component dies on construction without
// this. They only read `form` off it, which is null outside a <form>.
if (!HTMLElement.prototype.attachInternals) {
  HTMLElement.prototype.attachInternals = function attachInternals() {
    return { form: null } as unknown as ElementInternals;
  };
}

// Keep tests isolated: clear mounted elements, the shared query cache, and any
// stubbed globals/env so one test's state can't leak into the next.
afterEach(() => {
  document.body.replaceChildren();
  queryClient.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
