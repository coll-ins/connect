import { test, expect } from '@playwright/test';

const userForRole = (role) => ({
  id: 17,
  username: 'trip_oversight_user',
  role,
  company_id: 17,
  company_name: 'Test Company',
});

const trip = {
  id: 84,
  route: 9,
  route_details: {
    name: 'Nairobi to Mombasa',
    start_point: 'Nairobi',
    end_point: 'Mombasa',
  },
  driver_name: 'Alex Driver',
  driver_bus_number: 'KCA 123A',
  departure_at: new Date(Date.now() - 13 * 60 * 60 * 1000).toISOString(),
  capacity: 30,
  status: 'departed',
};

async function openDashboard(page, role, path, tripRecord = trip) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    let body = [];

    if (url.pathname === '/api/users/csrf/') {
      body = { csrfToken: 'e2e-csrf-token' };
    } else if (url.pathname === '/api/users/profile/') {
      body = { user: userForRole(role) };
    } else if (url.pathname === '/api/companies/17/trips/') {
      body = [tripRecord];
    } else if (url.pathname === '/api/companies/17/analytics/') {
      body = { total_trips: 1 };
    } else if (url.pathname === '/api/bookings/all/') {
      body = [{
        id: 33,
        trip_id: tripRecord.id,
        status: 'confirmed',
        driver_name: 'Alex Driver',
        seats: 1,
      }];
    } else if (url.pathname === '/api/bookings/incidents/') {
      body = [{
        id: 7,
        trip: trip.id,
        incident_type: 'breakdown',
        description: 'Replacement tire required.',
        status: 'investigating',
      }];
    } else if (url.pathname === '/api/companies/17/weekly-reports/') {
      body = [{
        id: 5,
        report_type: 'weekly',
        period_start: '2026-10-26',
        period_end: '2026-11-01',
        summary: {
          trips_by_status: [{ status: 'completed', count: 8 }],
          bookings_by_status: [{ status: 'confirmed', count: 21 }],
          payments_by_status: [{ status: 'confirmed', count: 21, amount: '10500.00' }],
          incidents_by_status: [],
          incidents_by_type: [],
          schedule_generation_issues: [],
        },
        email_status: 'skipped',
        email_error: 'Email is not configured; the report remains available in the app.',
      }];
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
  });

  await page.addInitScript((user) => {
    localStorage.setItem('user_session', JSON.stringify(user));
  }, userForRole(role));
  await page.goto(path);
}

test('auditor trip register includes trip, route, driver, bus and departure', async ({ page }) => {
  await openDashboard(page, 'company_auditor', '/company-auditor/trips');

  await expect(page.getByRole('cell', { name: '#84' })).toBeVisible();
  await expect(page.getByRole('cell', { name: 'Nairobi to Mombasa' })).toBeVisible();
  await expect(page.getByRole('cell', { name: 'Alex Driver' })).toBeVisible();
  await expect(page.getByRole('cell', { name: 'KCA 123A' })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'Departure' })).toBeVisible();
  await page.getByRole('searchbox', { name: 'Search auditor trip register' }).fill('KCA 123A');
  await expect(page.getByRole('cell', { name: '#84' })).toBeVisible();
  await page.getByRole('searchbox', { name: 'Search auditor trip register' }).fill('not found');
  await expect(page.getByText('No trips match your search.')).toBeVisible();
});

test('operator sees actionable incident and overdue-trip exceptions', async ({ page }) => {
  await openDashboard(page, 'company_operator', '/company-operator/operations');

  await expect(page.getByRole('heading', { name: 'Exceptions needing intervention' })).toBeVisible();
  await expect(page.getByText('Replacement tire required.')).toBeVisible();
  await expect(page.getByText('Trip #84 needs review')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Service templates' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /Create weekly template|Edit/ })).toHaveCount(0);

  await page.getByRole('button', { name: 'Manage trip' }).first().click();

  await expect(page).toHaveURL(/\/company-operator\/trips$/);
  await expect(page.getByRole('heading', { name: /Nairobi to Mombasa/ })).toBeVisible();
  await expect(page.getByLabel('Operational status')).toHaveValue('departed');
});

test('operator can confirm a boarding bus departure with one action', async ({ page }) => {
  await openDashboard(
    page,
    'company_operator',
    '/company-operator/trips',
    { ...trip, status: 'boarding' },
  );

  await page.getByRole('button', { name: 'Confirm bus departure' }).click();

  await expect(page.getByLabel('Operational status')).toHaveValue('departed');
});

test('manager can review the weekly report and email delivery status', async ({ page }) => {
  await openDashboard(page, 'company_manager', '/company-manager/reports');

  await expect(page.getByRole('heading', { name: 'Weekly reports' })).toBeVisible();
  await expect(page.getByText('completed', { exact: true })).toBeVisible();
  await expect(page.getByText('Email skipped')).toBeVisible();
  await expect(page.getByText(/Email is not configured/)).toBeVisible();
});
