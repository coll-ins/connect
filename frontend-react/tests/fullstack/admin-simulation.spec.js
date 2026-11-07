import { expect, test } from '@playwright/test';

// The platform admin simulates the seeded boarding trip (bus KDA 123A): the
// trip's real driver moves through the same code path as live GPS.
test('platform admin simulates a real trip, the driver moves, then stops it', async ({ page }) => {
  const problems = [];
  page.on('pageerror', (e) => problems.push(e.message));

  await page.goto('/login');
  await page.getByLabel('Phone number').fill('+254799000005');
  await page.getByLabel('Password', { exact: true }).fill('demo-pass-123');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/platform-admin/);

  await page.goto('/platform-admin/trips');
  const row = page.getByRole('row').filter({ hasText: 'Peter Mwangi' });
  await row.getByRole('button', { name: 'Simulate' }).click();

  const status = row.getByRole('status');
  await expect(status).toContainText('Moving');
  const progress = async () => Number((await status.textContent()).match(/(\d+)%/)[1]);
  const first = await progress();
  await expect.poll(progress, { timeout: 20000 }).toBeGreaterThan(first);

  // The real driver record moved: the API reports the live position.
  const position = await page.evaluate(async () => {
    const res = await fetch('/api/system/trip-simulations/active/', { credentials: 'include' });
    return res.json();
  });
  expect(position.simulation?.status).toBe('running');

  // Every other trip waits its turn.
  const other = page.getByRole('row').filter({ hasText: 'Joseph Kiprop' });
  await expect(other.getByRole('button', { name: 'Simulate' })).toBeDisabled();

  await row.getByRole('button', { name: 'Stop' }).click();
  await expect(row.getByRole('button', { name: 'Simulate' })).toBeVisible();
  expect(problems).toEqual([]);
});

// Phone width: the wide trips table scrolls inside its own box, so the page
// itself never slides sideways and the controls can still be reached.
test('admin trips table is usable at phone width', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });

  await page.goto('/login');
  await page.getByLabel('Phone number').fill('+254799000005');
  await page.getByLabel('Password', { exact: true }).fill('demo-pass-123');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/platform-admin/);

  await page.goto('/platform-admin/trips');
  const row = page.getByRole('row').filter({ hasText: 'Peter Mwangi' });
  const simulate = row.getByRole('button', { name: 'Simulate' });
  await expect(simulate).toBeVisible();

  const pageOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(pageOverflow).toBeLessThanOrEqual(0);

  for (const control of [simulate, row.getByRole('combobox')]) {
    await control.scrollIntoViewIfNeeded();
    await expect(control).toBeInViewport();
  }
});
