import { test, expect } from '@playwright/test';

const scenarios = [
  {
    role: 'passenger',
    path: '/passenger',
    heading: /Where are you\s*going today/i,
  },
  {
    role: 'company_manager',
    path: '/company-manager',
    heading: 'Test Company',
  },
  {
    role: 'driver',
    path: '/driver',
    heading: 'Overview',
  },
];

const viewports = [
  { name: 'mobile', width: 390, height: 844 },
  { name: 'desktop', width: 1440, height: 900 },
];

function fixtureUser(role) {
  return {
    id: 17,
    username: 'CONNECT UI Test',
    name: 'CONNECT UI Test',
    role,
    company_id: 17,
    company_name: 'Test Company',
    is_staff: role === 'platform_admin',
    is_superuser: role === 'platform_admin',
  };
}

async function prepareScreen(page, role) {
  const user = fixtureUser(role);

  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());

    if (url.pathname === '/api/users/profile/') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ user }),
      });
      return;
    }

    if (url.pathname === '/api/drivers/me/') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(user),
      });
      return;
    }

    if (url.pathname === '/api/bookings/driver/17/') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ driver: user, active_trip: null, bookings: [] }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(
        url.pathname.endsWith('/analytics/') ? {} : [],
      ),
    });
  });

  await page.addInitScript((storedUser) => {
    localStorage.setItem('user_session', JSON.stringify(storedUser));
  }, user);
}

for (const scenario of scenarios) {
  for (const viewport of viewports) {
    test(`${scenario.role} screen renders without horizontal overflow on ${viewport.name}`, async ({ page }) => {
      const pageErrors = [];

      page.on('pageerror', (error) => pageErrors.push(error.message));
      await page.setViewportSize({
        width: viewport.width,
        height: viewport.height,
      });

      await prepareScreen(page, scenario.role);
      await page.goto(scenario.path);

      const pageHeading = page.locator('h1').first();
      await expect(pageHeading).toBeVisible();
      await expect(pageHeading).toContainText(scenario.heading);

      const layout = await page.evaluate(() => ({
        viewportWidth: window.innerWidth,
        documentWidth: document.documentElement.scrollWidth,
        bodyWidth: document.body.scrollWidth,
      }));

      console.log(
        `${scenario.role}/${viewport.name}: ${JSON.stringify(layout)}`,
      );

      expect(
        layout.documentWidth,
        `Document overflows horizontally: ${JSON.stringify(layout)}`,
      ).toBeLessThanOrEqual(layout.viewportWidth + 1);

      expect(
        layout.bodyWidth,
        `Body overflows horizontally: ${JSON.stringify(layout)}`,
      ).toBeLessThanOrEqual(layout.viewportWidth + 1);

      expect(pageErrors).toEqual([]);
    });
  }
}
