import { test, expect } from '@playwright/test';
import { pages, base } from '../config';
import { authenticate } from '../helpers/auth';

test.describe('Snapshot', () => {
  for (const pageConfig of pages) {
    test(`${pageConfig.path}`, async ({ page }) => {
      if (pageConfig.requiresAuth) {
        await authenticate(page, base.authEmail, pageConfig.path);
      } else {
        await page.goto(pageConfig.path);
      }
      await expect(page).toHaveScreenshot({
        animations: 'disabled',
        maxDiffPixelRatio: pageConfig.threshold,
        fullPage: true,
      });
    });
  }
});
