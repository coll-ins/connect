import { expect, test } from '@playwright/test';

const userFor = (role) => ({
  id: 7, username: `e2e_${role}`, name: 'Amina Hassan', phone_number: '+254712000111',
  role, company_id: 17, company_name: 'Express Line', is_superuser: false,
});

async function mock(page, role, handler) {
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    const json = (body, status = 200) => route.fulfill({
      status, contentType: 'application/json', body: JSON.stringify(body),
    });
    if (path === '/api/users/csrf/') return json({ csrfToken: 'e2e' });
    if (path === '/api/users/profile/') return json({ user: userFor(role) });
    const body = handler(path, route.request());
    return json(body === undefined ? [] : body);
  });
  await page.addInitScript((u) => localStorage.setItem('user_session', JSON.stringify(u)), userFor(role));
}

const stage = (id, name, order, is_active = true) => ({
  id, name, order, is_active, source: 'manual', latitude: -1.28 - order / 100, longitude: 36.82,
});

test('route planner: a removed stage leaves the map and the stage list', async ({ page }) => {
  let stages = [stage(1, 'Kencom', 1), stage(2, 'Nyayo Stadium', 2), stage(3, 'Bomas', 3, false)];
  await mock(page, 'company_manager', (path, req) => {
    if (path === '/api/companies/17/routes/') {
      return [{ id: 5, name: 'CBD to Rongai', start_point: 'Kencom', end_point: 'Rongai', via_points: [] }];
    }
    if (path === '/api/companies/routes/5/pickup-stages/') return stages;
    if (path === '/api/companies/pickup-stages/2/' && req.method() === 'PATCH') {
      stages = stages.map((s) => (s.id === 2 ? { ...s, is_active: false } : s));
      return { ok: true };
    }
    return undefined;
  });
  await page.goto('/company-manager/route-planner');
  const pins = page.locator('.rp2-pin');
  await expect(pins).toHaveCount(2);
  await expect(page.getByText('Removed stages (1)')).toBeVisible();

  await page.locator('.rp-stage', { hasText: 'Nyayo Stadium' }).getByRole('button', { name: 'Remove' }).click();
  await expect(pins).toHaveCount(1);
  await expect(page.getByText('Removed stages (2)')).toBeVisible();
  await expect(page.locator('.svc-list').first().getByText('Nyayo Stadium')).toHaveCount(0);
});

test('parcels: sender picks from and to, buses of every company come soonest first', async ({ page }) => {
  const soon = new Date(Date.now() + 2 * 3600e3).toISOString();
  const later = new Date(Date.now() + 5 * 3600e3).toISOString();
  await mock(page, 'passenger', (path) => {
    if (path === '/api/deliveries/options/') {
      return [
        { id: 1, name: 'Supermetro', routes: [{ id: 10, name: 'CBD to Rongai', rates: { small: '150.00' },
          stages: [{ id: 101, name: 'Kencom', order: 1 }, { id: 102, name: 'Rongai', order: 2 }],
          trips: [{ id: 900, departure_at: later, bus_number: 'SM 12' }] }] },
        { id: 2, name: 'Latema', routes: [{ id: 20, name: 'CBD to Rongai', rates: { small: '120.00' },
          stages: [{ id: 201, name: 'kencom ', order: 1 }, { id: 202, name: 'Rongai', order: 2 }],
          trips: [{ id: 800, departure_at: soon, bus_number: 'LT 4' }] }] },
      ];
    }
    return undefined;
  });
  await page.goto('/passenger/delivery/new');
  // Same stage spelt two ways is one choice; the last stage is not a pickup.
  await expect(page.locator('.svc-pick', { hasText: /kencom/i })).toHaveCount(1);
  await expect(page.locator('.svc-pick', { hasText: 'Rongai' })).toHaveCount(0);
  await page.locator('.svc-pick', { hasText: /kencom/i }).click();
  await page.locator('.svc-pick', { hasText: 'Rongai' }).click();
  const buses = page.locator('.svc-pick');
  await expect(buses).toHaveCount(2);
  await expect(buses.first()).toContainText('Latema');
  await buses.first().click();
  await expect(page.getByText('How big is the parcel?')).toBeVisible();
  await expect(page.locator('.svc-pick', { hasText: 'Small' })).toContainText('120');
});
