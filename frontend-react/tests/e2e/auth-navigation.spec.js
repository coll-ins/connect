import { test, expect } from '@playwright/test';

test.describe('CONNECT public entry and access guards', () => {
  test('login page exposes labelled credentials and signup link', async ({ page }) => {
    await page.goto('/login');

    await expect(
      page.getByRole('heading', { name: 'Welcome back' }),
    ).toBeVisible();
    await expect(page.getByLabel('Phone number')).toBeVisible();
    await expect(page.getByLabel('Password')).toBeVisible();
    await expect(
      page.getByRole('link', { name: 'Create an account' }),
    ).toBeVisible();
  });

  test('unauthenticated visitors cannot enter protected role routes', async ({ page }) => {
    const protectedPaths = [
      '/passenger',
      '/passenger/bookings',
      '/driver',
      '/driver/location',
      '/company-manager',
      '/company-auditor',
      '/company-operator',
      '/platform-admin',
    ];

    for (const path of protectedPaths) {
      await page.goto(path);
      await expect(page).toHaveURL(/\/login$/);
      await expect(
        page.getByRole('heading', { name: 'Welcome back' }),
      ).toBeVisible();
    }
  });

  test('unknown URL redirects to login', async ({ page }) => {
    await page.goto('/this-route-does-not-exist');

    await expect(page).toHaveURL(/\/login$/);
    await expect(
      page.getByRole('heading', { name: 'Welcome back' }),
    ).toBeVisible();
  });

  test('signup link opens account creation route', async ({ page }) => {
    await page.goto('/login');
    await page.getByRole('link', { name: 'Create an account' }).click();

    await expect(page).toHaveURL(/\/signup$/);
  });

  test('rejected credentials show an error and restore the login button', async ({ page, context }) => {
    await page.goto('/login');

    await context.addCookies([{
      name: 'csrftoken',
      value: 'playwright-test-csrf',
      url: 'http://127.0.0.1:4173',
    }]);

    await page.route('**/api/users/login/', async (route) => {
      if (route.request().method() !== 'POST') {
        await route.continue();
        return;
      }

      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({
          error: 'Invalid phone number or password.',
        }),
      });
    });

    await page.getByLabel('Phone number').fill('0712345678');
    await page.getByLabel('Password').fill('intentionally-wrong-password');
    await page.getByRole('button', { name: 'Sign in' }).click();

    await expect(
      page.getByText('Invalid phone number or password.'),
    ).toBeVisible();
    await expect(
      page.getByRole('button', { name: 'Sign in' }),
    ).toBeEnabled();
    await expect(page).toHaveURL(/\/login$/);
  });
});
