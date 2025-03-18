import { defineConfig } from 'vitest/config';
import { resolve } from 'path';

export default defineConfig({
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./tests/js/setup.js'],
    include: ['tests/**/*.spec.js'],
  },
  resolve: {
    alias: {
      // Alias 'highcharts' to our local vendored copy
      // we cannot use npm to install due to licensing constraints
      highcharts: resolve(__dirname, 'static/js/lib/highcharts-module.js'),
    },
  },
});
