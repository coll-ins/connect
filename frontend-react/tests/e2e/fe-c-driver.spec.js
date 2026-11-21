import { test, expect } from '@playwright/test';

const driver = {
  id: 17,
  username: 'driver_e2e',
  name: 'Test Driver',
  role: 'driver',
  company_id: 17,
  company_name: 'Test Company',
};

const json = (route, body, status = 200) => route.fulfill({
  status,
  contentType: 'application/json',
  body: JSON.stringify(body),
});

async function openDriver(page, path, overrides = {}) {
  await page.route('**/api/**', async (route) => {
    const { pathname } = new URL(route.request().url());
    if (pathname === '/api/users/csrf/') return json(route, { csrfToken: 'e2e' });
    if (pathname === '/api/users/profile/') return json(route, { user: driver });
    if (pathname in overrides) {
      const handler = overrides[pathname];
      return typeof handler === 'function' ? handler(route) : json(route, handler);
    }
    if (pathname === '/api/drivers/me/') return json(route, { id: 17, name: 'Test Driver' });
    if (pathname === '/api/drivers/me/timetable/') return json(route, { trips: [] });
    return json(route, []);
  });
  await page.addInitScript((user) => {
    localStorage.setItem('user_session', JSON.stringify(user));
  }, driver);
  await page.goto(path);
}

test.describe('driver timetable states', () => {
  test('an empty timetable says so instead of staying on Loading', async ({ page }) => {
    await openDriver(page, '/driver/trips');
    await expect(page.getByText('No trips are scheduled for you in the next seven days.')).toBeVisible();
    await expect(page.getByText('Loading your timetable')).toHaveCount(0);
  });

  test('a driver profile with no id does not leave the timetable loading forever', async ({ page }) => {
    await openDriver(page, '/driver/trips', { '/api/drivers/me/': [] });
    await expect(page.getByText('No trips are scheduled for you in the next seven days.')).toBeVisible();
    await expect(page.getByRole('alert').filter({ hasText: /driver profile could not be found/ })).toBeVisible();
  });

  test('a failed timetable shows the error with Retry, and Retry recovers', async ({ page }) => {
    let failing = true;
    await openDriver(page, '/driver/trips', {
      '/api/drivers/me/timetable/': (route) => (
        failing ? json(route, { detail: 'boom' }, 500) : json(route, { trips: [] })
      ),
    });
    const alert = page.getByRole('alert').filter({ hasText: /Retry/ });
    await expect(alert.first()).toBeVisible();
    failing = false;
    await alert.getByRole('button', { name: 'Retry' }).first().click();
    await expect(page.getByText('No trips are scheduled for you in the next seven days.')).toBeVisible();
  });

  test('while the timetable request is pending it shows Loading, not the empty text', async ({ page }) => {
    await openDriver(page, '/driver/trips', {
      '/api/drivers/me/timetable/': () => new Promise(() => {}),
    });
    await expect(page.getByRole('status').filter({ hasText: 'Loading your timetable' })).toBeVisible();
    await expect(page.getByText('No trips are scheduled')).toHaveCount(0);
  });
});

test.describe('driver boarding PIN', () => {
  const booking = {
    booking_id: 501,
    booking_number: 'BK-501',
    passenger_name: 'Amina',
    status: 'confirmed',
    payment_status: 'confirmed',
    payment_method: 'mpesa',
    seats: 1,
  };

  test('the PIN dialog is labelled, the field is named, an error is announced, Escape returns focus', async ({ page }) => {
    await openDriver(page, '/driver', {
      '/api/bookings/driver/17/': [booking],
      '/api/bookings/501/verify-boarding/': (route) => json(route, { detail: 'Wrong PIN.' }, 400),
    });

    const opener = page.getByRole('button', { name: 'Verify PIN' });
    await opener.click();

    const dialog = page.getByRole('dialog', { name: 'Board passenger' });
    await expect(dialog).toBeVisible();
    const pin = dialog.getByLabel('Boarding PIN');
    await expect(pin).toBeFocused();

    await pin.fill('1234');
    await dialog.getByRole('button', { name: 'Verify' }).click();
    await expect(dialog.getByRole('alert')).toBeVisible();
    await expect(pin).toHaveAttribute('aria-invalid', 'true');

    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(opener).toBeFocused();
  });

  test('the boarding result is a status with a Dismiss button, not a clickable div', async ({ page }) => {
    await openDriver(page, '/driver', {
      '/api/bookings/driver/17/': [booking],
      '/api/bookings/501/verify-boarding/': (route) => json(route, { ok: true }),
    });
    await page.getByRole('button', { name: 'Verify PIN' }).click();
    const dialog = page.getByRole('dialog', { name: 'Board passenger' });
    await dialog.getByLabel('Boarding PIN').fill('1234');
    await dialog.getByRole('button', { name: 'Verify' }).click();

    const flash = page.locator('[role="alert"], [role="status"]').filter({ hasText: /PIN accepted|boarded/ });
    await expect(flash).toBeVisible();
    const dismiss = flash.getByRole('button', { name: 'Dismiss' });
    const box = await dismiss.boundingBox();
    expect(box.height).toBeGreaterThanOrEqual(44);
    await dismiss.click();
    await expect(flash).toHaveCount(0);
  });
});

test.describe('driver parcels and hires', () => {
  test('a failed parcel load shows an error with Retry, not "No paid parcels waiting"', async ({ page }) => {
    await openDriver(page, '/driver/jobs', {
      '/api/deliveries/driver/': (route) => json(route, { detail: 'boom' }, 500),
    });
    await expect(page.getByRole('alert').filter({ hasText: /Could not load your parcels/ })).toBeVisible();
    await expect(page.getByText('No paid parcels waiting.')).toHaveCount(0);
    await expect(page.getByText('No confirmed hires assigned to you.')).toBeVisible();
  });

  test('the receiver PIN field has a label', async ({ page }) => {
    await openDriver(page, '/driver/jobs', {
      '/api/deliveries/driver/': [{
        id: 9, tracking_code: 'PC-9', description: 'Box', status: 'picked_up', size: 'small',
        pickup_stage: { name: 'A' }, dropoff_stage: { name: 'B' },
        sender_name: 'S', sender_phone: '0700', receiver_name: 'R', receiver_phone: '0711',
        departure_at: null,
      }],
    });
    await expect(page.getByLabel('Receiver PIN')).toBeVisible();
  });
});

test.describe('driver live location', () => {
  test('has a main landmark, and sends fix time and accuracy with each GPS post', async ({ page, context }) => {
    await context.grantPermissions(['geolocation']);
    await context.setGeolocation({ latitude: -1.29, longitude: 36.82, accuracy: 15 });
    const posts = [];
    await openDriver(page, '/driver/location', {
      '/api/drivers/17/location/': (route) => {
        posts.push(route.request().postDataJSON());
        return json(route, { latitude: -1.29, longitude: 36.82 });
      },
    });
    await expect(page.getByRole('main')).toHaveCount(1);
    await expect.poll(() => posts.length).toBeGreaterThan(0);
    expect(typeof posts[0].fix_at).toBe('string');
    expect(Number.isNaN(Date.parse(posts[0].fix_at))).toBe(false);
    expect(posts[0].accuracy).toBe(15);
  });
});

test.describe('driver pages at 375px', () => {
  for (const path of ['/driver', '/driver/trips', '/driver/jobs']) {
    test(`${path} has no sideways scroll`, async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 740 });
      await openDriver(page, path);
      await expect(page.getByRole('main')).toBeVisible();
      const width = await page.evaluate(() => document.documentElement.scrollWidth);
      expect(width).toBeLessThanOrEqual(375);
    });
  }
});
