import { test, expect } from '@playwright/test';
import { collectPageErrors, openCompanyPage } from './fe-b-helpers.js';

const soon = new Date(Date.now() + 3600 * 1000).toISOString();
const boardingTrip = {
  id: 9,
  status: 'boarding',
  capacity: 30,
  booked_seats: 5,
  departure_at: soon,
  route_details: { name: 'CBD to Rongai' },
  driver_name: 'Jane',
};
const unassigned = { booking_id: 41, trip_id: 9, route_name: 'CBD to Rongai', seats: 2, status: 'confirmed' };

test.describe('company operator', () => {
  test('a failed first load shows Retry, not an empty dashboard, then recovers', async ({ page }) => {
    // The dev server mounts effects twice, so fail by phase, not by call count.
    let recovered = false;
    await openCompanyPage(page, 'company_operator', '/company-operator', (path) =>
      path === '/api/companies/17/trips/'
        ? (recovered ? { body: [boardingTrip] } : { status: 500, body: {} })
        : undefined);

    await expect(page.getByRole('alert').filter({ hasText: 'Could not load company operations' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible();
    recovered = true;
    await page.getByRole('button', { name: 'Retry' }).click();
    await expect(page.getByRole('alert')).toHaveCount(0);
  });

  test('operator not linked to a company is told so', async ({ page }) => {
    await openCompanyPage(page, 'company_operator', '/company-operator', () => undefined,
      { id: 3, username: 'op', role: 'company_operator', company_id: null });
    await expect(page.getByRole('alert')).toContainText('not assigned to a company');
  });

  test('assignment dialog is labelled, has Close and Escape, and gives focus back', async ({ page }) => {
    const errors = collectPageErrors(page);
    await openCompanyPage(page, 'company_operator', '/company-operator/bookings', (path) =>
      path === '/api/bookings/all/' ? { body: [unassigned] } : undefined);
    const opener = page.getByRole('button', { name: 'Assign', exact: true }).first();
    await opener.click();

    const dialog = page.getByRole('dialog', { name: 'Assign existing driver' });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Close' })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(opener).toBeFocused();
    expect(errors).toEqual([]);
  });

  test('capacity card uses the server seat count and the walk-in form is labelled', async ({ page }) => {
    await openCompanyPage(page, 'company_operator', '/company-operator/capacity', (path, request) => {
      if (path === '/api/companies/17/trips/') return { body: [boardingTrip] };
      if (path === '/api/bookings/walk-in/9/' && request.method() === 'POST') {
        return { status: 400, body: { error: 'Only 25 seats are open.' } };
      }
      return undefined;
    });

    await expect(page.getByText('5 / 30 seats')).toBeVisible();
    const phone = page.getByLabel('Passenger phone');
    await expect(phone).toHaveAttribute('inputmode', 'tel');
    await expect(page.getByLabel('Seats', { exact: true }).first()).toBeVisible();
    await phone.fill('0712345678');
    await page.getByRole('button', { name: 'Book & board' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'Only 25 seats are open.' })).toBeVisible();
  });

  test('phone width: no horizontal scroll on the operator capacity page', async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 375, height: 800 }, hasTouch: true, isMobile: true });
    const page = await context.newPage();
    await openCompanyPage(page, 'company_operator', '/company-operator/capacity', (path) =>
      path === '/api/companies/17/trips/' ? { body: [boardingTrip] } : undefined);
    await expect(page.getByText('5 / 30 seats')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
    await context.close();
  });
});

test.describe('company auditor', () => {
  test('a failed load shows Retry instead of empty registers, then recovers', async ({ page }) => {
    let recovered = false;
    await openCompanyPage(page, 'company_auditor', '/company-auditor/bookings', (path) =>
      path === '/api/companies/17/trips/'
        ? (recovered ? { body: [] } : { status: 500, body: {} })
        : undefined);

    await expect(page.getByRole('alert').filter({ hasText: 'Could not load company audit records' })).toBeVisible();
    await expect(page.getByText('No bookings recorded yet')).toHaveCount(0);
    recovered = true;
    await page.getByRole('button', { name: 'Retry' }).click();
    await expect(page.getByText('No bookings recorded yet')).toBeVisible();
  });

  test('incidents failure shows Retry in the register, not an empty list', async ({ page }) => {
    await openCompanyPage(page, 'company_auditor', '/company-auditor/incidents', (path) =>
      path === '/api/bookings/incidents/' ? { status: 500, body: {} } : undefined);

    await expect(page.getByRole('alert').filter({ hasText: 'Could not load incidents' })).toBeVisible();
    await expect(page.getByText('No incidents reported')).toHaveCount(0);
  });

  test('search box has a name and an empty submit is announced', async ({ page }) => {
    await openCompanyPage(page, 'company_auditor', '/company-auditor/search');
    const box = page.getByRole('textbox', { name: /Search by receipt/ });
    await expect(box).toBeVisible();
    await page.getByRole('button', { name: 'Search', exact: true }).click();

    await expect(page.getByRole('alert')).toContainText('Enter something to search.');
    await expect(box).toHaveAttribute('aria-invalid', 'true');
  });

  test('no results is a status, not an alert', async ({ page }) => {
    await openCompanyPage(page, 'company_auditor', '/company-auditor/search');
    await page.getByRole('textbox', { name: /Search by receipt/ }).fill('zzz');
    await page.getByRole('button', { name: 'Search', exact: true }).click();

    await expect(page.getByRole('status').filter({ hasText: 'No matching records found.' })).toBeVisible();
    await expect(page.getByRole('alert')).toHaveCount(0);
  });

  test('search bar shows a focus ring', async ({ page }) => {
    await openCompanyPage(page, 'company_auditor', '/company-auditor/search');
    await page.getByRole('textbox', { name: /Search by receipt/ }).focus();
    const outline = await page.locator('.audit-search-form').evaluate((el) => getComputedStyle(el).outlineStyle);
    expect(outline).toBe('solid');
  });
});

test.describe('manager side pages', () => {
  test('parcels failure shows Retry, not "no routes yet"', async ({ page }) => {
    await openCompanyPage(page, 'company_manager', '/company-manager/parcels', (path) =>
      path === '/api/deliveries/rates/' ? { status: 500, body: {} } : undefined);

    await expect(page.getByRole('alert').filter({ hasText: 'Could not load parcel rates' })).toBeVisible();
    await expect(page.getByText('You have no routes yet.')).toHaveCount(0);
  });

  test('bus hire quote mode toggles expose pressed state', async ({ page }) => {
    await openCompanyPage(page, 'company_manager', '/company-manager/charters', (path) =>
      path === '/api/charters/company/'
        ? { body: [{ id: 1, reference: 'CH1', purpose: 'Trip', status: 'requested', pickup_location: 'A', destination: 'B', passenger_count: 10, contact_name: 'X', contact_phone: '1' }] }
        : undefined);
    await expect(page.getByRole('button', { name: 'Send a quote' })).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByRole('button', { name: 'Decline' })).toHaveAttribute('aria-pressed', 'false');
  });

  test('service templates failure does not claim there are none', async ({ page }) => {
    await openCompanyPage(page, 'company_manager', '/company-manager/services', (path) =>
      path === '/api/companies/17/schedules/' ? { status: 500, body: {} } : undefined);

    await expect(page.getByRole('alert')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible();
    await expect(page.getByText('No weekly service templates yet')).toHaveCount(0);
    await expect(page.getByText('0 service templates')).toHaveCount(0);
  });

  test('route planner failure shows Retry, not "no routes yet"', async ({ page }) => {
    await openCompanyPage(page, 'company_manager', '/company-manager/route-planner', (path) =>
      path === '/api/companies/17/routes/' ? { status: 500, body: {} } : undefined);

    await expect(page.getByRole('alert').filter({ hasText: 'Could not load your routes' })).toBeVisible();
    await expect(page.getByText('You have no routes yet.')).toHaveCount(0);
  });
});
