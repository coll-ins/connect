import { expect, test } from '@playwright/test';

const passenger = {
  id: 7,
  username: 'cash_passenger',
  name: 'Cash Passenger',
  role: 'passenger',
};

test('cash reservation opens its trip map without confirming payment', async ({ page }) => {
  let selectedDate;
  const cashBooking = {
    id: 42,
    booking_id: 42,
    booking_number: 'CN-0042',
    status: 'pending',
    payment_method: 'cash',
    payment_status: 'pending',
    trip_status: 'scheduled',
    passenger: { name: 'Cash Passenger' },
    route_geometry: {
      type: 'LineString',
      coordinates: [
        [36.8219, -1.2864],
        [36.823, -1.287],
      ],
    },
    pickup_latitude: -1.2864,
    pickup_longitude: 36.8219,
    pickup_stage_name: 'Westlands',
  };

  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
    let body = [];

    if (path === '/api/users/csrf/') {
      body = { csrfToken: 'e2e-csrf-token' };
    } else if (path === '/api/users/profile/') {
      body = { user: passenger };
    } else if (path === '/api/companies/') {
      body = [{ id: 1, name: 'Express Line' }];
    } else if (path === '/api/companies/1/routes/') {
      body = [{
        id: 11,
        name: 'Nairobi to Mombasa',
        start_point: 'Nairobi',
        end_point: 'Mombasa',
        price: '800.00',
        pickup_stages: [{ id: 5, name: 'Westlands', is_active: true }],
      }];
    } else if (path === '/api/companies/1/trips/') {
      selectedDate = url.searchParams.get('date');
      body = [{
        id: 22,
        departure_at: `${selectedDate}T09:00:00+03:00`,
        status: 'scheduled',
        capacity: 10,
        route_details: {
          name: 'Nairobi to Mombasa',
          price: '800.00',
        },
      }];
    } else if (path === '/api/bookings/create/' && method === 'POST') {
      body = {
        booking_id: 42,
        booking_number: 'CN-0042',
        total_amount: '800.00',
      };
    } else if (path === '/api/bookings/payments/42/cash/' && method === 'POST') {
      body = { booking_id: 42, method: 'cash', status: 'pending' };
    } else if (path === '/api/bookings/my/') {
      body = [cashBooking];
    } else if (path === '/api/wallet/') {
      body = {};
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
  });

  await page.addInitScript((user) => {
    localStorage.setItem('user_session', JSON.stringify(user));
  }, passenger);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/passenger');

  await page.getByRole('button', { name: /Book a Seat/ }).click();
  await page.getByRole('button', { name: /Express Line/ }).click();
  await page.getByRole('button', { name: /Nairobi.*Mombasa/ }).click();
  await page.getByRole('button', { name: /Westlands/ }).click();
  await expect(page.getByLabel('Departure date')).toHaveValue(/\d{4}-\d{2}-\d{2}/);
  await page.getByRole('button', { name: /Select trip/ }).click();

  const modal = page.locator('.modern-booking-modal');
  await expect(modal).toBeVisible();
  const modalBounds = await modal.boundingBox();
  expect(modalBounds).not.toBeNull();
  expect(modalBounds.y).toBeGreaterThanOrEqual(0);
  expect(modalBounds.y + modalBounds.height).toBeLessThanOrEqual(844);

  await page.getByRole('button', { name: 'Confirm booking & continue →' }).click();
  await page.getByRole('button', { name: /Pay with cash/ }).click();

  await expect(page).toHaveURL(/\/passenger\/map\?booking=42$/);
  const paymentNotice = page.locator('.cn-notice-info');
  await expect(paymentNotice).toContainText('Cash payment selected');
  await expect(paymentNotice).toContainText('Pay the driver to confirm');
  expect(selectedDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);
});

test('cash booking automatically enables live tracking when its driver starts boarding', async ({ page }) => {
  let bookingRequests = 0;
  let liveLocationRequests = 0;
  const pendingBooking = {
    id: 42,
    booking_id: 42,
    status: 'pending',
    payment_method: 'cash',
    payment_status: 'pending',
    trip_status: 'scheduled',
    route_name: 'Nairobi to Mombasa',
    route_geometry: {
      type: 'LineString',
      coordinates: [
        [36.8219, -1.2864],
        [36.823, -1.287],
      ],
    },
  };
  const trackableBooking = {
    ...pendingBooking,
    status: 'confirmed',
    payment_status: 'confirmed',
    trip_status: 'boarding',
    driver_id: 8,
    driver_name: 'Maria Njeri',
  };

  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body = [];

    if (path === '/api/users/csrf/') {
      body = { csrfToken: 'e2e-csrf-token' };
    } else if (path === '/api/users/profile/') {
      body = { user: passenger };
    } else if (path === '/api/bookings/my/') {
      bookingRequests += 1;
      body = [bookingRequests === 1 ? pendingBooking : trackableBooking];
    } else if (path === '/api/bookings/42/live-location/') {
      liveLocationRequests += 1;
      body = { driver: { name: 'Maria Njeri' } };
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
  });

  await page.addInitScript((user) => {
    localStorage.setItem('user_session', JSON.stringify(user));
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
  }, passenger);
  await page.goto('/passenger/map?booking=42');

  await expect(page.getByText('Cash payment selected')).toBeVisible();
  await expect.poll(() => liveLocationRequests, { timeout: 10000 }).toBeGreaterThan(0);
  await expect(page.getByText('Live trip')).toBeVisible();
  expect(bookingRequests).toBeGreaterThan(1);
});
