import { expect, test } from '@playwright/test';

// Platform admin runs the client demo trip on the real API.
test('platform admin runs, follows and stops the demo trip', async ({ page }) => {
  const problems = [];
  page.on('pageerror', (e) => problems.push(e.message));

  await page.goto('/login');
  await page.getByLabel('Phone number').fill('+254799000005');
  await page.getByLabel('Password', { exact: true }).fill('demo-pass-123');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/platform-admin/);

  await page.goto('/platform-admin/trips');
  const panel = page.getByTestId('demo-simulation-panel');
  const route = panel.getByLabel('Demo route');
  await route.selectOption({ index: 1 });
  await panel.locator('.pa-primary-button').click();

  await expect(panel.locator('.bus-icon')).toBeVisible();
  const progress = async () => Number((await panel.getByText(/% complete/).textContent()).match(/\d+/)[0]);
  const first = await progress();
  await expect.poll(progress, { timeout: 15000 }).toBeGreaterThan(first);

  await panel.getByRole('button', { name: 'Show whole route' }).click();
  await expect(panel.getByRole('button', { name: 'Follow bus' })).toBeVisible();

  await panel.getByRole('button', { name: /Stop simulation/ }).click();
  await expect(panel.getByRole('button', { name: /Stop simulation/ })).toHaveCount(0);
  expect(problems).toEqual([]);
});
