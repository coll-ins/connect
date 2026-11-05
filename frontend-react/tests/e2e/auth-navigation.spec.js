import { test, expect } from '@playwright/test';

test.describe('CONNECT public entry and access guards', () => {
  test('login page exposes labelled credentials and signup link', async ({ page }) => {
    await page.goto('/login');

    await expect(
      page.getByRole('heading', { name: 'Welcome back' }),
    ).toBeVisible();
    await expect(page.getByLabel('Phone number')).toBeVisible();
    await expect(page.getByText('Password', { exact: true })).toBeVisible();
    await expect(page.getByRole('textbox', { name: 'Password' })).toBeVisible();
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

  test('successful signup stores the new session and opens its role dashboard', async ({ page }) => {
    let registrationPayload;
    await page.route('**/api/users/register/', async (route) => {
      registrationPayload = route.request().postDataJSON();
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          message: 'Account created',
          user: {
            id: 41,
            username: 'new_passenger',
            name: 'New Passenger',
            phone_number: '+254712345678',
            role: 'passenger',
          },
        }),
      });
    });
    await page.route('**/api/users/profile/', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user: {
            id: 41,
            username: 'new_passenger',
            name: 'New Passenger',
            phone_number: '+254712345678',
            role: 'passenger',
          },
        }),
      });
    });

    await page.goto('/signup');
    await page.getByLabel('First and last name').fill('New Passenger');
    await page.getByLabel('Phone number').fill('0712345678');
    await page.getByLabel('Usual location').fill('CBD');
    await page.getByRole('textbox', { name: 'Password' }).fill('StrongPassword123!');
    await page.getByRole('button', { name: 'Create account' }).click();

    await expect(page).toHaveURL(/\/passenger$/);
    await expect(page.getByRole('button', { name: /Book a Seat/i })).toBeVisible();
    expect(registrationPayload).toMatchObject({
      name: 'New Passenger',
      phone_number: '0712345678',
      location: 'CBD',
    });
    await expect.poll(async () => page.evaluate(() => {
      const user = JSON.parse(localStorage.getItem('user_session') || 'null');
      return user?.role;
    })).toBe('passenger');
  });

  test('failed signup remains unauthenticated and reports the error', async ({ page }) => {
    await page.route('**/api/users/register/', async (route) => {
      await route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Phone number is already registered.' }),
      });
    });

    await page.goto('/signup');
    await page.getByLabel('First and last name').fill('Existing Passenger');
    await page.getByLabel('Phone number').fill('0712345678');
    await page.getByRole('textbox', { name: 'Password' }).fill('StrongPassword123!');
    await page.getByRole('button', { name: 'Create account' }).click();

    await expect(page.getByText('Phone number is already registered.')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Create account' })).toBeEnabled();
    await expect(page).toHaveURL(/\/signup$/);
    expect(await page.evaluate(() => localStorage.getItem('user_session'))).toBeNull();
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
    await page.getByRole('textbox', { name: 'Password' }).fill('intentionally-wrong-password');
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
