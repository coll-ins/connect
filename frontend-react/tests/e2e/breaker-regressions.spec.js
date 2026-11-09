import { expect, test } from '@playwright/test';

// Holes the red team found; each test failed before its fix.
const u = { id: 7, username: 'p', name: 'Pat Wanjiru', role: 'passenger' };

async function signedIn(page, onApi = () => false) {
  await page.addInitScript((x) => localStorage.setItem('user_session', JSON.stringify(x)), u);
  await page.route('**/api/**', (r) => {
    if (onApi(r)) return undefined;
    const p = new URL(r.request().url()).pathname;
    return r.fulfill({
      json: p === '/api/charters/companies/' ? [{ id: 1, name: 'Express Line' }]
        : p === '/api/users/csrf/' ? { csrfToken: 't' }
          : p === '/api/users/profile/' ? { user: u } : [],
    });
  });
}

test('charter refuses a past departure and keeps answers when the phone goes Back', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signedIn(page);
  await page.goto('/passenger/charter/new');
  await page.getByRole('button', { name: /Express Line/ }).click();
  await page.getByLabel(/trip for/i).fill('Wedding trip');
  await page.getByLabel(/Pickup location/).fill('Kencom, Moi Avenue');
  await page.getByLabel(/Destination/).fill('Naivasha');
  await page.getByRole('button', { name: 'Next' }).click();
  await page.getByLabel('Departure').fill('2020-01-01T10:00');
  await expect(page.getByRole('button', { name: 'Next' })).toBeDisabled();
  await expect(page.getByText(/at least 25 hours from now/)).toBeVisible();

  await page.goBack();
  await expect(page).toHaveURL(/\/passenger\/charter\/new/);
  await expect(page.getByLabel(/Destination/)).toHaveValue('Naivasha');
});

test('a session that ended on the server sends the user to sign in', async ({ page }) => {
  await signedIn(page, (r) => {
    if (!r.request().url().includes('/api/users/delete-account/')) return false;
    r.fulfill({ status: 403, json: { detail: 'Authentication credentials were not provided.' } });
    return true;
  });
  await page.goto('/passenger/profile');
  page.on('dialog', (d) => d.accept());
  await page.getByLabel(/Your password/).fill('whatever-1');
  await page.getByRole('button', { name: 'Delete my account' }).click();
  await expect(page).toHaveURL(/\/login/);
  expect(await page.evaluate(() => localStorage.getItem('user_session'))).toBeNull();
});
