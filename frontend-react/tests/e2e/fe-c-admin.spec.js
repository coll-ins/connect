import { test, expect } from '@playwright/test';

const admin = {
  id: 1,
  username: 'platform_admin_e2e',
  name: 'Platform Admin',
  role: 'platform_admin',
  is_staff: true,
  is_superuser: true,
};

const json = (route, body, status = 200) => route.fulfill({
  status,
  contentType: 'application/json',
  body: JSON.stringify(body),
});

// `overrides` maps an API path to a handler or a body; everything else is [].
async function openAdmin(page, path, overrides = {}) {
  await page.route('**/api/**', async (route) => {
    const { pathname } = new URL(route.request().url());
    if (pathname === '/api/users/csrf/') return json(route, { csrfToken: 'e2e' });
    if (pathname === '/api/users/profile/') return json(route, { user: admin });
    const handler = overrides[pathname];
    if (typeof handler === 'function') return handler(route);
    return json(route, handler ?? []);
  });
  await page.addInitScript((user) => {
    localStorage.setItem('user_session', JSON.stringify(user));
  }, admin);
  await page.goto(path);
}

const MODALS = [
  { path: '/platform-admin/companies', open: /Add Company/i, title: /Add company/i, fields: 4 },
  { path: '/platform-admin/routes', open: /Add Route/i, title: /Add route/i, fields: 5 },
  { path: '/platform-admin/drivers', open: /Add Driver/i, title: /Add driver/i, fields: 4 },
  { path: '/platform-admin/trips', open: /Create Trip/i, title: /Create trip/i, fields: 5 },
  { path: '/platform-admin/operators', open: /Add Company Staff/i, title: /Add company staff/i, fields: 7 },
];

test.describe('platform admin modals', () => {
  for (const modal of MODALS) {
    test(`${modal.title} is a labelled dialog and every field has an accessible name`, async ({ page }) => {
      await openAdmin(page, modal.path);
      await page.getByRole('button', { name: modal.open }).first().click();

      const dialog = page.getByRole('dialog', { name: modal.title });
      await expect(dialog).toBeVisible();

      const fields = dialog.locator('input:not([type="hidden"]), select, textarea');
      await expect(fields).toHaveCount(modal.fields);
      for (let i = 0; i < modal.fields; i += 1) {
        await expect(fields.nth(i)).toHaveAccessibleName(/\S/);
      }

      await page.keyboard.press('Escape');
      await expect(dialog).toHaveCount(0);
      await expect(page.getByRole('button', { name: modal.open }).first()).toBeFocused();
    });
  }

  test('the longest form fits a 375px screen without sideways scrolling', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 740 });
    await openAdmin(page, '/platform-admin/operators');
    await page.getByRole('button', { name: /Add Company Staff/i }).first().click();
    await expect(page.getByRole('dialog', { name: /Add company staff/i })).toBeVisible();
    const width = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(width).toBeLessThanOrEqual(375);
  });
});

test.describe('platform admin load states', () => {
  test('companies show Loading, not "No companies found", while the request is pending', async ({ page }) => {
    await openAdmin(page, '/platform-admin/companies', {
      '/api/companies/': () => new Promise(() => {}),
    });
    await expect(page.getByRole('button', { name: /Add Company/i })).toBeVisible();
    await expect(page.getByRole('status').filter({ hasText: /Loading/ })).toBeVisible();
    await expect(page.getByText('No companies found')).toHaveCount(0);
  });

  test('a failed companies load shows an alert with Retry, not an empty list', async ({ page }) => {
    await openAdmin(page, '/platform-admin/companies', {
      '/api/companies/': (route) => json(route, { detail: 'boom' }, 500),
    });
    await expect(page.getByRole('alert').filter({ hasText: /Could not load companies/ })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Retry' }).first()).toBeVisible();
    await expect(page.getByText('No companies found')).toHaveCount(0);
  });

  test('a real empty list still says so', async ({ page }) => {
    await openAdmin(page, '/platform-admin/companies');
    await expect(page.getByText('No companies found')).toBeVisible();
  });

  test('failed bookings show -- for revenue and an unknown system status', async ({ page }) => {
    await openAdmin(page, '/platform-admin/revenue', {
      '/api/bookings/all/': (route) => json(route, { detail: 'boom' }, 500),
    });
    await expect(page.getByText('--').first()).toBeVisible();
    await expect(page.getByText('KES 0.00')).toHaveCount(0);
    await expect(page.getByText('System healthy')).toHaveCount(0);
  });
});
