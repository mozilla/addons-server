import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

// Standalone from vite.config.ts: the dev server's base/proxy/HMR settings are
// irrelevant to tests. Vitest still uses Vite's transform pipeline, so legacy
// decorators and `?inline` CSS imports work the same as in `npm run dev`.
export default defineConfig({
  test: {
    // Lit components render to real shadow roots here; we assert on their DOM
    // rather than acorn's internals. See README "Testing".
    environment: 'happy-dom',
    globals: true,
    setupFiles: ['tests/setup.ts'],
    // The real virtualizer measures layout APIs happy-dom lacks (it renders
    // nothing and throws). Swap it for a stub that renders every row eagerly so
    // component DOM assertions stay meaningful. Production uses the real one via
    // vite.config.ts.
    alias: {
      '@lit-labs/virtualizer': fileURLToPath(
        new URL('./tests/doubles/lit-virtualizer.ts', import.meta.url),
      ),
    },
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
