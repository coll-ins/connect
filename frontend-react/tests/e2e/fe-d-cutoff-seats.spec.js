import { test, expect } from '@playwright/test';
import { collectPageErrors, openCompanyPage } from './fe-b-helpers.js';

const soon = new Date(Date.now() + 3600 * 1000).toISOString();
const trip = {
  id: 9, status: 'boarding', capacity: 30, booked_seats: 30, departure_at: soon,
  route_details: { name: 'CBD to Rongai' }, driver_name: 'Jane',
};
const summary = {
  trip_id: 9, capacity: 30, confirmed_seats: 20, pending_seats: 3, pending_expires_at: soon,
  boarded_seats: 4, open_seats: 7, online_open: true, online_closes_at: soon, walkup_allowed: true,
  by_stage: [{ stage_id: 1, name: 'Kencom', booked_seats: 12 }, { stage_id: 2, name: 'Rongai', booked_seats: 8 }],
};

const SETTINGS = '/api/companies/booking-settings/';
const SUMMARY = '/api/companies/trips/9/seat-summary/';
const operatorHandler = (summaryAnswer, tripOverride = {}) => (path) => {
  if (path === '/api/companies/17/trips/') return { body: [{ ...trip, ...tripOverride }] };
  if (path === SUMMARY) return summaryAnswer();
  return undefined;
};

test.describe('booking cut-off setting', () => {
  test('loads the saved value and saves a new one', async ({ page }) => {
    const errors = collectPageErrors(page);
    let patched = null;
    let saved = 30;
    await openCompanyPage(page, 'company_manager', '/company-manager/settings', (path, request) => {
      if (path !== SETTINGS) return undefined;
      if (request.method() === 'PATCH') {
        patched = request.postDataJSON();
        saved = patched.booking_cutoff_minutes;
        return { body: { booking_cutoff_minutes: saved } };
      }
      return { body: { booking_cutoff_minutes: saved } };
    });

    const input = page.getByLabel('Close online booking this many minutes before departure');
    await expect(input).toHaveValue('30');
    const save = page.getByRole('button', { name: 'Save' });
    await expect(save).toBeDisabled();
    await input.fill('45');
    await save.click();
    await expect(page.getByRole('status').filter({ hasText: 'Saved. Online booking now closes 45 minutes' })).toBeVisible();
    expect(patched).toEqual({ booking_cutoff_minutes: 45 });
    await expect(input).toHaveValue('45');
    expect(errors).toEqual([]);
  });

  test('a server 400 shows its message and keeps the typed value', async ({ page }) => {
    await openCompanyPage(page, 'company_manager', '/company-manager/settings', (path, request) => {
      if (path !== SETTINGS) return undefined;
      return request.method() === 'PATCH'
        ? { status: 400, body: { booking_cutoff_minutes: ['Ensure this value is less than or equal to 240.'] } }
        : { body: { booking_cutoff_minutes: 30 } };
    });
    const input = page.getByLabel('Close online booking this many minutes before departure');
    await input.fill('60');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'Ensure this value is less than or equal to 240.' })).toBeVisible();
    await expect(input).toHaveValue('60');
  });

  test('a 403 for a non-manager shows the permission message', async ({ page }) => {
    await openCompanyPage(page, 'company_manager', '/company-manager/settings', (path, request) => {
      if (path !== SETTINGS) return undefined;
      return request.method() === 'PATCH' ? { status: 403, body: { detail: 'no' } } : { body: { booking_cutoff_minutes: 30 } };
    });
    await page.getByLabel('Close online booking this many minutes before departure').fill('60');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'You don’t have permission' })).toBeVisible();
  });

  test('an out-of-range value is stopped before any request', async ({ page }) => {
    const calls = await openCompanyPage(page, 'company_manager', '/company-manager/settings', (path) =>
      path === SETTINGS ? { body: { booking_cutoff_minutes: 30 } } : undefined);
    const input = page.getByLabel('Close online booking this many minutes before departure');
    await input.fill('241');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'whole number of minutes from 0 to 240' })).toBeVisible();
    await expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(calls.filter((c) => c.startsWith('PATCH'))).toEqual([]);
  });

  test('a failed load shows Retry, then recovers', async ({ page }) => {
    let recovered = false;
    await openCompanyPage(page, 'company_manager', '/company-manager/settings', (path) =>
      path === SETTINGS
        ? (recovered ? { body: { booking_cutoff_minutes: 15 } } : { status: 500, body: {} })
        : undefined);
    await expect(page.getByRole('alert').filter({ hasText: 'Could not load the booking cut-off' })).toBeVisible();
    recovered = true;
    await page.getByRole('button', { name: 'Retry' }).click();
    await expect(page.getByLabel('Close online booking this many minutes before departure')).toHaveValue('15');
  });
});

test.describe('operator seat summary and walk-in guard', () => {
  test('shows the server numbers: booked, open, holds with expiry, walk-ups, stages', async ({ page }) => {
    const errors = collectPageErrors(page);
    await openCompanyPage(page, 'company_operator', '/company-operator/capacity',
      operatorHandler(() => ({ body: summary })));

    await expect(page.getByText('20 of 30')).toBeVisible();
    await expect(page.getByText('earliest hold ends')).toBeVisible();
    await expect(page.getByText('Allowed', { exact: true })).toBeVisible();
    await expect(page.getByText('Kencom: 12')).toBeVisible();
    await expect(page.getByText('Rongai: 8')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Book & board' })).toBeDisabled(); // empty phone only
    await page.getByLabel('Passenger phone').fill('0712345678');
    await expect(page.getByRole('button', { name: 'Book & board' })).toBeEnabled();
    expect(errors).toEqual([]);
  });

  test('walk-in is disabled with the reason when no seats are open', async ({ page }) => {
    await openCompanyPage(page, 'company_operator', '/company-operator/capacity',
      operatorHandler(() => ({ body: { ...summary, open_seats: 0, confirmed_seats: 27 } })));
    await page.getByLabel('Passenger phone').fill('0712345678');
    await expect(page.getByText('No seats are open on this trip.')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Book & board' })).toBeDisabled();
  });

  test('walk-in is disabled with the reason when walk-ups are not allowed', async ({ page }) => {
    await openCompanyPage(page, 'company_operator', '/company-operator/capacity',
      operatorHandler(() => ({ body: { ...summary, walkup_allowed: false } })));
    await page.getByLabel('Passenger phone').fill('0712345678');
    await expect(page.getByText('Walk-up booking is not allowed for this trip.')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Book & board' })).toBeDisabled();
  });

  test('a scheduled trip past its cut-off shows the walk-in form', async ({ page }) => {
    await openCompanyPage(page, 'company_operator', '/company-operator/capacity',
      operatorHandler(() => ({ body: { ...summary, online_open: false } }), { status: 'scheduled' }));
    await page.getByLabel('Passenger phone').fill('0712345678');
    await expect(page.getByRole('button', { name: 'Book & board' })).toBeEnabled();
  });

  test('a scheduled trip still open online shows the reason and no walk-in form', async ({ page }) => {
    await openCompanyPage(page, 'company_operator', '/company-operator/capacity',
      operatorHandler(() => ({ body: { ...summary, walkup_allowed: false } }), { status: 'scheduled' }));
    await expect(page.getByText('Walk-up booking is not allowed for this trip.')).toBeVisible();
    await expect(page.getByLabel('Passenger phone')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Book & board' })).toHaveCount(0);
  });

  test('a failed summary shows Retry and does not block the walk-in form', async ({ page }) => {
    let recovered = false;
    await openCompanyPage(page, 'company_operator', '/company-operator/capacity',
      operatorHandler(() => (recovered ? { body: summary } : { status: 500, body: {} })));
    await expect(page.getByRole('alert').filter({ hasText: 'Could not load seat details' })).toBeVisible();
    await page.getByLabel('Passenger phone').fill('0712345678');
    await expect(page.getByRole('button', { name: 'Book & board' })).toBeEnabled();
    recovered = true;
    await page.getByRole('button', { name: 'Retry' }).click();
    await expect(page.getByText('20 of 30')).toBeVisible();
  });

  test('a refused walk-in refreshes the summary from the server', async ({ page }) => {
    let phase = 'before';
    await openCompanyPage(page, 'company_operator', '/company-operator/capacity', (path, request) => {
      if (path === '/api/companies/17/trips/') return { body: [trip] };
      if (path === SUMMARY) return { body: phase === 'before' ? summary : { ...summary, open_seats: 0 } };
      if (path === '/api/bookings/walk-in/9/' && request.method() === 'POST') {
        phase = 'after';
        return { status: 400, body: { error: 'Only 0 seats are open.' } };
      }
      return undefined;
    });
    await page.getByLabel('Passenger phone').fill('0712345678');
    await page.getByRole('button', { name: 'Book & board' }).click();
    await expect(page.getByText('No seats are open on this trip.')).toBeVisible();
  });

  test('phone width: no horizontal scroll with the summary open', async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 375, height: 800 }, hasTouch: true, isMobile: true });
    const page = await context.newPage();
    await openCompanyPage(page, 'company_operator', '/company-operator/capacity',
      operatorHandler(() => ({ body: summary })));
    await expect(page.getByText('20 of 30')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
    await context.close();
  });
});
