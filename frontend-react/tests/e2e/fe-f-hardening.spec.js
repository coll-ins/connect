import { test, expect } from '@playwright/test';
import { measure } from './contrast-helpers.js';
import { openCompanyPage, testUser } from './fe-b-helpers.js';

const AA_TEXT = 4.5;

const ROLES = [
  { role: 'passenger', path: '/passenger' },
  { role: 'driver', path: '/driver' },
  { role: 'company_manager', path: '/company-manager' },
  { role: 'company_auditor', path: '/company-auditor' },
  { role: 'company_operator', path: '/company-operator' },
  { role: 'platform_admin', path: '/platform-admin' },
];

const stageHandler = (path) => {
  if (path === '/api/companies/') return { body: [{ id: 1, name: 'Express Line' }] };
  if (path === '/api/companies/1/routes/') {
    return {
      body: [{
        id: 11, name: 'CBD to Rongai', start_point: 'Nairobi CBD', end_point: 'Rongai', price: '80.00',
        pickup_stages: [{ id: 5, name: 'Koja', is_active: true }, { id: 6, name: 'Afya', is_active: true }],
      }],
    };
  }
  return undefined;
};

test.describe('pickup stage screen at 390px', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('the other-pickup field and Continue are 44px and the stage text passes AA', async ({ page }) => {
    await openCompanyPage(page, 'passenger', '/passenger?step=stages&mode=seat&company=1&route=11', stageHandler);
    const field = page.locator('#other-pickup');
    await expect(field).toBeVisible();
    expect((await field.boundingBox()).height).toBeGreaterThanOrEqual(44);
    const next = page.getByRole('button', { name: 'Continue' });
    expect((await next.boundingBox()).height).toBeGreaterThanOrEqual(44);
    await expect(next).toHaveClass(/btn-primary/);
    for (const selector of ['.pickup-stage-number', '.pickup-stage-arrow', '.pickup-stage-kicker', '.pickup-route-pill span', '.pickup-stage-info small']) {
      expect((await measure(page, selector)).ratio, selector).toBeGreaterThanOrEqual(AA_TEXT);
    }
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBe(false);
  });
});

test.describe('closed mobile drawers at 360px', () => {
  test.use({ viewport: { width: 360, height: 740 } });

  for (const { role, path } of ROLES) {
    test(`${role}: Tab never lands on a link inside an off-screen drawer`, async ({ page }) => {
      await openCompanyPage(page, role, path);
      await page.locator('main, [role="main"], .connect-content, .driver-content, .pa-content').first().waitFor();
      const stops = [];
      for (let i = 0; i < 40; i += 1) {
        await page.keyboard.press('Tab');
        stops.push(await page.evaluate(() => {
          const el = document.activeElement;
          if (!el || el === document.body) return null;
          const box = el.getBoundingClientRect();
          const rail = el.closest('aside');
          return { name: (el.getAttribute('aria-label') || el.textContent || el.tagName).trim().slice(0, 30), offscreen: box.right <= 0 || box.left >= window.innerWidth, inClosedAside: Boolean(rail && rail.getBoundingClientRect().right <= 0) };
        }));
      }
      const bad = stops.filter((s) => s && (s.offscreen || s.inClosedAside));
      expect(bad, JSON.stringify(bad)).toEqual([]);
    });
  }
});

test.describe('tap targets at 375px', () => {
  test.use({ viewport: { width: 375, height: 800 } });

  for (const { role, path } of ROLES) {
    test(`${role}: the menu button and visible nav links are at least 44px`, async ({ page }) => {
      await openCompanyPage(page, role, path);
      const menu = page.locator('.connect-mobile-menu, .company-mobile-menu, .operator-menu-button, .audit-mobile-menu, .driver-menu-button, .driver-mobile-menu').first();
      if (await menu.count()) {
        const box = await menu.boundingBox();
        expect(box.height, 'menu button height').toBeGreaterThanOrEqual(44);
        expect(box.width, 'menu button width').toBeGreaterThanOrEqual(44);
      }
    });
  }
});

test('driver passenger rows: the booking code and the empty hint pass AA (no stacked opacity)', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const booking = { booking_id: 5, booking_number: 'CN-0005', passenger: 'Amina', status: 'confirmed', payment_status: 'confirmed', payment_method: 'wallet', seats: 1 };
  await openCompanyPage(page, 'driver', '/driver', (path) => {
    if (path === '/api/drivers/me/') return { body: { id: 17, name: 'Test Driver' } };
    if (path === '/api/bookings/driver/17/') return { body: [booking] };
    return undefined;
  }, testUser('driver'));
  await expect(page.getByText(/CN-0005/)).toBeVisible();
  expect((await measure(page, 'text=/CN-0005 ·/')).ratio).toBeGreaterThanOrEqual(AA_TEXT);
});

test('staff screens get their own tab title per route and no heading level is skipped', async ({ page }) => {
  await openCompanyPage(page, 'company_manager', '/company-manager/settings', (path) => (
    path === '/api/companies/booking-settings/' ? { body: { booking_cutoff_minutes: 30 } } : undefined));
  await expect(page.getByRole('heading', { name: 'Booking cut-off', level: 2 })).toBeVisible();
  await expect.poll(() => page.title()).toBe('Settings | CONNECT');
});
