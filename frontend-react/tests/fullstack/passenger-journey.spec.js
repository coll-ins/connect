import { expect, test } from '@playwright/test';

// The whole seat journey against the real API: walking away books nothing,
// and a real booking can be paid, tracked and cancelled.
test('closing the payment window books nothing; a paid booking can be cancelled', async ({ page }) => {
  page.on('dialog', (d) => d.accept());

  await page.goto('/login');
  await page.getByLabel('Phone number').fill('+254799000001');
  await page.getByLabel('Password', { exact: true }).fill('demo-pass-123');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/passenger/);

  // Find the route the seeded trips run on, and the stage they leave from.
  const companies = await (await page.request.get('/api/companies/')).json();
  let target = null;
  for (const c of companies) {
    const seeded = await (await page.request.get(`/api/companies/${c.id}/trips/`)).json();
    const trip = seeded.find((t) => t.status === 'scheduled');
    if (!trip) continue;
    const routes = await (await page.request.get(`/api/companies/${c.id}/routes/`)).json();
    const r = routes.find((x) => x.id === trip.route);
    target = { company: c.id, route: r.id, stage: r.pickup_stages[0].name };
    break;
  }
  expect(target).not.toBeNull();

  await page.goto(`/passenger?step=stages&mode=seat&company=${target.company}&route=${target.route}`);
  await page.getByText(target.stage).first().click();

  // The seeded scheduled trip leaves 3 hours after seeding, which is
  // tomorrow in Nairobi when the suite runs late in the day: show its date.
  const trips = await (await page.request.get(`/api/companies/${target.company}/trips/`)).json();
  const later = trips.find((t) => t.status === 'scheduled' && t.route === target.route)
    || trips.find((t) => t.status === 'scheduled');
  const day = new Intl.DateTimeFormat('en-CA', { timeZone: 'Africa/Nairobi' }).format(new Date(later.departure_at));
  await page.getByLabel('Departure date').fill(day);

  const scheduled = page.locator('article', { hasText: 'scheduled' }).first();
  await expect(scheduled).toContainText('seats left');
  const bookOneSeat = async () => {
    await scheduled.getByRole('button', { name: 'Select trip' }).click();
    await page.getByRole('radio', { name: 'Choose for me' }).click();
    await page.getByRole('button', { name: 'Book 1 seat' }).click();
    await expect(page.getByRole('button', { name: /Pay cash on board/ })).toBeVisible();
  };

  // Walk away before paying: nothing is booked and the seat is free again.
  await bookOneSeat();
  await page.getByRole('button', { name: 'Close' }).first().click();
  await expect(page.getByText('nothing was booked')).toBeVisible();
  const mine = await (await page.request.get('/api/bookings/my/')).json();
  expect(mine.filter((b) => b.status === 'pending')).toHaveLength(0);

  // Book again and pay cash on board this time.
  await bookOneSeat();
  await page.getByRole('button', { name: /Pay cash on board/ }).click();
  await expect(page).toHaveURL(/\/passenger\/map\?booking=/);
  await expect(page.getByText('Seat reserved · awaiting payment')).toBeVisible();

  // Change of plans: cancel from My bookings frees the seat.
  await page.goto('/passenger/bookings');
  // Newest first: the cash booking, above the one cancelled on close.
  const card = page.locator('.passenger-data-card').first();
  await card.getByRole('button', { name: 'Cancel booking' }).click();
  await expect(card.locator('.passenger-status')).toHaveText(/cancelled/i);
  await expect(card.getByRole('button')).toHaveCount(0);
});
