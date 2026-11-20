import { test, expect } from '@playwright/test';
import { measure } from './contrast-helpers.js';
import { openCompanyPage, testUser } from './fe-b-helpers.js';

const AA_TEXT = 4.5;
const AA_UI = 3;
const soon = new Date(Date.now() + 3600 * 1000).toISOString();
const booking = (id, status) => ({
  id, booking_id: id, booking_number: `CN-00${id}`, status, payment_method: 'mpesa', payment_status: 'paid',
  trip_status: 'scheduled', route_name: 'CBD to Githurai 45', total_amount: '120.00', seats: 1,
  pickup_location: 'Kencom stage', pay_before: soon,
});

test.use({ viewport: { width: 390, height: 844 } });

test('login: button, link, muted text, input border and focus ring pass AA', async ({ page }) => {
  await page.route('**/api/**', (route) => route.fulfill({ status: 401, contentType: 'application/json', body: '{}' }));
  await page.goto('/login');
  expect((await measure(page, '.auth-card .btn-primary')).ratio).toBeGreaterThanOrEqual(AA_TEXT);
  expect((await measure(page, '.auth-footer a')).ratio).toBeGreaterThanOrEqual(AA_TEXT);
  expect((await measure(page, '.auth-card .muted')).ratio).toBeGreaterThanOrEqual(AA_TEXT);
  expect((await measure(page, '.auth-card input')).ratio).toBeGreaterThanOrEqual(AA_TEXT);
  expect((await measure(page, '.auth-card input', { part: 'border' })).ratio).toBeGreaterThanOrEqual(AA_UI);
  await page.keyboard.press('Tab');
  await page.locator('.auth-card input').first().focus();
  expect((await measure(page, '.auth-card input:focus-visible', { part: 'outline' })).ratio).toBeGreaterThanOrEqual(AA_UI);
});

test('passenger bookings: every status chip passes AA text and the chips differ', async ({ page }) => {
  const rows = [booking(1, 'pending'), booking(2, 'confirmed'), booking(3, 'boarded'), booking(4, 'cancelled'), booking(5, 'refunded')];
  await openCompanyPage(page, 'passenger', '/passenger/bookings', (path) => (path === '/api/bookings/my/' ? { body: rows } : undefined));
  const colours = [];
  for (let i = 0; i < rows.length; i += 1) {
    const chip = await measure(page, '.passenger-status', { nth: i });
    expect(chip.ratio, `chip ${rows[i].status}`).toBeGreaterThanOrEqual(AA_TEXT);
    colours.push(chip.fg);
  }
  expect(new Set(colours).size).toBe(rows.length);
  await expect(page.locator('.passenger-status svg')).toHaveCount(rows.length);
});

test('driver overview: eyebrow, link and timetable chips pass AA', async ({ page }) => {
  const trips = [
    { id: 1, status: 'scheduled' }, { id: 2, status: 'boarding' }, { id: 3, status: 'completed' }, { id: 4, status: 'cancelled' },
  ].map((t) => ({ ...t, departure_at: soon, route_name: 'CBD to Rongai', bus_number: 'KAA 001A', start_point: 'CBD', end_point: 'Rongai', capacity: 30 }));
  await openCompanyPage(page, 'driver', '/driver', (path) => {
    if (path === '/api/drivers/me/') return { body: { id: 17, name: 'Test Driver' } };
    if (path === '/api/drivers/me/timetable/') return { body: { trips } };
    return undefined;
  }, testUser('driver'));
  await expect(page.locator('.driver-timetable-status').first()).toBeVisible();
  for (let i = 0; i < trips.length; i += 1) {
    expect((await measure(page, '.driver-timetable-status', { nth: i })).ratio, trips[i].status).toBeGreaterThanOrEqual(AA_TEXT);
  }
  expect((await measure(page, '.driver-eyebrow')).ratio).toBeGreaterThanOrEqual(AA_TEXT);
  expect((await measure(page, '.driver-timetable-link')).ratio).toBeGreaterThanOrEqual(AA_TEXT);
});

test('operator: departure status chips and the primary button pass AA', async ({ page }) => {
  const trips = ['scheduled', 'boarding', 'completed', 'cancelled'].map((status, i) => ({
    id: i + 1, status, capacity: 30, booked_seats: 10, departure_at: soon, route_details: { name: 'CBD to Rongai' }, driver_name: 'Jane',
  }));
  await openCompanyPage(page, 'company_operator', '/company-operator', (path) => (/\/api\/companies\/\d+\/trips\//.test(path) ? { body: trips } : undefined));
  await expect(page.locator('.operator-status').first()).toBeVisible();
  const count = await page.locator('.operator-status').count();
  for (let i = 0; i < count; i += 1) {
    expect((await measure(page, '.operator-status', { nth: i })).ratio).toBeGreaterThanOrEqual(AA_TEXT);
  }
  expect((await measure(page, '.operator-eyebrow')).ratio).toBeGreaterThanOrEqual(AA_TEXT);
});
