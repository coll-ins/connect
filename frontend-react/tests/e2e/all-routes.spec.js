import { expect, test } from '@playwright/test';

// Every route each role can open, with an API that has no data yet: each
// page must render its own screen (no crash, no blank page, no bounce).
const ROUTES = {
  passenger: [
    '/passenger', '/passenger/schedules', '/passenger/map', '/passenger/bookings',
    '/passenger/wallet', '/passenger/payments', '/passenger/receipts', '/passenger/history',
    '/passenger/seats', '/passenger/help', '/passenger/profile', '/passenger/payment/9',
    '/passenger/delivery', '/passenger/delivery/new', '/passenger/delivery/9',
    '/passenger/charter', '/passenger/charter/new', '/passenger/charter/9',
  ],
  driver: [
    '/driver', '/driver/trips', '/driver/passengers', '/driver/location',
    '/driver/boarding', '/driver/jobs', '/driver/profile',
  ],
  company_manager: [
    '/company-manager', '/company-manager/companies', '/company-manager/routes',
    '/company-manager/trips', '/company-manager/services', '/company-manager/reports',
    '/company-manager/drivers', '/company-manager/operators', '/company-manager/bookings',
    '/company-manager/capacity', '/company-manager/pricing', '/company-manager/revenue',
    '/company-manager/settings', '/company-manager/parcels', '/company-manager/route-planner',
    '/company-manager/charters',
  ],
  company_auditor: [
    '/company-auditor', '/company-auditor/audit', '/company-auditor/bookings',
    '/company-auditor/incidents', '/company-auditor/passengers', '/company-auditor/payments',
    '/company-auditor/receipts', '/company-auditor/reports', '/company-auditor/revenue',
    '/company-auditor/search', '/company-auditor/transactions', '/company-auditor/trips',
    '/company-auditor/profile',
  ],
  company_operator: [
    '/company-operator', '/company-operator/overview', '/company-operator/operations',
    '/company-operator/departures', '/company-operator/trips', '/company-operator/boarding',
    '/company-operator/bookings', '/company-operator/drivers', '/company-operator/capacity',
  ],
  platform_admin: [
    '/platform-admin', '/platform-admin/users', '/platform-admin/companies',
    '/platform-admin/routes', '/platform-admin/drivers', '/platform-admin/operators',
    '/platform-admin/trips', '/platform-admin/bookings', '/platform-admin/revenue',
    '/platform-admin/reports', '/platform-admin/issues', '/platform-admin/settings',
    '/platform-admin/system-tests',
  ],
  public: ['/', '/login', '/signup', '/legal/terms', '/legal/privacy', '/legal/refunds'],
};

const userFor = (role) => ({
  id: 7,
  username: `e2e_${role}`,
  name: 'Amina Hassan',
  phone_number: '+254712000111',
  role,
  company_id: 17,
  company_name: 'Express Line',
  is_superuser: role === 'platform_admin',
});

for (const [role, paths] of Object.entries(ROUTES)) {
  test(`${role}: every route renders its own screen`, async ({ page }) => {
    test.setTimeout(paths.length * 8000);
    const user = role === 'public' ? null : userFor(role);
    const crashes = [];
    page.on('pageerror', (e) => crashes.push(e.message));

    await page.route('**/api/**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      const json = (status, body) => route.fulfill({
        status, contentType: 'application/json', body: JSON.stringify(body),
      });
      if (path === '/api/users/csrf/') return json(200, { csrfToken: 'e2e' });
      if (path === '/api/users/profile/') {
        return user ? json(200, { user }) : json(401, { error: 'Not signed in.' });
      }
      if (path === '/api/drivers/me/') {
        return json(200, { id: 17, name: 'Amina Hassan', phone_number: '+254712000111', company: 17 });
      }
      if (path === '/api/companies/operator-routes/') return json(200, { routes: [], operators: [] });
      // A record that does not exist yet.
      if (/\/\d+\/$/.test(path) && route.request().method() === 'GET') {
        return json(404, { error: 'Not found.' });
      }
      return json(200, []);
    });
    if (user) {
      await page.addInitScript((u) => localStorage.setItem('user_session', JSON.stringify(u)), user);
    }

    for (const path of paths) {
      crashes.length = 0;
      await page.goto(path);
      await expect(page.getByRole('status').filter({ hasText: 'Loading CONNECT' }))
        .toHaveCount(0, { timeout: 10000 });
      await page.waitForTimeout(400);
      const text = (await page.locator('#root').innerText()).trim();
      expect.soft(crashes, `${path} threw`).toEqual([]);
      expect.soft(text.length, `${path} rendered nothing`).toBeGreaterThan(40);
      expect.soft(new URL(page.url()).pathname, `${path} bounced elsewhere`).toBe(path);
    }
  });
}
