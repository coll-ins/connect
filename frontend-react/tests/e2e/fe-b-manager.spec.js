import { test, expect } from '@playwright/test';
import { collectPageErrors, openCompanyPage } from './fe-b-helpers.js';

const route = { id: 1, name: 'CBD to Rongai', start_point: 'CBD', end_point: 'Rongai', price: '150.00' };

test.describe('company manager screens', () => {
  test('operators page with an empty array answer renders instead of crashing', async ({ page }) => {
    const errors = collectPageErrors(page);
    await openCompanyPage(page, 'company_manager', '/company-manager/operators');

    await expect(page.getByRole('heading', { level: 1, name: 'Operators' })).toBeVisible();
    await expect(page.getByText('No operators yet')).toBeVisible();
    expect(errors).toEqual([]);
  });

  test('operators page survives operator-routes answering with an object of wrong shapes', async ({ page }) => {
    const errors = collectPageErrors(page);
    await openCompanyPage(page, 'company_manager', '/company-manager/operators', (path) =>
      path === '/api/companies/operator-routes/'
        ? { body: { routes: {}, operators: [{ id: 3, username: 'op3', phone_number: '0711', all_routes: false }] } }
        : undefined);

    await expect(page.getByRole('heading', { level: 1, name: 'Operators' })).toBeVisible();
    await expect(page.getByText('op3')).toBeVisible();
    expect(errors).toEqual([]);
  });

  test('a failed route load shows an error with Retry, never the empty copy', async ({ page }) => {
    // The dev server mounts effects twice, so fail by phase, not by call count.
    let recovered = false;
    await openCompanyPage(page, 'company_manager', '/company-manager/routes', (path) => {
      if (path !== '/api/companies/17/routes/') return undefined;
      return recovered ? { body: [route] } : { status: 500, body: { detail: 'boom' } };
    });

    await expect(page.getByRole('alert').filter({ hasText: 'Could not load' })).toBeVisible();
    await expect(page.getByText('No routes yet')).toHaveCount(0);
    recovered = true;
    await page.getByRole('button', { name: 'Retry' }).click();
    await expect(page.getByText('CBD to Rongai')).toBeVisible();
    await expect(page.getByRole('alert')).toHaveCount(0);
  });

  test('revenue never shows a zero amount while loading or after a failure', async ({ page }) => {
    await openCompanyPage(page, 'company_manager', '/company-manager/revenue', (path) =>
      path === '/api/companies/17/analytics/' ? { status: 500, body: {} } : undefined);

    await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible();
    await expect(page.getByText('KES 0.00')).toHaveCount(0);
  });

  test('overview failure shows Retry instead of zero counts', async ({ page }) => {
    await openCompanyPage(page, 'company_manager', '/company-manager', (path) =>
      path === '/api/companies/17/analytics/' ? { status: 500, body: {} } : undefined);

    await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible();
    await expect(page.getByText('KES 0.00')).toHaveCount(0);
    await expect(page.getByText('Active bookings')).toHaveCount(0);
  });

  test('create route opens a labelled dialog that closes on Escape and returns focus', async ({ page }) => {
    await openCompanyPage(page, 'company_manager', '/company-manager/routes');
    const opener = page.getByRole('button', { name: 'Create Route' });
    await opener.click();

    const dialog = page.getByRole('dialog', { name: 'Create Route' });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Close' })).toBeVisible();
    await expect(dialog.getByLabel('Route name')).toBeFocused();

    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(opener).toBeFocused();
  });

  test('a failed save is announced inside the open dialog', async ({ page }) => {
    await openCompanyPage(page, 'company_manager', '/company-manager/routes', (path, request) =>
      path === '/api/companies/routes/create/' && request.method() === 'POST'
        ? { status: 400, body: { error: 'Route already exists.' } }
        : undefined);
    await page.getByRole('button', { name: 'Create Route' }).click();
    const dialog = page.getByRole('dialog', { name: 'Create Route' });
    await dialog.getByLabel('Route name').fill('X');
    await dialog.getByLabel('Starting point').fill('A');
    await dialog.getByLabel('Destination').fill('B');
    await dialog.getByLabel('Price (KES)').fill('10');
    await dialog.getByRole('button', { name: 'Create Route' }).click();

    await expect(dialog.getByRole('alert')).toContainText('Route already exists.');
  });

  test('icon-only delete buttons have names and the trips filter exposes pressed state', async ({ page }) => {
    await openCompanyPage(page, 'company_manager', '/company-manager/routes', (path) =>
      path === '/api/companies/17/routes/' ? { body: [route] } : undefined);
    await expect(page.getByRole('button', { name: 'Delete CBD to Rongai' })).toBeVisible();

    await page.goto('/company-manager/trips');
    const active = page.getByRole('button', { name: /^Active/ });
    await expect(active).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByRole('button', { name: /^Logs/ })).toHaveAttribute('aria-pressed', 'false');
  });

  test('manager screens have one main landmark', async ({ page }) => {
    await openCompanyPage(page, 'company_manager', '/company-manager/routes');
    await expect(page.getByRole('heading', { level: 1, name: 'Routes' })).toBeVisible();
    await expect(page.getByRole('main')).toHaveCount(1);
  });

  test('every manager page has exactly one h1', async ({ page }) => {
    await openCompanyPage(page, 'company_manager', '/company-manager/routes');
    for (const path of ['routes', 'trips', 'drivers', 'revenue', 'settings']) {
      await page.goto(`/company-manager/${path}`);
      await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
    }
  });

  test('phone width: no horizontal scroll and touch targets are 44px', async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 375, height: 800 }, hasTouch: true, isMobile: true });
    const page = await context.newPage();
    await openCompanyPage(page, 'company_manager', '/company-manager/routes', (path) =>
      path === '/api/companies/17/routes/' ? { body: [route] } : undefined);
    await expect(page.getByText('CBD to Rongai')).toBeVisible();

    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
    const small = await page.evaluate(() =>
      [...document.querySelectorAll('main button, main a, main select, main input')]
        .filter((el) => el.getClientRects().length && el.getBoundingClientRect().height < 44)
        .map((el) => `${el.tagName} ${el.textContent.trim().slice(0, 20)} ${Math.round(el.getBoundingClientRect().height)}`));
    expect(small).toEqual([]);
    await context.close();
  });
});
