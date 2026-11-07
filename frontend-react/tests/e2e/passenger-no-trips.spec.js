import { expect, test } from '@playwright/test';

const passenger = { id: 7, username: 'rider', name: 'Rider', role: 'passenger' };

// A route with no trips on the chosen date must never be a dead end.
async function openTrips(page, trips) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    let body = [];
    if (path === '/api/users/csrf/') body = { csrfToken: 'e2e' };
    else if (path === '/api/users/profile/') body = { user: passenger };
    else if (path === '/api/companies/') body = [{ id: 1, name: 'Express Line' }];
    else if (path === '/api/companies/1/routes/') {
      body = [{
        id: 11, name: 'CBD to Rongai', start_point: 'Nairobi CBD', end_point: 'Rongai', price: '80.00',
        pickup_stages: [{ id: 5, name: 'Koja', is_active: true }],
      }];
    } else if (path === '/api/companies/1/trips/') {
      const date = url.searchParams.get('date');
      body = trips.filter((t) => !date || t.departure_at.startsWith(date));
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.addInitScript((user) => localStorage.setItem('user_session', JSON.stringify(user)), passenger);
  await page.goto('/passenger');
  await page.getByRole('button', { name: /Book a seat/ }).click();
  await page.getByRole('button', { name: /Express Line/ }).click();
  await page.getByRole('button', { name: /Rongai/ }).click();
  await page.getByRole('button', { name: /Koja/ }).click();
}

test('no trips today offers the next date that has one', async ({ page }) => {
  const later = new Date(Date.now() + 3 * 864e5);
  const key = new Date(later.getTime() - later.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  await openTrips(page, [{
    id: 22, status: 'scheduled', capacity: 14, departure_at: `${key}T09:00:00+03:00`,
    route_details: { name: 'CBD to Rongai', price: '80.00' },
  }]);
  await expect(page.getByText(/No departures on/)).toBeVisible();
  await page.getByRole('button', { name: /^Show / }).click();
  await expect(page.getByRole('button', { name: /Select trip/ })).toBeVisible();
});

test('a route with no trips at all sends the passenger back to routes', async ({ page }) => {
  await openTrips(page, []);
  await expect(page.getByText('This route has no upcoming departures yet.', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Choose another route' }).click();
  await expect(page).toHaveURL(/step=routes/);
});
