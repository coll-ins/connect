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
  // The sheet is a --surface card; resolve the token instead of pinning a hex.
  const surface = await page.evaluate(() => {
    const probe = document.createElement('div');
    probe.style.background = 'var(--surface)';
    document.body.appendChild(probe);
    const colour = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return colour;
  });
  expect(sheetBackground).toBe(surface);

  await expect.poll(() => capturedGpsPayload, { timeout: 10000 })
    .toMatchObject(simulatedLocation);
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

// Shared plumbing: loading / error / empty states, dialog, route focus, auth alerts.
async function openPassenger(page, path, handlers = {}) {
  await page.route('**/api/**', async (route) => {
    const { pathname } = new URL(route.request().url());
    const json = (status, body) => route.fulfill({
      status, contentType: 'application/json', body: JSON.stringify(body),
    });
    if (pathname === '/api/users/csrf/') return json(200, { csrfToken: 'e2e' });
    if (pathname === '/api/users/profile/') return json(200, { user: testUser('passenger') });
    const handler = handlers[pathname];
    if (handler) return handler(route, json);
    return json(200, []);
  });
  await page.addInitScript((user) => {
    localStorage.setItem('user_session', JSON.stringify(user));
  }, testUser('passenger'));
  await page.goto(path);
}

test.describe('CONNECT shared states and accessibility plumbing', () => {
  test('a failed wallet load shows Retry and never KES 0.00', async ({ page }) => {
    let failing = true;
    await openPassenger(page, '/passenger/wallet', {
      '/api/wallet/': (route, json) => (failing
        ? json(500, { detail: 'boom' })
        : json(200, { available_balance: '1250.00', held_balance: '0.00' })),
    });

    await expect(page.getByText('Could not load your wallet')).toBeVisible();
    await expect(page.getByText('KES 0.00')).toHaveCount(0);
    failing = false;
    await page.getByRole('button', { name: 'Retry' }).click();
    await expect(page.getByText('KES 1,250.00')).toBeVisible();
    // The held-balance card was removed: nothing credits it, so it is not shown.
    await expect(page.getByText('Held balance')).toHaveCount(0);
  });

  test('wallet shows -- while loading, not KES 0.00', async ({ page }) => {
    await openPassenger(page, '/passenger/wallet', {
      '/api/wallet/': () => new Promise(() => {}),
    });
    await expect(page.locator('.wallet-overview-grid')).toHaveAttribute('aria-busy', 'true');
    await expect(page.locator('.wallet-main strong')).toHaveText('--');
    await expect(page.getByText('KES 0.00')).toHaveCount(0);
  });

  test('a failed bookings load shows Retry instead of "No bookings yet"', async ({ page }) => {
    await openPassenger(page, '/passenger/bookings', {
      '/api/bookings/my/': (route, json) => json(500, { detail: 'boom' }),
    });
    await expect(page.getByText('Could not load your bookings')).toBeVisible();
    await expect(page.getByText('No bookings yet.')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible();
  });

  test('payment history shows loading, then its empty state', async ({ page }) => {
    await openPassenger(page, '/passenger/payments');
    await expect(page.getByText('No payment history yet.')).toBeVisible();
  });

  test('the payment window is a labelled dialog that traps Tab and closes on Escape', async ({ page }) => {
    await openPassenger(page, '/passenger?pay=9', {
      '/api/bookings/my/': (route, json) => json(200, [{
        booking_id: 9, booking_number: 'BK-9', status: 'pending', payment_status: 'pending',
        trip_status: 'scheduled', total_amount: '300.00', route_name: 'CBD - Rongai',
      }]),
    });

    const dialog = page.getByRole('dialog', { name: 'KES 300.00' });
    await expect(dialog).toBeVisible();
    await expect(dialog).toHaveAttribute('aria-modal', 'true');
    await expect(dialog.getByRole('button', { name: 'Close' })).toBeVisible();

    for (let i = 0; i < 8; i += 1) {
      await page.keyboard.press('Tab');
      expect(await page.evaluate(() => !!document.activeElement.closest('[role="dialog"]'))).toBe(true);
    }
    for (let i = 0; i < 8; i += 1) {
      await page.keyboard.press('Shift+Tab');
      expect(await page.evaluate(() => !!document.activeElement.closest('[role="dialog"]'))).toBe(true);
    }

    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
  });

  test('the M-PESA number field has a visible label', async ({ page }) => {
    await openPassenger(page, '/passenger?pay=9', {
      '/api/bookings/my/': (route, json) => json(200, [{
        booking_id: 9, booking_number: 'BK-9', status: 'pending', payment_status: 'pending',
        trip_status: 'scheduled', total_amount: '300.00',
      }]),
    });
    await page.getByRole('button', { name: /Pay online/ }).click();
    await page.getByRole('button', { name: /M-PESA/ }).click();
    await expect(page.getByLabel('M-PESA phone number')).toBeVisible();
  });

  test('a route change moves focus to main, sets the title and a skip link exists', async ({ page }) => {
    await openPassenger(page, '/passenger/wallet');
    await expect(page).toHaveTitle('Wallet | CONNECT');
    const skip = page.getByRole('link', { name: 'Skip to main content' });
    await page.keyboard.press('Tab');
    await expect(skip).toBeFocused();

    await page.getByRole('link', { name: 'Payments' }).first().click();
    await expect(page).toHaveTitle('Payments | CONNECT');
    await expect(page.locator('main#main-content')).toBeFocused();
  });

  test('a failed sign-in is an alert, marks the fields invalid and focuses the phone field', async ({ page }) => {
    await page.route('**/api/**', async (route) => {
      const { pathname } = new URL(route.request().url());
      if (pathname === '/api/users/csrf/') {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ csrfToken: 'e2e' }) });
      }
      if (pathname === '/api/users/login/') {
        return route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ error: 'Wrong phone or password.' }) });
      }
      return route.fulfill({ status: 401, contentType: 'application/json', body: '{}' });
    });
    await page.goto('/login');
    await expect(page.locator('main')).toHaveCount(1);
    await page.getByLabel('Phone number').fill('0712345678');
    await page.getByLabel('Password', { exact: true }).fill('nope-nope');
    await page.getByRole('button', { name: 'Sign in' }).click();

    await expect(page.getByRole('alert')).toHaveText('Wrong phone or password.');
    await expect(page.getByLabel('Phone number')).toHaveAttribute('aria-invalid', 'true');
    await expect(page.getByLabel('Phone number')).toBeFocused();
    await expect(page.getByLabel('Password', { exact: true })).toHaveAttribute('aria-describedby', 'login-error');
  });

  test('the password toggle is reachable by keyboard and at least 44px', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Password', { exact: true }).focus();
    await page.keyboard.press('Tab');
    const toggle = page.getByRole('button', { name: 'Show password' });
    await expect(toggle).toBeFocused();
    const box = await toggle.boundingBox();
    expect(box.width).toBeGreaterThanOrEqual(44);
    expect(box.height).toBeGreaterThanOrEqual(44);
  });

  test('a render crash shows the fallback with a Reload button, not a blank page', async ({ page }) => {
    page.on('console', () => {});
    await openPassenger(page, '/passenger/bookings', {
      '/api/bookings/my/': (route, json) => json(200, [null]),
    });
    await expect(page.getByRole('alert').getByText('Something went wrong')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Reload' })).toBeVisible();
  });
});
