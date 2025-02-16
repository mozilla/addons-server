import { defineConfig, devices } from '@playwright/test';

import { base } from './tests/visual/config';

export default defineConfig({
  testDir: './tests/visual',
  timeout: 30000,
  expect: {
    timeout: 5000
  },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: base.baseURL,
    trace: 'on-first-retry',
    screenshot: 'on',
    viewport: { width: 1200, height: 800 },
  },
  projects: [700, 960, 1200].map((width) => {
    return {
      name: `firefox-${width}`,
      use: {
        ...devices['Desktop Firefox'],
        // Target the width 1 pixel less than the breakpoint
        viewport: { width: width - 1, height: 800 },
      },
    };
  }, []),
});
