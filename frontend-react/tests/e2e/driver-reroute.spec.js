import { test, expect } from '@playwright/test';

// Planned route runs east along -1.2864; the bus is ~300 m north of it, on a
// side road the server returns as the new road.
const gps = { latitude: -1.2837, longitude: 36.8230 };
const driver = {
  id: 17,
  username: 'E2E Driver',
  name: 'E2E Driver',
  role: 'driver',
  company_id: 17,
  ...gps,
  location_updated_at: new Date().toISOString(),
};
const newRoad = {
  type: 'LineString',
  coordinates: [
    [36.8200, -1.28385],
    [36.8300, -1.28385],
    [36.8400, -1.2864],
  ],
};

test('off its route, the driver map asks for the real road and draws the bus on it', async ({ page, context }) => {
  test.setTimeout(60000);
  let rerouteCalls = 0;

  await context.grantPermissions(['geolocation']);
  await context.setGeolocation(gps);

  await page.route('**/api/**', async (route) => {
    const { pathname } = new URL(route.request().url());
    const json = (body) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });

    if (pathname === '/api/users/profile/') return json({ user: driver });
    if (pathname === '/api/users/csrf/') return json({ csrfToken: 'e2e' });
    if (pathname === '/api/drivers/me/') return json(driver);
    if (pathname === '/api/bookings/driver/17/reroute/') {
      rerouteCalls += 1;
      return json({ geometry: newRoad, distance_m: 2300, goal: 'destination' });
    }
    if (pathname === '/api/bookings/driver/17/') {
      return json({
        driver,
        active_trip: {
          id: 28,
          status: 'departed',
          route_name: 'Nairobi to Thika',
          route_geometry: {
            type: 'LineString',
            coordinates: [[36.8100, -1.2864], [36.8400, -1.2864]],
          },
          stages: [],
          bookings: [],
        },
        bookings: [],
      });
    }
    if (pathname === '/api/drivers/17/location/') {
      return json({ ...driver, location_updated_at: new Date().toISOString() });
    }
    return json([]);
  });

  await page.addInitScript((user) => {
    localStorage.setItem('user_session', JSON.stringify(user));
  }, driver);
  await page.goto('/driver/location');

  const blueLines = page.locator('.leaflet-overlay-pane path[stroke="#1677ff"]');
  await expect.poll(() => blueLines.count()).toBeGreaterThan(0);
  const before = await blueLines.count();

  await expect.poll(() => rerouteCalls, { timeout: 30000 }).toBeGreaterThan(0);
  await expect.poll(() => blueLines.count(), { timeout: 5000 }).toBe(before + 1);
  await page.screenshot({ path: test.info().outputPath('rerouted.png') });
});
