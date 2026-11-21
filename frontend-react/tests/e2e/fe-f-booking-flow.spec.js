import { expect, test } from '@playwright/test';

const passenger = { id: 7, username: 'flow_passenger', name: 'Flow Passenger', role: 'passenger' };
// Shape of GET /api/bookings/trips/<id>/seat-map/: ten free seats on trip 22.
const seatMap = {
  trip_id: 22,
  capacity: 10,
  bus: { fleet_number: 'EXL-01', plate: 'KDA 123A', vehicle_type: 'matatu_14' },
  vehicle_label: 'Test coach',
  plan_verified: true,
  driver_name: 'Maria Njeri',
  layout: [[1, 2, null, 'D'], [3, 4, 5, 6], [7, 8, 9, 10]],
  seats: Array.from({ length: 10 }, (_, i) => ({ no: i + 1, state: 'free' })),
  unassigned: 0,
};
const inTenMinutes = () => new Date(Date.now() + 10 * 60000).toISOString();

// One passenger, one company, one route, one trip with 10 seats. `state` lets a test shape the answers.
async function setup(page, state = {}) {
  state.calls = [];
  state.bookings = state.bookings || [];
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
    state.calls.push(`${method} ${path}`);
    let status = 200;
    let body = [];
    if (path === '/api/users/csrf/') body = { csrfToken: 'e2e-csrf-token' };
    else if (path === '/api/users/profile/') body = { user: passenger };
    else if (path === '/api/companies/') body = [{ id: 1, name: 'Express Line' }];
    else if (path === '/api/companies/1/routes/') {
      body = [{ id: 11, name: 'Nairobi to Mombasa', start_point: 'Nairobi', end_point: 'Mombasa', price: '800.00', pickup_stages: [{ id: 5, name: 'Westlands', is_active: true }] }];
    } else if (path === '/api/companies/1/trips/') {
      const date = url.searchParams.get('date');
      body = state.noTrips ? [] : [{ id: 22, departure_at: `${date}T23:30:00+03:00`, status: 'scheduled', capacity: 10, booked_seats: 0, route_details: { name: 'Nairobi to Mombasa', price: '800.00' } }];
    } else if (path === '/api/bookings/trips/22/seat-map/') body = seatMap;
    else if (path === '/api/bookings/create/' && method === 'POST') {
      state.createBody = route.request().postDataJSON();
      if (state.createError) { status = state.createError.status; body = state.createError.body; } else {
        body = { booking_id: 42, booking_number: 'CN-0042', total_amount: '800.00', pay_before: inTenMinutes() };
      }
    } else if (path === '/api/bookings/payments/42/wallet/' && method === 'POST') {
      status = 409; body = { code: 'hold_expired', error: 'server text' };
      state.bookings = [{ booking_id: 42, booking_number: 'CN-0042', status: 'expired', payment_status: 'pending', pay_before: new Date(Date.now() - 60000).toISOString() }];
    } else if (path === '/api/bookings/my/') {
      body = state.bookings;
    } else if (path === '/api/wallet/') body = { available_balance: '5000.00', held_balance: '0.00' };
    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.addInitScript((user) => localStorage.setItem('user_session', JSON.stringify(user)), passenger);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/passenger');
  await page.getByRole('button', { name: /Book a seat/ }).click();
  await page.getByRole('button', { name: /Express Line/ }).click();
  await page.getByRole('button', { name: /Nairobi.*Mombasa/ }).click();
  await page.getByRole('button', { name: /Westlands/ }).click();
  return state;
}

// Opens the booking sheet and takes seat 1, so the Book button is live.
const openBooking = async (page) => {
  await page.getByRole('button', { name: /Select trip/ }).click();
  await page.getByRole('button', { name: 'Seat 1, free' }).click();
};
const book = (page) => page.getByRole('button', { name: 'Book seat 1' });

test('the seat picker stops at 6 and says why', async ({ page }) => {
  await setup(page);
  await openBooking(page);
  for (let n = 2; n <= 7; n += 1) await page.getByRole('button', { name: `Seat ${n}, free` }).click();
  await expect(page.getByRole('button', { name: 'Book seats 1, 2, 3, 4, 5, 6' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Seat 7, your pick' })).toHaveCount(0);
  await expect(page.getByText('You can book up to 6 seats at a time.')).toBeVisible();
});

test('a seat_limit answer is shown as plain copy, not the server text', async ({ page }) => {
  await setup(page, { createError: { status: 400, body: { code: 'seat_limit', error: 'server text' } } });
  await openBooking(page);
  await book(page).click();
  await expect(page.getByText(/You can book up to 6 seats at a time\. Lower/)).toBeVisible();
  await expect(page.getByText('server text')).toHaveCount(0);
});

test('Escape in the pay dialog leaves focus on the page, not on <body>', async ({ page }) => {
  await setup(page);
  await openBooking(page);
  await book(page).focus();
  await page.keyboard.press('Enter');
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: /KES/ })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  const tag = await page.evaluate(() => document.activeElement?.tagName);
  expect(tag).not.toBe('BODY');
});

test('a rejected wallet payment refetches the booking and the countdown follows the server', async ({ page }) => {
  const state = await setup(page);
  await openBooking(page);
  await book(page).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText(/Pay within/)).toBeVisible();
  const before = state.calls.filter((c) => c === 'GET /api/bookings/my/').length;
  await dialog.getByRole('button', { name: /wallet/i }).click();
  await expect(dialog.getByText('The payment window for this seat closed. Nothing was taken from your wallet.')).toBeVisible();
  await expect(dialog.getByText(/Pay within/)).toHaveCount(0);
  await expect.poll(() => state.calls.filter((c) => c === 'GET /api/bookings/my/').length).toBeGreaterThan(before);
});

test('an empty day today explains that booking closes shortly before departure', async ({ page }) => {
  await setup(page, { noTrips: true });
  await expect(page.getByText(/No departures on/)).toBeVisible();
  await expect(page.getByText('Booking for a trip closes shortly before it leaves, so a bus about to depart is not listed.')).toBeVisible();
});
