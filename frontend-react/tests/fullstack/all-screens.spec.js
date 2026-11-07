import { expect, test } from '@playwright/test';

// Accounts created by `manage.py seed_demo`.
const ROLES = {
  passenger: ['+254799000001', ['/passenger', '/passenger/schedules', '/passenger/map', '/passenger/bookings', '/passenger/wallet', '/passenger/payments', '/passenger/receipts', '/passenger/history', '/passenger/seats', '/passenger/help', '/passenger/profile', '/passenger/delivery', '/passenger/delivery/new', '/passenger/charter', '/passenger/charter/new']],
  driver: ['+254799000010', ['/driver', '/driver/trips', '/driver/passengers', '/driver/location', '/driver/boarding', '/driver/jobs', '/driver/profile']],
  operator: ['+254799000002', ['/company-operator', '/company-operator/bookings', '/company-operator/trips', '/company-operator/drivers', '/company-operator/capacity', '/company-operator/operations']],
  manager: ['+254799000003', ['/company-manager', '/company-manager/bookings', '/company-manager/charters', '/company-manager/drivers', '/company-manager/parcels', '/company-manager/revenue', '/company-manager/routes', '/company-manager/settings', '/company-manager/trips']],
  auditor: ['+254799000004', ['/company-auditor', '/company-auditor/audit', '/company-auditor/bookings', '/company-auditor/revenue', '/company-auditor/trips']],
  admin: ['+254799000005', ['/platform-admin', '/platform-admin/bookings', '/platform-admin/companies', '/platform-admin/drivers', '/platform-admin/reports', '/platform-admin/settings', '/platform-admin/trips', '/platform-admin/users']],
};

test.use({
  permissions: ['geolocation'],
  geolocation: { latitude: -1.2856, longitude: 36.825 },
});

for (const [role, [phone, paths]] of Object.entries(ROLES)) {
  test(`${role}: every screen loads against the real API`, async ({ page }, testInfo) => {
    const problems = [];
    page.on('pageerror', (err) => problems.push(`JS error: ${err.message}`));
    page.on('response', (res) => {
      if (res.url().includes('/api/') && res.status() >= 500) {
        problems.push(`${res.status()} ${res.request().method()} ${new URL(res.url()).pathname}`);
      }
    });

    await page.goto('/login');
    await page.getByLabel('Phone number').fill(phone);
    await page.getByLabel('Password', { exact: true }).fill('demo-pass-123');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page).not.toHaveURL(/\/login$/);

    for (const path of paths) {
      await page.goto(path);
      await page.waitForLoadState('networkidle').catch(() => {});
      expect(new URL(page.url()).pathname, `${path} redirected`).toBe(path);
      await page.screenshot({ path: testInfo.outputPath(`${path.slice(1).replace(/\//g, '_')}.png`) });
    }

    if (role === 'admin') {
      await page.goto('/platform-admin/users');
      await expect(page.getByText('demo_passenger')).toBeVisible();
    }

    expect(problems).toEqual([]);
  });
}
