import { defineConfig } from 'vitest/config';

// Standalone from vite.config.ts: the dev server's base/proxy/HMR settings are
// irrelevant to tests, and there are no Vite plugins to inherit. Vitest still
// uses Vite's transform pipeline, so legacy decorators and `?inline` CSS imports
// work the same as in `npm run dev`.
export default defineConfig({
  test: {
    // Lit components render to real shadow roots here; we assert on their DOM
    // rather than acorn's internals. See README "Testing".
    environment: 'happy-dom',
    globals: true,
    // Pin the API as unconfigured so tests are deterministic and never hit the
    // network, regardless of a developer's local .env. Tests that need the
    // configured path stub this env var and re-import.
    env: { VITE_AMO_SESSION_ID: '' },
    setupFiles: ['tests/setup.ts'],
    include: ['tests/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      include: ['src/**/*.ts'],
      // Entry/dev-only glue, type-only files, and the CSS-only layout primitives
      // have no data-shape behaviour to assert.
      exclude: [
        'src/main.ts',
        'src/data/devtools.ts',
        'src/foundations/layout/**',
        'src/**/*.d.ts',
      ],
      reporter: ['text', 'html'],
    },
  },
});
