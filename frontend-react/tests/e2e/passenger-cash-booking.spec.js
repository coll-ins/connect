import { expect, test } from '@playwright/test';

const passenger = {
  id: 7,
  username: 'cash_passenger',
  name: 'Cash Passenger',
  role: 'passenger',
};

// Shape of GET /api/bookings/trips/<id>/seat-map/ (backend bookings/seats.py
// seat_map) for a 14-seat HiAce with seat 3 already sold.
const seatMap = {
  trip_id: 22,
  capacity: 14,
  bus: { fleet_number: 'EXL-01', plate: 'KDA 123A', vehicle_type: 'matatu_14' },
  vehicle_label: '14-seater matatu (Toyota HiAce Commuter)',
  plan_verified: true,
  driver_name: 'Maria Njeri',
  layout: [
    [1, 2, null, 'D'],
    ['door', 3, 4, 5],
    [6, null, 7, 8],
    [9, null, 10, 11],
    [12, null, 13, 14],
  ],
  seats: Array.from({ length: 14 }, (_, i) => (
    i + 1 === 3 ? { no: 3, state: 'booked', mine: false } : { no: i + 1, state: 'free' }
  )),
  unassigned: 0,
};

test('cash reservation opens its trip map without confirming payment', async ({ page }) => {
  // Cash is off at launch (CASH_ENABLED); this rider is on a cash-enabled
  // deployment and has earned it.
  const cashPassenger = { ...passenger, cash_enabled: true, can_pay_cash: true };
  let selectedDate;
  let createdBooking;
  let cashSelected = false;
  let bookingsAfterCash = 0;
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
      body = { user: cashPassenger };
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
        capacity: 14,
        route_details: {
          name: 'Nairobi to Mombasa',
          price: '800.00',
        },
      }];
    } else if (path === '/api/bookings/trips/22/seat-map/') {
      body = seatMap;
    } else if (path === '/api/bookings/create/' && method === 'POST') {
      createdBooking = route.request().postDataJSON();
      body = {
        booking_id: 42,
        booking_number: 'CN-0042',
        total_amount: '800.00',
      };
    } else if (path === '/api/bookings/payments/42/cash/' && method === 'POST') {
      cashSelected = true;
      body = { booking_id: 42, method: 'cash', status: 'pending' };
    } else if (path === '/api/bookings/my/') {
      if (cashSelected && bookingsAfterCash++ < 2) {
        body = [];
      } else {
        body = [cashBooking];
      }
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
  }, cashPassenger);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/passenger');

  await page.getByRole('button', { name: /Book a seat/ }).click();
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

  // On a short phone, the seat choice, the book button and the payment
  // choices must all be on screen without scrolling.
  // 540 is what a small phone has left once its browser bars are showing.
  await page.setViewportSize({ width: 360, height: 540 });
  const expectOnScreen = async (locator) => {
    await expect(locator).toBeVisible();
    const box = await locator.boundingBox();
    expect(box).not.toBeNull();
    expect(box.y).toBeGreaterThanOrEqual(0);
    expect(box.y + box.height).toBeLessThanOrEqual(540);
    // Nothing is covering it, so it can be tapped without scrolling.
    const onTop = await locator.evaluate((el) => {
      const r = el.getBoundingClientRect();
      const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
      return el === hit || el.contains(hit);
    });
    expect(onTop).toBe(true);
  };
  await expect(page.getByRole('button', { name: 'Seat 3, booked' })).toBeDisabled();
  await expectOnScreen(page.getByRole('radio', { name: 'Choose for me' }));
  await expectOnScreen(page.getByRole('button', { name: 'Pick a seat first' }));
  await expect(page.getByRole('button', { name: 'Pick a seat first' })).toBeDisabled();

  await page.getByRole('radio', { name: 'Choose for me' }).click();
  const seatCount = page.locator('.booking-seat-count strong');
  await expect(seatCount).toHaveText('1');
  await page.getByRole('button', { name: 'One seat more' }).click();
  await expect(seatCount).toHaveText('2');
  await page.getByRole('button', { name: 'One seat fewer' }).click();
  await expect(seatCount).toHaveText('1');

  await page.getByRole('radio', { name: "I'll pick my seats" }).click();
  await page.getByRole('button', { name: 'Seat 5, free' }).click();
  await expectOnScreen(page.getByRole('button', { name: 'Book seat 5' }));
  await page.getByRole('button', { name: 'Book seat 5' }).click();
  await expectOnScreen(page.getByRole('button', { name: /Pay cash on board/ }));
  await expectOnScreen(page.getByRole('button', { name: /Pay online/ }));
  await page.getByRole('button', { name: /Pay cash on board/ }).click();

  await expect(page).toHaveURL(/\/passenger\/map\?booking=42$/);
  const paymentNotice = page.locator('.cn-notice-info');
  await expect(paymentNotice).toContainText('Cash payment selected', { timeout: 15000 });
  await expect(paymentNotice).toContainText('Pay your fare in cash to the driver');
  await expect.poll(() => bookingsAfterCash, { timeout: 15000 }).toBeGreaterThanOrEqual(3);
  await expect(
    page.locator('.leaflet-overlay-pane path').first(),
  ).toBeVisible();
  expect(createdBooking).toEqual({
    trip_id: 22, seats: 1, seat_numbers: [5], pickup_stage_id: 5,
  });
  expect(selectedDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);
});

test('confirmed M-PESA payment enters the selected trip map automatically', async ({ page }) => {
  let createdBooking;
  const confirmedBooking = {
    booking_id: 42,
    booking_number: 'CN-0042',
    status: 'confirmed',
    payment_method: 'digital',
    payment_status: 'confirmed',
    trip_status: 'scheduled',
    route_name: 'Nairobi to Mombasa',
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
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
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
      body = [{
        id: 22,
        departure_at: '2026-11-06T09:00:00+03:00',
        status: 'scheduled',
        capacity: 14,
        route_details: { name: 'Nairobi to Mombasa', price: '800.00' },
      }];
    } else if (path === '/api/bookings/trips/22/seat-map/') {
      body = seatMap;
    } else if (path === '/api/bookings/create/' && request.method() === 'POST') {
      createdBooking = request.postDataJSON();
      body = {
        booking_id: 42,
        booking_number: 'CN-0042',
        total_amount: '800.00',
      };
    } else if (path === '/api/bookings/payments/42/mpesa/' && request.method() === 'POST') {
      body = { display_text: 'M-PESA prompt sent' };
    } else if (path === '/api/bookings/payments/42/status/') {
      body = { payment_status: 'confirmed' };
    } else if (path === '/api/bookings/my/') {
      body = [confirmedBooking];
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

  await page.getByRole('button', { name: /Book a seat/ }).click();
  await page.getByRole('button', { name: /Express Line/ }).click();
  await page.getByRole('button', { name: /Nairobi.*Mombasa/ }).click();
  await page.getByRole('button', { name: /Westlands/ }).click();
  await page.getByRole('button', { name: /Select trip/ }).click();
  await expect(page.getByRole('button', { name: /Pay cash on board/ })).toHaveCount(0);
  await page.getByRole('radio', { name: 'Choose for me' }).click();
  await page.getByRole('button', { name: 'Book 1 seat' }).click();
  // Cash is off at launch: online payment is the only choice.
  await expect(page.getByRole('button', { name: /Pay cash on board/ })).toHaveCount(0);
  await page.getByRole('button', { name: /Pay online/ }).click();
  await page.getByRole('button', { name: 'M-PESA' }).click();
  await page.getByRole('button', { name: 'Pay with my number' }).click();

  await expect(page).toHaveURL(/\/passenger\/map\?booking=42$/);
  await expect(
    page.locator('.leaflet-overlay-pane path').first(),
  ).toBeVisible();
  expect(createdBooking).toEqual({ trip_id: 22, seats: 1, pickup_stage_id: 5 });
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

test('closing the payment sheet before paying books nothing and frees the seat', async ({ page }) => {
  const calls = [];
  let cancelled = false;
  let mpesaSent = false;
  const pendingBooking = {
    id: 42, booking_id: 42, booking_number: 'CN-0042', status: 'pending',
    payment_status: 'unpaid', trip_status: 'scheduled', route_name: 'Nairobi to Mombasa',
  };
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
    calls.push(`${method} ${path}`);
    let body = [];
    if (path === '/api/users/csrf/') body = { csrfToken: 'e2e-csrf-token' };
    else if (path === '/api/users/profile/') body = { user: passenger };
    else if (path === '/api/companies/') body = [{ id: 1, name: 'Express Line' }];
    else if (path === '/api/companies/1/routes/') {
      body = [{
        id: 11, name: 'Nairobi to Mombasa', start_point: 'Nairobi', end_point: 'Mombasa',
        price: '800.00', pickup_stages: [{ id: 5, name: 'Westlands', is_active: true }],
      }];
    } else if (path === '/api/companies/1/trips/') {
      body = [{
        id: 22, departure_at: `${url.searchParams.get('date')}T09:00:00+03:00`, status: 'scheduled',
        capacity: 14, route_details: { name: 'Nairobi to Mombasa', price: '800.00' },
      }];
    } else if (path === '/api/bookings/trips/22/seat-map/') body = seatMap;
    else if (path === '/api/bookings/create/' && method === 'POST') {
      body = { booking_id: 42, booking_number: 'CN-0042', total_amount: '800.00' };
    } else if (path === '/api/bookings/42/cancel/' && method === 'POST') {
      cancelled = true;
      body = { message: 'Booking cancelled' };
    } else if (path === '/api/bookings/payments/42/mpesa/' && method === 'POST') {
      mpesaSent = true;
      body = { display_text: 'Check your phone.' };
    } else if (path === '/api/bookings/payments/42/status/') body = { payment_status: 'pending' };
    else if (path === '/api/bookings/my/') body = calls.includes('POST /api/bookings/create/') && !cancelled ? [pendingBooking] : [];
    else if (path === '/api/wallet/') body = {};
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.addInitScript((user) => {
    localStorage.setItem('user_session', JSON.stringify(user));
  }, passenger);
  await page.setViewportSize({ width: 390, height: 844 });

  const bookSeatFive = async () => {
    await page.goto('/passenger');
    await page.getByRole('button', { name: /Book a seat/ }).click();
    await page.getByRole('button', { name: /Express Line/ }).click();
    await page.getByRole('button', { name: /Nairobi.*Mombasa/ }).click();
    await page.getByRole('button', { name: /Westlands/ }).click();
    await page.getByRole('button', { name: /Select trip/ }).click();
    await page.getByRole('button', { name: 'Seat 5, free' }).click();
    await page.getByRole('button', { name: 'Book seat 5' }).click();
    await expect(page.getByRole('button', { name: /Pay online/ })).toBeVisible();
  };

  // Left before choosing how to pay: the booking is cancelled.
  await bookSeatFive();
  await page.getByRole('button', { name: 'Close' }).click();
  await expect.poll(() => cancelled).toBe(true);
  await expect(page.getByText('nothing was booked')).toBeVisible();

  // Phone Back does the same.
  cancelled = false;
  calls.length = 0;
  await bookSeatFive();
  await page.goBack();
  await expect.poll(() => cancelled).toBe(true);

  // An M-PESA prompt already sent: money may be on its way, so keep the booking.
  cancelled = false;
  calls.length = 0;
  await bookSeatFive();
  await page.getByRole('button', { name: /Pay online/ }).click();
  await page.getByRole('button', { name: /M-PESA/ }).click();
  await page.getByLabel('M-PESA phone number').fill('0712345678');
  await page.getByRole('button', { name: 'Proceed' }).click();
  await expect.poll(() => mpesaSent).toBe(true);
  await page.getByRole('button', { name: 'Close' }).click();
  await page.waitForTimeout(500);
  expect(cancelled).toBe(false);
});
