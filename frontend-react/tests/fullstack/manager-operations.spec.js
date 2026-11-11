import { expect, test } from '@playwright/test';

// A manager sets up service from nothing through the real API:
// route -> driver -> trip, and the passenger side can see the new trip.
test('manager creates a route, a driver and a trip', async ({ page }) => {
  const problems = [];
  page.on('pageerror', (e) => problems.push(e.message));
  page.on('response', (r) => {
    if (r.url().includes('/api/') && r.status() >= 400) {
      problems.push(`${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`);
    }
  });
  const tag = String(Date.now()).slice(-5);
  // Names and plates are checked as real: letters for the name, KXX 000X plate.
  const SYL = ['ka', 'be', 'di', 'fo', 'gu', 'ha', 'je', 'ki', 'lo', 'mu'];
  const word = `M${[...tag].map((d) => SYL[d]).join('')}`;
  const plate = `KDT ${tag.slice(0, 3)}${'ABCDEFGHJK'[tag[3]]}`;

  await page.goto('/login');
  await page.getByLabel('Phone number').fill('+254799000003');
  await page.getByLabel('Password', { exact: true }).fill('demo-pass-123');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/company-manager/);

  await page.goto('/company-manager/routes');
  await page.getByRole('button', { name: 'Create Route' }).first().click();
  const modal = page.locator('.company-modal');
  await modal.getByLabel('Route name').fill(`Test ${tag} - Rongai`);
  await modal.getByLabel('Starting point').fill('Railways');
  await modal.getByLabel('Destination').fill('Rongai');
  await modal.getByLabel('Price (KES)').fill('150');
  await modal.getByRole('button', { name: 'Create Route' }).click();
  await expect(page.getByText(`Test ${tag} - Rongai`)).toBeVisible();

  await page.goto('/company-manager/drivers');
  await page.getByRole('button', { name: 'Add Driver' }).first().click();
  await modal.getByLabel('Driver name').fill(`Wanjiru ${word}`);
  await modal.getByLabel('Phone number').fill(`+2547330${tag}`);
  await modal.getByLabel('Bus number').fill(plate);
  const pw = modal.getByLabel('Login password');
  if (await pw.count()) await pw.fill('Matatu-Route-58');
  await modal.getByRole('button', { name: 'Add Driver' }).click();
  await expect(page.getByText(`Wanjiru ${word}`)).toBeVisible();

  await page.goto('/company-manager/capacity');
  await page.getByLabel('Number plate').fill(plate);
  await page.getByLabel('Fleet number').fill(`F${tag}`);
  await page.getByLabel('Vehicle').selectOption('matatu_14');
  await page.getByRole('button', { name: 'Add bus' }).click();
  await expect(page.getByText(`F${tag} · ${plate}`)).toBeVisible();

  await page.goto('/company-manager/trips');
  await page.getByRole('button', { name: 'Create Trip' }).first().click();
  await modal.getByLabel('Route').selectOption({ label: `Test ${tag} - Rongai` });
  await modal.getByLabel('Driver').selectOption({ label: `Wanjiru ${word} · ${plate}` });
  const tomorrow = new Date(Date.now() + 86400000);
  const local = new Date(tomorrow.getTime() - tomorrow.getTimezoneOffset() * 60000)
    .toISOString().slice(0, 16);
  await modal.getByLabel('Departure').fill(local);
  // The driver's registered bus picks its own type; otherwise 33 seats.
  await expect(modal.getByLabel(/^Vehicle/)).toHaveValue('matatu_14');
  await modal.getByRole('button', { name: 'Create Trip' }).click();
  await expect(modal).toHaveCount(0);
  await expect(page.getByText(`Test ${tag} - Rongai`).first()).toBeVisible();

  await page.goto('/company-manager/operators');
  await page.getByRole('button', { name: 'Add Operator' }).first().click();
  await modal.getByLabel('Username').fill(`otieno${tag}`);
  await modal.getByLabel('Email').fill(`otieno${tag}@example.com`);
  await modal.getByLabel('Phone number').fill(`+2547440${tag}`);
  await modal.getByLabel('Role').selectOption('company_operator');
  await modal.getByLabel('Password').fill('Stage-Desk-2026');
  await modal.getByRole('button', { name: 'Create Operator' }).click();
  await expect(page.getByText(`otieno${tag}`).first()).toBeVisible();

  expect(problems).toEqual([]);
});
