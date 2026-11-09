import { test, expect } from '@playwright/test';

async function stubCsrf(page) {
  await page.route('**/api/users/csrf/', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ csrfToken: 'playwright-test-csrf' }),
  }));
}

test.describe('CONNECT public entry and access guards', () => {
  test('login page exposes labelled credentials and signup link', async ({ page }) => {
    await page.goto('/login');

    await expect(page.locator('.splash')).toHaveCount(0);
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

  test('unknown URL redirects to the landing page', async ({ page }) => {
    await page.goto('/this-route-does-not-exist');

    await expect(page).toHaveURL('/');
    await expect(
      page.getByRole('heading', { name: /Your matatu seat, booked/ }),
    ).toBeVisible();
    await expect(page.getByRole('link', { name: 'Sign in' })).toBeVisible();
  });

  test('signup link opens account creation route', async ({ page }) => {
    await page.goto('/login');
    await page.getByRole('link', { name: 'Create an account' }).click();

    await expect(page).toHaveURL(/\/signup$/);
  });

  test('successful signup stores the new session and opens its role dashboard', async ({ page }) => {
    let registrationPayload;
    await stubCsrf(page);
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
    await page.getByLabel('First name').fill('New');
    await page.getByLabel('Last name').fill('Passenger');
    await page.getByLabel('Phone number').fill('0712345678');
    await page.getByLabel('Usual location').fill('CBD');
    await page.getByRole('textbox', { name: 'Password' }).fill('StrongPassword123!');
    await expect(page.getByRole('button', { name: 'Create account' })).toBeDisabled();
    await page.getByRole('checkbox', { name: /I agree to the Terms of Service/ }).check();
    await page.getByRole('button', { name: 'Create account' }).click();

    await expect(page).toHaveURL(/\/passenger$/);
    await expect(page.getByRole('button', { name: /Book a seat/i })).toBeVisible();
    expect(registrationPayload).toMatchObject({
      name: 'New Passenger',
      phone_number: '0712345678',
      location: 'CBD',
      accept_terms: true,
    });
    await expect.poll(async () => page.evaluate(() => {
      const user = JSON.parse(localStorage.getItem('user_session') || 'null');
      return user?.role;
    })).toBe('passenger');
  });

  test('signup explains each field and refuses nonsense before sending it', async ({ page }) => {
    let registerCalls = 0;
    await stubCsrf(page);
    await page.route('**/api/users/register/', async (route) => {
      registerCalls += 1;
      await route.fulfill({ status: 500, body: '{}' });
    });

    await page.goto('/signup');
    // Before typing, each field says what it wants.
    await expect(page.getByText(/07XX XXX XXX, 01XX XXX XXX or \+254 7XX XXX XXX/)).toBeVisible();

    await page.getByLabel('First name').fill('Qwer');
    await page.getByLabel('Last name').fill('Passenger');
    await page.getByLabel('Phone number').fill('12345');
    await page.getByLabel(/Usual location/).fill('asdfgh');
    await expect(page.locator('#su-phone')).toHaveClass(/is-error/);
    await expect(page.locator('#su-loc')).toContainText('"asdfgh" in your usual location does not look like a real word');
    await expect(page.locator('#su-name')).toContainText('"Qwer" in your name does not look like a real word');

    await page.getByRole('textbox', { name: 'Password' }).fill('StrongPassword123!');
    await page.getByRole('checkbox', { name: /I agree to the Terms of Service/ }).check();
    await page.getByRole('button', { name: 'Create account' }).click();
    await expect(page.getByRole('alert')).toContainText('does not look like a real word');
    expect(registerCalls).toBe(0);
  });

  test('failed signup remains unauthenticated and reports the error', async ({ page }) => {
    await stubCsrf(page);
    await page.route('**/api/users/register/', async (route) => {
      await route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Phone number is already registered.' }),
      });
    });

    await page.goto('/signup');
    await page.getByLabel('First name').fill('Existing');
    await page.getByLabel('Last name').fill('Passenger');
    await page.getByLabel('Phone number').fill('0712345678');
    await page.getByRole('textbox', { name: 'Password' }).fill('StrongPassword123!');
    await expect(page.getByRole('button', { name: 'Create account' })).toBeDisabled();
    await page.getByRole('checkbox', { name: /I agree to the Terms of Service/ }).check();
    await page.getByRole('button', { name: 'Create account' }).click();

    await expect(
      page.getByRole('alert').getByText('Phone number is already registered.'),
    ).toBeVisible();
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
      page.getByRole('alert').getByText('Invalid phone number or password.'),
    ).toBeVisible();
    await expect(
      page.getByRole('button', { name: 'Sign in' }),
    ).toBeEnabled();
    await expect(page).toHaveURL(/\/login$/);
  });

  test('unavailable login action is explained in plain language', async ({ page, context }) => {
    await page.goto('/login');

    await context.addCookies([{
      name: 'csrftoken',
      value: 'playwright-test-csrf',
      url: 'http://127.0.0.1:4173',
    }]);

    await page.route('**/api/users/login/', async (route) => {
      await route.fulfill({
        status: 405,
        contentType: 'application/json',
        body: JSON.stringify({ detail: "Method 'POST' not allowed." }),
      });
    });

    await page.getByLabel('Phone number').fill('0712345678');
    await page.getByRole('textbox', { name: 'Password' }).fill('test-password-only');
    await page.getByRole('button', { name: 'Sign in' }).click();

    const errorBanner = page.getByRole('alert');
    await expect(errorBanner.getByText(
      'That action isn’t available right now. Please try again later.',
    )).toBeVisible();
    await expect(errorBanner).toBeInViewport();
    expect((await errorBanner.boundingBox()).y).toBeLessThan(100);
    await expect(page.getByText(/405|Method 'POST'/)).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Sign in' })).toBeEnabled();
  });

  test('slow sign-in explains that the free server may be waking up', async ({ page, context }) => {
    await page.goto('/login');

    await context.addCookies([{
      name: 'csrftoken',
      value: 'playwright-test-csrf',
      url: 'http://127.0.0.1:4173',
    }]);

    await page.route('**/api/users/login/', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1800));
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Invalid phone number or password.' }),
      });
    });

    await page.getByLabel('Phone number').fill('0712345678');
    await page.getByRole('textbox', { name: 'Password' }).fill('test-password-only');
    await page.getByRole('button', { name: 'Sign in' }).click();

    await expect(page.getByRole('status')).toHaveText(
      'The free server can take up to 50 seconds to wake up. Keep this page open.',
    );
    await expect(page.getByRole('alert')).toBeInViewport();
    await expect(page.getByRole('status')).toHaveCount(0);
  });
});
