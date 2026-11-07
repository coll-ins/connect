import { expect, test } from '@playwright/test';

// The whole seat journey against the real API: no step may leave the
// passenger without a way forward (pay later, pay, track, cancel).
test('passenger books, pays later from My bookings, then cancels', async ({ page }) => {
  page.on('dialog', (d) => d.accept());

  await page.goto('/login');
  await page.getByLabel('Phone number').fill('+254799000001');
  await page.getByLabel('Password', { exact: true }).fill('demo-pass-123');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/passenger/);

  // Find the seeded route that has the demo stage.
  const companies = await (await page.request.get('/api/companies/')).json();
  let target = null;
  for (const c of companies) {
    const routes = await (await page.request.get(`/api/companies/${c.id}/routes/`)).json();
    const r = routes.find((x) => (x.pickup_stages || []).some((s) => s.name === 'Kencom House'));
    if (r) { target = { company: c.id, route: r.id }; break; }
  }
  expect(target).not.toBeNull();

  await page.goto(`/passenger?step=stages&mode=seat&company=${target.company}&route=${target.route}`);
  await page.getByText('Kencom House').first().click();

  // The seeded scheduled trip leaves 3 hours after seeding, which is
  // tomorrow in Nairobi when the suite runs late in the day: show its date.
  const trips = await (await page.request.get(`/api/companies/${target.company}/trips/`)).json();
  const later = trips.find((t) => t.status === 'scheduled' && t.route === target.route)
    || trips.find((t) => t.status === 'scheduled');
  const day = new Intl.DateTimeFormat('en-CA', { timeZone: 'Africa/Nairobi' }).format(new Date(later.departure_at));
  await page.getByLabel('Departure date').fill(day);

  const scheduled = page.locator('article', { hasText: 'scheduled' }).first();
  await expect(scheduled).toContainText('seats left');
  await scheduled.getByRole('button', { name: 'Select trip' }).click();
  await page.getByRole('button', { name: /Confirm booking/ }).click();

  // Walk away from the payment window: the booking must still be payable.
  await page.getByRole('button', { name: 'Close' }).first().click();
  await page.goto('/passenger/bookings');
  const card = page.locator('.passenger-data-card').first();
  await card.getByRole('button', { name: 'Pay now' }).click();
  await page.getByRole('button', { name: /Pay with cash/ }).click();
  await expect(page).toHaveURL(/\/passenger\/map\?booking=/);
  await expect(page.getByText('Seat reserved · awaiting payment')).toBeVisible();

  // Change of plans: cancel from My bookings frees the seat.
  await page.goto('/passenger/bookings');
  await card.getByRole('button', { name: 'Cancel booking' }).click();
  await expect(card.locator('.passenger-status')).toHaveText(/cancelled/i);
  await expect(card.getByRole('button')).toHaveCount(0);
});
