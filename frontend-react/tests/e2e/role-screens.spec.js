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

    if (url.pathname === '/api/users/csrf/') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ csrfToken: 'e2e-csrf-token' }),
      });
      return;
    }

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

    await expect(page.getByRole('button', { name: /Book a seat/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Send a parcel/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Hire a bus/i })).toBeVisible();

    expect(pageErrors).toEqual([]);
  });

  test('Book a Seat moves the passenger into company selection', async ({ page }) => {
    await openRolePage(page, 'passenger', '/passenger');

    await page.getByRole('button', { name: /Book a seat/i }).click();

    await expect(
      page.getByRole('heading', { name: /Choose your transport company/i }),
    ).toBeVisible();
  });

  test('Order Delivery opens the passenger delivery screen', async ({ page }) => {
    await openRolePage(page, 'passenger', '/passenger');

    await page.getByRole('button', { name: /Send a parcel/i }).click();

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

  test('company operator navigation follows the URL and browser history', async ({ page }) => {
    await openRolePage(page, 'company_operator', '/company-operator/trips');

    await expect(
      page.getByRole('heading', { level: 1, name: 'Departures' }),
    ).toBeVisible();

    await page.getByRole('button', { name: 'Bookings', exact: true }).click();
    await expect(page).toHaveURL(/\/company-operator\/bookings$/);
    await expect(
      page.getByRole('heading', { level: 1, name: 'Bookings' }),
    ).toBeVisible();

    await page.goBack();
    await expect(page).toHaveURL(/\/company-operator\/trips$/);
    await expect(
      page.getByRole('heading', { level: 1, name: 'Departures' }),
    ).toBeVisible();
  });

  test('unknown company operator routes return to the overview', async ({ page }) => {
    await openRolePage(page, 'company_operator', '/company-operator/not-a-real-page');

    await expect(page).toHaveURL(/\/company-operator$/);
    await expect(page.getByRole('heading', { level: 1 })).toContainText("Today's operations");
  });

  test('driver portal exposes operational navigation and opens trips', async ({ page }) => {
    await openRolePage(page, 'driver', '/driver');

    await expect(page.getByRole('link', { name: 'My timetable' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Passengers' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Live location' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Pickup manifest' })).toBeVisible();

    await page.getByRole('link', { name: 'My timetable' }).click();

    await expect(page).toHaveURL(/\/driver\/trips$/);
    await expect(
      page.getByRole('heading', { level: 1, name: 'My timetable' }),
    ).toBeVisible();
  });
});

test('driver live-location screen shows its route, styles the panel, and sends GPS updates', async ({ page, context }) => {
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

    if (url.pathname === '/api/users/csrf/') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ csrfToken: 'e2e-csrf-token' }),
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
          active_trip: {
            id: 28,
            route_name: 'Nairobi to Thika',
            route_start_point: 'Nairobi CBD',
            route_end_point: 'Thika Town',
            departure_at: '2026-11-05T16:30:00Z',
            route_geometry: {
              type: 'LineString',
              coordinates: [
                [36.817223, -1.286389],
                [36.830000, -1.275000],
              ],
            },
            stages: [],
            bookings: [],
            passenger_count: 0,
            booking_count: 0,
          },
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
          location_updated_at: new Date().toISOString(),
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
    page.getByRole('heading', { level: 1, name: 'Nairobi to Thika' }),
  ).toBeVisible();
  await expect(page.getByText('Nairobi CBD → Thika Town')).toBeVisible();
  await expect(
    page.locator('.leaflet-overlay-pane path[stroke="#1677ff"]').first(),
  ).toBeVisible();
  const sheetBackground = await page
    .locator('.driver-live-sheet')
    .evaluate((element) => getComputedStyle(element).backgroundColor);
  expect(sheetBackground).toBe('rgba(15, 23, 42, 0.96)');

  await expect.poll(() => capturedGpsPayload, { timeout: 10000 })
    .toEqual(simulatedLocation);
  expect(gpsPostCount).toBeGreaterThan(0);

  await expect(page.getByText('GPS live', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Dashboard' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Locate me' })).toBeVisible();

  await expect(page.locator('.driver-live-sheet')).toHaveClass(
    /driver-live-sheet-open/,
  );
  await page.getByRole('button', { name: 'Toggle trip details' }).click();

  await expect(page.locator('.driver-live-sheet')).not.toHaveClass(
    /driver-live-sheet-open/,
  );
  await page.getByRole('button', { name: 'Toggle trip details' }).click();
  await expect(page.locator('.driver-live-sheet')).toHaveClass(
    /driver-live-sheet-open/,
  );
  await page.getByRole('button', { name: 'Dashboard' }).click();
  await expect(page).toHaveURL(/\/driver$/);
});
