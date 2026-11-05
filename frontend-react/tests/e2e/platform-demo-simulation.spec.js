import { test, expect } from '@playwright/test';

const admin = {
  id: 1,
  username: 'demo_admin',
  role: 'platform_admin',
  is_staff: true,
  is_superuser: true,
  company_id: null,
};

async function openDemoTrips(page, { advancesToComplete = false } = {}) {
  let simulation = null;
  let advanceCalls = 0;
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    let body = [];
    if (url.pathname === '/api/users/profile/') {
      body = { user: admin };
    } else if (url.pathname === '/api/companies/') {
      body = [{ id: 7, name: 'Demo Company' }];
    } else if (url.pathname === '/api/companies/routes/') {
      body = [{
        id: 22,
        name: 'CBD to Westlands',
        company: 7,
        company_name: 'Demo Company',
      }];
    } else if (url.pathname === '/api/system/demo-simulation/' && method === 'GET') {
      body = {
        simulation,
        available_routes: [{
          id: 22,
          name: 'CBD to Westlands',
          company_name: 'Demo Company',
        }],
      };
    } else if (url.pathname === '/api/system/demo-simulation/' && method === 'POST') {
      simulation = {
        id: 9,
        route_id: 22,
        route_name: 'CBD to Westlands',
        company_name: 'Demo Company',
        start_point: 'CBD',
        end_point: 'Westlands',
        bus_number: 'DEMO BUS',
        path: [[-1.2864, 36.8219], [-1.287, 36.823], [-1.289, 36.825]],
        position_index: 0,
        position: [-1.2864, 36.8219],
        progress: 0,
        status: 'running',
        expires_at: new Date(Date.now() + 600000).toISOString(),
      };
      body = { simulation };
    } else if (url.pathname.endsWith('/advance/')) {
      advanceCalls += 1;
      const positionIndex = Math.min(advanceCalls, simulation.path.length - 1);
      simulation = {
        ...simulation,
        position_index: positionIndex,
        position: simulation.path[positionIndex],
        progress: Math.round(positionIndex / (simulation.path.length - 1) * 100),
        status: advancesToComplete && positionIndex === simulation.path.length - 1
          ? 'completed'
          : 'running',
      };
      body = { simulation };
    } else if (url.pathname.endsWith('/stop/')) {
      simulation = { ...simulation, status: 'stopped' };
      body = { simulation };
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
  });

  await page.addInitScript((user) => {
    localStorage.setItem('user_session', JSON.stringify(user));
  }, admin);
  await page.goto('/platform-admin/trips');
}

test('platform admin starts and can stop an isolated demo trip', async ({ page }) => {
  await openDemoTrips(page);

  const panel = page.getByTestId('demo-simulation-panel');
  await expect(panel.getByRole('heading', { name: 'Client demo simulator' })).toBeVisible();
  await expect(panel.getByText(/without creating or changing real trips/)).toBeVisible();

  await page.getByLabel('Demo route').selectOption('22');
  await panel.getByRole('button', { name: 'Start demo simulation' }).click();

  await expect(panel.getByText('Running', { exact: true })).toBeVisible();
  await expect(panel.locator('.pa-demo-meta > strong')).toHaveText('CBD to Westlands');
  await expect(panel.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '0');
  await expect(panel.getByRole('button', { name: 'Stop simulation' })).toBeVisible();

  await panel.getByRole('button', { name: 'Stop simulation' }).click();
  await expect(panel.getByText('stopped', { exact: true })).toBeVisible();
  await expect(panel.getByText(/No operational trip data was changed/)).toBeVisible();
});

test('platform admin simulation advances to completion', async ({ page }) => {
  await openDemoTrips(page, { advancesToComplete: true });

  const panel = page.getByTestId('demo-simulation-panel');
  await page.getByLabel('Demo route').selectOption('22');
  await panel.getByRole('button', { name: 'Start demo simulation' }).click();

  await expect(panel.getByText('completed', { exact: true })).toBeVisible({ timeout: 10000 });
  await expect(panel.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100');
  await expect(panel.getByText(/Demo trip completed/)).toBeVisible();
});
