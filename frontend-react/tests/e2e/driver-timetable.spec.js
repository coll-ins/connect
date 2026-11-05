import { test, expect } from '@playwright/test';

const serviceDateKey = (date) => new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Africa/Nairobi',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
}).format(date);

test('driver sees automatically assigned trips in the daily and seven-day timetable', async ({ page }) => {
  const driver = {
    id: 17,
    username: 'driver_test',
    name: 'Test Driver',
    role: 'driver',
    company_id: 17,
    company_name: 'Test Company',
  };
  const today = serviceDateKey(new Date());
  const tomorrowDate = new Date(`${today}T12:00:00+03:00`);
  tomorrowDate.setDate(tomorrowDate.getDate() + 1);
  const tomorrow = serviceDateKey(tomorrowDate);
  const tomorrowLabel = new Intl.DateTimeFormat('en-KE', {
    timeZone: 'Africa/Nairobi',
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  }).format(new Date(`${tomorrow}T12:00:00+03:00`));
  const trips = [
    {
      id: 101,
      departure_at: `${today}T08:30:00+03:00`,
      status: 'scheduled',
      route_name: 'CBD to Westlands',
      start_point: 'CBD',
      end_point: 'Westlands',
      bus_number: 'KAA 001A',
      capacity: 30,
    },
    {
      id: 102,
      departure_at: `${tomorrow}T09:00:00+03:00`,
      status: 'scheduled',
      route_name: 'CBD to Kasarani',
      start_point: 'CBD',
      end_point: 'Kasarani',
      bus_number: 'KAA 001A',
      capacity: 30,
    },
  ];

  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const body = url.pathname === '/api/users/profile/'
      ? { user: driver }
      : url.pathname === '/api/drivers/me/'
        ? driver
        : url.pathname === '/api/drivers/me/timetable/'
          ? {
            start_date: today,
            end_date: tomorrow,
            trips,
          }
          : url.pathname === '/api/bookings/driver/17/'
            ? { driver, bookings: [] }
            : [];
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
  });

  await page.addInitScript((user) => {
    localStorage.setItem('user_session', JSON.stringify(user));
  }, driver);
  await page.goto('/driver');

  await expect(page.getByRole('heading', { name: "Today's timetable" })).toBeVisible();
  await expect(page.getByText('CBD to Westlands', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'View full timetable' })).toBeVisible();

  await page.getByRole('link', { name: 'My timetable' }).click();
  await expect(page).toHaveURL(/\/driver\/trips$/);
  await expect(page.getByRole('heading', { level: 1, name: 'My timetable' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Today' })).toBeVisible();
  await expect(page.getByRole('heading', { name: tomorrowLabel })).toBeVisible();
  await expect(page.getByText('CBD to Kasarani', { exact: true })).toBeVisible();
});
