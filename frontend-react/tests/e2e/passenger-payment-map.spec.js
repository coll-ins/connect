import { expect, test } from '@playwright/test';

const passengerUser = {
  id: 17,
  username: 'connect_e2e_user',
  name: 'CONNECT Test User',
  role: 'passenger',
  company_id: 17,
  company_name: 'Test Company',
  is_staff: false,
  is_superuser: false,
};

const confirmedBooking = {
  booking_id: 42,
  booking_number: 'CN-0042',
  status: 'confirmed',
  payment_status: 'confirmed',
  trip_status: 'scheduled',
  driver_id: 8,
  driver_name: 'Maria Njeri',
  driver_bus_number: 'KDA 123A',
  route_name: 'Airport Express',
  route_geometry: {
    type: 'LineString',
    coordinates: [
      [36.8172, -1.2864],
      [36.828, -1.279],
    ],
  },
  pickup_stage_name: 'Westlands',
  pickup_latitude: -1.267,
  pickup_longitude: 36.81,
};

async function setPassengerSession(page) {
  await page.addInitScript((user) => {
    window.localStorage.setItem('user_session', JSON.stringify(user));
  }, passengerUser);
}

async function stubPaymentReturnApi(page, { failVerification = false } = {}) {
  let liveLocationRequests = 0;

  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;

    if (path === '/api/users/csrf/') {
      await route.fulfill({
        status: 200,
        headers: { 'Set-Cookie': 'csrftoken=e2e-token; Path=/' },
        contentType: 'application/json',
        body: JSON.stringify({ csrfToken: 'e2e-token' }),
      });
      return;
    }

    if (path === '/api/users/profile/') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ user: passengerUser }),
      });
      return;
    }

    if (path === '/api/bookings/payments/42/verify/') {
      if (failVerification) {
        await route.abort('failed');
        return;
      }

      await new Promise((resolve) => setTimeout(resolve, 200));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          payment_status: 'confirmed',
          booking_status: 'confirmed',
        }),
      });
      return;
    }

    if (path === '/api/bookings/my/') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([confirmedBooking]),
      });
      return;
    }

    if (path === '/api/bookings/42/live-location/') {
      liveLocationRequests += 1;
      await route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Trip is not boarding yet.' }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '[]',
    });
  });

  return () => liveLocationRequests;
}

for (const viewport of [
  { name: 'mobile', width: 390, height: 844 },
  { name: 'desktop', width: 1440, height: 900 },
]) {
  test(`confirmed payment opens the driver map on ${viewport.name} in under one second`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await setPassengerSession(page);
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'geolocation', {
        configurable: true,
        value: {
          getCurrentPosition() {
            window.__connectGeolocationCalls =
              (window.__connectGeolocationCalls || 0) + 1;
          },
          watchPosition() {
            window.__connectGeolocationCalls =
              (window.__connectGeolocationCalls || 0) + 1;
            return 1;
          },
          clearWatch() {},
        },
      });
    });
    const liveLocationRequests = await stubPaymentReturnApi(page);
    let verificationFinishedAt = 0;

    page.on('response', (response) => {
      if (response.url().includes('/api/bookings/payments/42/verify/')) {
        verificationFinishedAt = Date.now();
      }
    });

    await page.goto('/passenger/payment/42?reference=e2e-reference');
    await expect(page).toHaveURL(/\/passenger\/map\?booking=42$/);
    await expect(page.getByText('Maria Njeri', { exact: true })).toBeVisible();
    await expect(page.getByText('KDA 123A', { exact: true })).toBeVisible();

    expect(verificationFinishedAt).toBeGreaterThan(0);
    expect(Date.now() - verificationFinishedAt).toBeLessThan(1000);
    expect(liveLocationRequests()).toBe(0);
    expect(await page.evaluate(() => window.__connectGeolocationCalls || 0)).toBe(0);
  });
}

test('live map labels stale GPS, route progress, and the lack of live city traffic', async ({
  page,
}) => {
  await setPassengerSession(page);
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'geolocation', {
      configurable: true,
      value: {
        getCurrentPosition() {},
        watchPosition() {
          return 1;
        },
        clearWatch() {},
      },
    });
  });

  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;

    if (path === '/api/users/csrf/') {
      await route.fulfill({
        status: 200,
        headers: { 'Set-Cookie': 'csrftoken=e2e-token; Path=/' },
        contentType: 'application/json',
        body: JSON.stringify({ csrfToken: 'e2e-token' }),
      });
      return;
    }

    if (path === '/api/users/profile/') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ user: passengerUser }),
      });
      return;
    }

    if (path === '/api/bookings/my/') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([{ ...confirmedBooking, trip_status: 'boarding' }]),
      });
      return;
    }

    if (path === '/api/bookings/42/live-location/') {
      const locationUpdatedAt = new Date(Date.now() - 5 * 60 * 1000).toISOString();
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          route_name: 'Airport Express',
          route_geometry: confirmedBooking.route_geometry,
          trip_status: 'boarding',
          is_trip_live: true,
          is_stale: true,
          location_age_seconds: 300,
          driver: {
            latitude: -1.2864,
            longitude: 36.8172,
            location_updated_at: locationUpdatedAt,
          },
          pickup: {
            name: 'Westlands',
            latitude: -1.267,
            longitude: 36.81,
          },
          stages: [],
        }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '{}',
    });
  });

  await page.goto('/passenger/map?booking=42');

  await expect(page.getByText('Last seen 5 min ago').first()).toBeVisible();
  await expect(
    page.getByRole('progressbar', { name: 'Bus progress along the trip route' }),
  ).toHaveAttribute('aria-valuetext', 'Waiting for a fresh GPS update');
  await expect(page.getByText('Traffic information')).toBeVisible();
  await expect(page.getByText(/No live city-traffic feed is available/)).toBeVisible();
  await expect(page.getByText('Bus to pickup')).toBeVisible();
});

test('a trip that has not started shows the bus parked at the first stage', async ({ page }) => {
  await setPassengerSession(page);
  const liveLocationRequests = await stubPaymentReturnApi(page);
  const departure = new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString();

  await page.route('**/api/bookings/my/', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          ...confirmedBooking,
          departure_at: departure,
          route_start_point: 'CBD',
          route_start_latitude: -1.2864,
          route_start_longitude: 36.8172,
        },
      ]),
    }),
  );

  await page.goto('/passenger/map?booking=42');

  const parkedBus = page.locator('.passenger-vehicle-marker.is-parked');
  await expect(parkedBus).toBeVisible();
  await expect(parkedBus).toContainText(/Departs/);
  await expect(page.getByText(/^Parked at CBD · Departs/).first()).toBeVisible();
  expect(liveLocationRequests()).toBe(0);
});

test('payment connection errors are explained in a top notice', async ({ page }) => {
  await setPassengerSession(page);
  await stubPaymentReturnApi(page, { failVerification: true });

  await page.goto('/passenger/payment/42?reference=e2e-reference');

  const notice = page.getByRole('alert').first();
  await expect(notice).toContainText(
    "We couldn't reach CONNECT. Check your internet connection and try again.",
  );
  await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible();
});
