import { Page } from '@playwright/test';

export async function authenticate(page: Page, email: string, redirectTo: string) {
  // Navigate to the login page
  await page.goto(`/api/v5/accounts/login/start?to=${encodeURIComponent(redirectTo)}`);
  // Fill and submit the login form
  const form = page.locator('form#fake_fxa_authorization');
  await form.getByLabel('Email').fill(email);
  await form.getByRole('button').click();
  // Wait for the redirect to complete
  await page.waitForURL(new RegExp(`${redirectTo}$`));
}

export async function logout(page: Page, redirectTo: string) {
  const encodedRedirect = encodeURIComponent(redirectTo);
  await page.goto(`/developers/logout?to=${encodedRedirect}`);
  await page.waitForURL(redirectTo);
}
