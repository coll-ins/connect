import { test, expect } from '@playwright/test';

const roleDashboards = [
  { role: 'passenger', path: '/passenger' },
  { role: 'driver', path: '/driver' },
  { role: 'company_manager', path: '/company-manager' },
  { role: 'company_auditor', path: '/company-auditor' },
  { role: 'company_operator', path: '/company-operator' },
  { role: 'platform_admin', path: '/platform-admin' },
];

const baseUser = (role) => ({
  id: 17,
  username: 'connect_e2e_user',
  name: 'CONNECT Test User',
  phone_number: '0712345678',
  role,
  company_id: 17,
  company_name: 'Test Company',
  is_staff: role === 'platform_admin',
  is_superuser: role === 'platform_admin',
});

async function stubApi(page, { loginRole = null, profileRole = null } = {}) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());

    if (url.pathname === '/api/users/login/' && loginRole) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ user: baseUser(loginRole) }),
      });
      return;
    }

    if (url.pathname === '/api/users/profile/' && profileRole) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ user: baseUser(profileRole) }),
      });
      return;
    }

    // Empty fixtures keep these tests isolated from real application data.
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    });
  });
}

async function addCsrfCookie(page) {
  await page.context().addCookies([{
    name: 'csrftoken',
    value: 'connect-e2e-csrf',
    url: 'http://127.0.0.1:4173',
  }]);
}

test.describe('CONNECT role-specific navigation', () => {
  for (const { role, path } of roleDashboards) {
    test(`${role} login redirects to ${path}`, async ({ page }) => {
      await stubApi(page, { loginRole: role });
      await addCsrfCookie(page);
      await page.goto('/login');

      await page.getByLabel('Phone number').fill('0712345678');
      await page.getByLabel('Password').fill('test-password-only');
      await page.getByRole('button', { name: 'Sign in' }).click();

      await expect(page).toHaveURL(new RegExp(`${path.replaceAll('/', '\\/')}$`));
    });
  }

  const forbiddenDestinations = [
    { role: 'passenger', path: '/company-manager', expected: '/passenger' },
    { role: 'driver', path: '/platform-admin', expected: '/driver' },
    { role: 'company_manager', path: '/company-auditor', expected: '/company-manager' },
  ];

  for (const { role, path, expected } of forbiddenDestinations) {
    test(`${role} cannot stay on ${path}`, async ({ page }) => {
      await stubApi(page, { profileRole: role });

      await page.addInitScript((user) => {
        localStorage.setItem('user_session', JSON.stringify(user));
      }, baseUser(role));

      await page.goto(path);
      await expect(page).toHaveURL(new RegExp(`${expected.replaceAll('/', '\\/')}$`));
    });
  }

  test('an unrecognized server role clears the stale session and returns to login', async ({ page }) => {
    await stubApi(page, { profileRole: 'unrecognized_role' });

    await page.addInitScript((user) => {
      localStorage.setItem('user_session', JSON.stringify(user));
    }, baseUser('passenger'));

    await page.goto('/company-manager');

    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
    await expect.poll(() => page.evaluate(() => localStorage.getItem('user_session'))).toBeNull();
  });
});

test('unknown passenger subroute returns to passenger home', async ({ page }) => {
  await stubApi(page, { profileRole: 'passenger' });

  await page.addInitScript((user) => {
    localStorage.setItem('user_session', JSON.stringify(user));
  }, baseUser('passenger'));

  await page.goto('/passenger/not-a-real-page');

  await expect(page).toHaveURL(/\/passenger$/);
  await expect(
    page.getByRole('heading', { name: /Where are you going today\?/i }),
  ).toBeVisible();
});

test('unknown driver subroute returns to driver overview', async ({ page }) => {
  await stubApi(page, { profileRole: 'driver' });

  await page.addInitScript((user) => {
    localStorage.setItem('user_session', JSON.stringify(user));
  }, baseUser('driver'));

  await page.goto('/driver/not-a-real-page');

  await expect(page).toHaveURL(/\/driver$/);
  await expect(
    page.getByRole('heading', { level: 1, name: 'Overview' }),
  ).toBeVisible();
});
