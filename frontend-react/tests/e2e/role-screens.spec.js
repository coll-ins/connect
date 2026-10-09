import { test, expect } from '@playwright/test';

const testUser = (role) => ({
  id: 17,
  username: 'connect_e2e_user',
  name: 'CONNECT Test User',
  role,
  company_id: 17,
  company_name: 'Test Company',
  is_staff: role === 'platform_admin',
  is_superuser: role === 'platform_admin',
});

async function openRolePage(page, role, path) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());

    if (url.pathname === '/api/users/profile/') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ user: testUser(role) }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    });
  });

  await page.addInitScript((user) => {
    localStorage.setItem('user_session', JSON.stringify(user));
  }, testUser(role));

  await page.goto(path);
}

test.describe('CONNECT role screen interactions', () => {
  test('passenger home renders all three primary journey choices', async ({ page }) => {
    const pageErrors = [];
    page.on('pageerror', error => pageErrors.push(error.message));

    await openRolePage(page, 'passenger', '/passenger');

    await expect(
      page.getByRole('heading', { name: /Where are you going today/i }),
    ).toBeVisible();

    await expect(page.getByRole('button', { name: /Book a Seat/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Order Delivery/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Book a Bus/i })).toBeVisible();

    expect(pageErrors).toEqual([]);
  });

  test('Book a Seat moves the passenger into company selection', async ({ page }) => {
    await openRolePage(page, 'passenger', '/passenger');

    await page.getByRole('button', { name: /Book a Seat/i }).click();

    await expect(
      page.getByRole('heading', { name: /Choose your transport company/i }),
    ).toBeVisible();
  });

  test('Order Delivery opens the passenger delivery screen', async ({ page }) => {
    await openRolePage(page, 'passenger', '/passenger');

    await page.getByRole('button', { name: /Order Delivery/i }).click();

    await expect(page).toHaveURL(/\/passenger\/delivery$/);
    await expect(page.locator('h1').first()).toBeVisible();
  });

  test('company manager overview renders and its route action navigates', async ({ page }) => {
    await openRolePage(page, 'company_manager', '/company-manager');

    await expect(
      page.locator('h1').filter({ hasText: 'Test Company' }),
    ).toBeVisible();

    await page.getByRole('link', { name: /Manage routes/i }).click();

    await expect(page).toHaveURL(/\/company-manager\/routes$/);
    await expect(
      page.getByRole('link', { name: 'Routes', exact: true }),
    ).toBeVisible();
  });

  test('driver portal exposes operational navigation and opens trips', async ({ page }) => {
    await openRolePage(page, 'driver', '/driver');

    await expect(page.getByRole('link', { name: "Today's Trips" })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Passengers' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Live Location' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Pickup Manifest' })).toBeVisible();

    await page.getByRole('link', { name: "Today's Trips" }).click();

    await expect(page).toHaveURL(/\/driver\/trips$/);
    await expect(
      page.getByRole('heading', { level: 1, name: "Today's Trips" }),
    ).toBeVisible();
  });
});

test('driver live-location screen sends simulated coordinates to the location endpoint', async ({ page, context }) => {
  const simulatedLocation = {
    latitude: -1.286389,
    longitude: 36.817223,
  };
  let capturedGpsPayload = null;
  let gpsPostCount = 0;

  await context.grantPermissions(['geolocation']);
  await context.setGeolocation(simulatedLocation);

  const driver = {
    ...testUser('driver'),
    id: 17,
    username: 'E2E Driver',
    latitude: simulatedLocation.latitude,
    longitude: simulatedLocation.longitude,
  };

  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());

    if (url.pathname === '/api/users/profile/') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ user: driver }),
      });
      return;
    }

    if (url.pathname === '/api/drivers/me/') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(driver),
      });
      return;
    }

    if (url.pathname === '/api/bookings/driver/17/') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          driver,
          active_trip: null,
          bookings: [],
        }),
      });
      return;
    }

    if (
      url.pathname === '/api/drivers/17/location/' &&
      route.request().method() === 'POST'
    ) {
      capturedGpsPayload = route.request().postDataJSON();
      gpsPostCount += 1;

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...driver,
          ...simulatedLocation,
        }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    });
  });

  await page.addInitScript((user) => {
    localStorage.setItem('user_session', JSON.stringify(user));
  }, driver);

  await page.goto('/driver/location');

  await expect(
    page.getByRole('heading', { level: 1, name: 'No assigned trip' }),
  ).toBeVisible();

  await expect.poll(() => capturedGpsPayload, { timeout: 10000 })
    .toEqual(simulatedLocation);
  expect(gpsPostCount).toBeGreaterThan(0);

  await expect(page.getByText('GPS LIVE', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Dashboard' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Locate me' })).toBeVisible();

  await page.getByRole('button', { name: 'Toggle trip details' }).click();

  await expect(page.locator('.driver-live-sheet')).toHaveClass(
    /driver-live-sheet-open/,
  );
});
