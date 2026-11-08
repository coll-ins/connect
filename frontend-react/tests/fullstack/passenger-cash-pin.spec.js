import { expect, test } from '@playwright/test';

// Cash end to end on the real API: choosing cash opens the map with the seat
// held and the boarding PIN already showing, because the fare is paid to the
// driver on boarding. Confirming the cash keeps the same PIN.
test('cash booking opens the map with the boarding PIN before the cash is paid', async ({ page, browser }) => {
  page.on('dialog', (d) => d.accept());

  await page.goto('/login');
  await page.getByLabel('Phone number').fill('+254799000001');
  await page.getByLabel('Password', { exact: true }).fill('demo-pass-123');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/passenger/);

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
  const trips = await (await page.request.get(`/api/companies/${target.company}/trips/`)).json();
  const later = trips.find((t) => t.status === 'scheduled' && t.route === target.route)
    || trips.find((t) => t.status === 'scheduled');
  const day = new Intl.DateTimeFormat('en-CA', { timeZone: 'Africa/Nairobi' }).format(new Date(later.departure_at));
  await page.getByLabel('Departure date').fill(day);

  const scheduled = page.locator('article', { hasText: 'scheduled' }).first();
  await scheduled.getByRole('button', { name: 'Select trip' }).click();
  await page.getByRole('button', { name: /Confirm booking/ }).click();
  await page.getByRole('button', { name: /Pay with cash/ }).click();

  await expect(page).toHaveURL(/\/passenger\/map\?booking=\d+/);
  const bookingId = new URL(page.url()).searchParams.get('booking');
  await expect(page.getByText('Seat reserved · awaiting payment')).toBeVisible();
  const pin = page.locator('.passenger-live-map__guide-pin strong');
  await expect(pin).toHaveText(/^\d{4,8}$/, { timeout: 15000 });
  const issuedPin = await pin.textContent();

  // The company manager takes the cash.
  const staff = await browser.newContext({ baseURL: 'http://127.0.0.1:5174' });
  const login = await staff.request.post('/api/users/login/', {
    data: { phone_number: '+254799000003', password: 'demo-pass-123' },
  });
  expect(login.ok()).toBeTruthy();
  await staff.request.get('/api/users/csrf/');
  const csrf = (await staff.cookies()).find((c) => c.name === 'csrftoken')?.value;
  const confirm = await staff.request.post(`/api/bookings/payments/${bookingId}/cash/confirm/`, {
    headers: { 'X-CSRFToken': csrf, Origin: 'http://127.0.0.1:5174' },
    data: {},
  });
  expect(confirm.ok(), await confirm.text()).toBeTruthy();
  await staff.close();

  await expect(pin).toHaveText(issuedPin);
});
