import { test, expect } from '@playwright/test';
import { collectPageErrors, openCompanyPage } from './fe-b-helpers.js';

const WALLET = '/api/wallet/';
const TOPUP = '/api/wallet/topup/';
const TX = '/api/wallet/transactions/';
const PAYSTACK = 'https://checkout.paystack.test/pay/abc';

const open = (page, path, handler) => openCompanyPage(page, 'passenger', path, handler);
const bal = (v) => ({ body: { available_balance: v, held_balance: '0.00' } });
const err = (status, code, extra = {}) => ({ status, body: { code, error: 'server text', ...extra } });
const count = (calls, line) => calls.filter((c) => c === line).length;

test.describe('wallet page', () => {
  test('shows the balance, honest copy and no held balance', async ({ page }) => {
    const errors = collectPageErrors(page);
    await open(page, '/passenger/wallet', (path) => (path === WALLET ? bal('1250.50') : undefined));
    await expect(page.getByText('KES 1,250.50')).toBeVisible();
    await expect(page.getByText('Held balance')).toHaveCount(0);
    await expect(page.getByText('Available for new bookings.')).toHaveCount(0);
    await expect(page.getByText('Protected payments')).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test('a failed balance load shows Retry and never a fake KES 0.00', async ({ page }) => {
    await open(page, '/passenger/wallet', (path) => (path === WALLET ? { status: 500, body: {} } : undefined));
    await expect(page.getByRole('alert').filter({ hasText: 'Could not load your wallet' })).toBeVisible();
    await expect(page.getByText('KES 0.00')).toHaveCount(0);
  });
});

test.describe('top-up', () => {
  test('a valid amount posts it and redirects to the Paystack page', async ({ page }) => {
    await page.route('https://checkout.paystack.test/**', (route) => route.fulfill({ contentType: 'text/html', body: '<h1>Paystack</h1>' }));
    let body = null;
    await open(page, '/passenger/wallet', (path, request) => {
      if (path === TOPUP && request.method() === 'POST') {
        body = request.postDataJSON();
        return { status: 201, body: { reference: 'TOPUP-1', authorization_url: PAYSTACK, amount: '500.00', status: 'pending' } };
      }
      return path === WALLET ? bal('0.00') : undefined;
    });
    await page.getByLabel('Amount (KES)').fill('500');
    await page.getByRole('button', { name: 'Top up' }).click();
    await page.waitForURL(PAYSTACK);
    expect(body).toEqual({ amount: '500' });
  });

  test('a double click sends one request', async ({ page }) => {
    await page.route('https://checkout.paystack.test/**', (route) => route.fulfill({ contentType: 'text/html', body: '<h1>Paystack</h1>' }));
    await open(page, '/passenger/wallet', (path) => (path === WALLET ? bal('0.00') : undefined));
    // Later routes win: hold the answer briefly so both clicks land while it is in flight.
    let posts = 0;
    await page.route('**/api/wallet/topup/', async (route) => {
      posts += 1;
      await new Promise((resolve) => { setTimeout(resolve, 400); });
      await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ reference: 'TOPUP-1', authorization_url: PAYSTACK, amount: '500.00', status: 'pending' }) });
    });
    await page.getByLabel('Amount (KES)').fill('500');
    await page.getByRole('button', { name: 'Top up' }).dblclick();
    await page.waitForURL(PAYSTACK);
    expect(posts).toBe(1);
  });

  test('an invalid amount is caught before any request and focuses the field', async ({ page }) => {
    const calls = await open(page, '/passenger/wallet', (path) => (path === WALLET ? bal('0.00') : undefined));
    const input = page.getByLabel('Amount (KES)');
    await input.fill('10.999');
    await page.getByRole('button', { name: 'Top up' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'at most 2 decimals' })).toBeVisible();
    await expect(input).toBeFocused();
    await expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(count(calls, 'POST /api/wallet/topup/')).toBe(0);
  });

  test('server limits show the numbers the server sent', async ({ page }) => {
    await open(page, '/passenger/wallet', (path, request) => {
      if (path === TOPUP && request.method() === 'POST') return err(400, 'amount_too_small', { min: '50' });
      return path === WALLET ? bal('0.00') : undefined;
    });
    await page.getByLabel('Amount (KES)').fill('10');
    await page.getByRole('button', { name: 'Top up' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'The minimum top-up is KES 50.00.' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Top up' })).toBeEnabled();
  });

  test('top-up switched off is calm information, not an error', async ({ page }) => {
    await open(page, '/passenger/wallet', (path, request) => {
      if (path === TOPUP && request.method() === 'POST') return err(503, 'topup_disabled');
      return path === WALLET ? bal('0.00') : undefined;
    });
    await page.getByLabel('Amount (KES)').fill('500');
    await page.getByRole('button', { name: 'Top up' }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Top-up is not available yet.' })).toBeVisible();
    await expect(page.getByText('Something went wrong on our end')).toHaveCount(0);
  });

  test('a gateway error says nothing was charged and allows another try', async ({ page }) => {
    await open(page, '/passenger/wallet', (path, request) => {
      if (path === TOPUP && request.method() === 'POST') return err(502, 'gateway_error');
      return path === WALLET ? bal('0.00') : undefined;
    });
    await page.getByLabel('Amount (KES)').fill('500');
    await page.getByRole('button', { name: 'Top up' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'You were not charged' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Top up' })).toBeEnabled();
  });
});

test.describe('return from Paystack', () => {
  const statusHandler = (answer) => (path) => {
    if (path === `${TOPUP}TOPUP-1/`) return answer();
    if (path === WALLET) return bal('0.00');
    return undefined;
  };
  const row = (status, extra = {}) => ({ body: { reference: 'TOPUP-1', status, amount: '500.00', amount_paid: null, created_at: '2026-11-20T10:00:00Z', credited_at: null, available_balance: '0.00', ...extra } });

  test('polls while pending, then shows the credit and the new balance', async ({ page }) => {
    await page.clock.install();
    let polls = 0;
    let credited = false;
    const calls = await open(page, '/passenger/wallet?reference=TOPUP-1&trxref=TOPUP-1', (path) => {
      if (path === `${TOPUP}TOPUP-1/`) {
        polls += 1;
        // The first mount runs its effect twice (StrictMode), so count 3 is the first scheduled poll.
        if (polls < 3) return row('pending');
        credited = true;
        return row('credited', { amount_paid: '500.00', available_balance: '500.00' });
      }
      if (path === WALLET) return bal(credited ? '500.00' : '0.00');
      return undefined;
    });
    await expect(page.getByRole('heading', { name: 'Checking your top-up' })).toBeVisible();
    await expect.poll(() => polls).toBeGreaterThanOrEqual(2);
    await page.clock.fastForward(5000);
    await expect(page.getByRole('heading', { name: 'Top-up received' })).toBeVisible();
    await expect(page.getByText('KES 500.00 was added to your wallet.')).toBeVisible();
    await expect(page.locator('.wallet-glass-card strong')).toHaveText('KES 500.00');
    const settled = polls;
    await page.clock.fastForward(20000);
    expect(polls).toBe(settled);
    expect(calls.some((c) => c.startsWith('GET /api/wallet/topup/TOPUP-1/'))).toBe(true);
  });

  test('review status uses the checking-your-payment copy and stops', async ({ page }) => {
    await page.clock.install();
    let polls = 0;
    await open(page, '/passenger/wallet?reference=TOPUP-1', statusHandler(() => { polls += 1; return row('review'); }));
    await expect(page.getByText('We received your payment and are checking it.')).toBeVisible();
    await page.clock.fastForward(20000);
    expect(polls).toBeLessThanOrEqual(2);
  });

  test('expired status explains that a charge will still be credited', async ({ page }) => {
    await open(page, '/passenger/wallet?reference=TOPUP-1', statusHandler(() => row('expired')));
    await expect(page.getByText('This top-up expired; if you were charged it will be credited.')).toBeVisible();
  });

  test('an unknown reference stops with a clear message and Dismiss clears the URL', async ({ page }) => {
    await open(page, '/passenger/wallet?reference=NOPE', (path) => {
      if (path === `${TOPUP}NOPE/`) return { status: 404, body: { code: 'not_found' } };
      return path === WALLET ? bal('0.00') : undefined;
    });
    await expect(page.getByText('We could not find this top-up on your account.')).toBeVisible();
    await page.getByRole('button', { name: 'Dismiss' }).click();
    await expect(page).toHaveURL(/\/passenger\/wallet$/);
  });

  test('a network failure offers Check again', async ({ page }) => {
    let fail = true;
    await open(page, '/passenger/wallet?reference=TOPUP-1', statusHandler(() => (fail ? { status: 400, body: {} } : row('credited'))));
    await expect(page.getByRole('heading', { name: 'Could not check this top-up' })).toBeVisible();
    fail = false;
    await page.getByRole('button', { name: 'Check again' }).click();
    await expect(page.getByRole('heading', { name: 'Top-up received' })).toBeVisible();
  });
});

test.describe('history', () => {
  const rows = [
    { id: 3, type: 'refund', amount: '400.00', balance_after: '600.00', reference: 'refund:9', booking: 5, created_at: '2026-11-20T12:00:00Z' },
    { id: 2, type: 'spend', amount: '-800.00', balance_after: '200.00', reference: 'spend:5', booking: 5, created_at: '2026-11-20T11:00:00Z' },
    { id: 1, type: 'deposit', amount: '1000.00', balance_after: '1000.00', reference: 'TOPUP-1', booking: null, created_at: '2026-11-20T10:00:00Z' },
  ];

  test('lists credits and debits with signs and words, newest first', async ({ page }) => {
    await open(page, '/passenger/wallet', (path) => (path === TX ? { body: rows } : path === WALLET ? bal('600.00') : undefined));
    const items = page.getByRole('list').locator('li');
    await expect(items).toHaveCount(3);
    await expect(items.nth(0)).toContainText('Refund');
    await expect(items.nth(0)).toContainText('+KES 400.00');
    await expect(items.nth(0)).toContainText('Credit of KES 400.00');
    await expect(items.nth(1)).toContainText('Booking payment');
    await expect(items.nth(1)).toContainText('-KES 800.00');
    await expect(items.nth(1)).toContainText('Debit of KES 800.00');
    await expect(items.nth(2)).toContainText('Top-up');
    await expect(items.nth(1)).toContainText('Balance KES 200.00');
  });

  test('empty history says what shows up here', async ({ page }) => {
    await open(page, '/passenger/wallet', (path) => (path === WALLET ? bal('0.00') : undefined));
    await expect(page.getByText('No wallet activity yet.')).toBeVisible();
  });

  test('a failed history load shows Retry and keeps the balance', async ({ page }) => {
    let failing = true;
    await open(page, '/passenger/wallet', (path) => {
      if (path === TX) return failing ? { status: 500, body: {} } : { body: rows };
      return path === WALLET ? bal('600.00') : undefined;
    });
    await expect(page.getByRole('alert').filter({ hasText: 'Could not load your wallet history' })).toBeVisible();
    await expect(page.locator('.wallet-glass-card strong')).toHaveText('KES 600.00');
    failing = false;
    await page.getByRole('button', { name: 'Retry' }).click();
    await expect(page.getByRole('list').locator('li')).toHaveCount(3);
  });

  test('does not scroll sideways at 375px with a very long reference', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    const long = { ...rows[0], reference: `refund:${'9'.repeat(80)}` };
    await open(page, '/passenger/wallet', (path) => (path === TX ? { body: [long, ...rows] } : path === WALLET ? bal('600.00') : undefined));
    await expect(page.getByRole('list').locator('li')).toHaveCount(4);
    const width = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(width).toBeLessThanOrEqual(375);
  });
});

test.describe('pay from wallet', () => {
  const booking = {
    booking_id: 42, booking_number: 'CN-0042', status: 'pending', payment_status: 'pending',
    trip_status: 'scheduled', total_amount: '800.00', route_name: 'CBD to Rongai',
  };
  const PAY = '/api/bookings/payments/42/wallet/';
  const base = (balance, payAnswer) => (path, request) => {
    if (path === '/api/bookings/my/') return { body: [booking] };
    if (path === WALLET) return bal(balance());
    if (path === PAY && request.method() === 'POST') return payAnswer();
    return undefined;
  };
  const dialog = (page) => page.getByRole('dialog');

  test('enough balance pays, sends no amount and goes to the trip map', async ({ page }) => {
    let sent = 'unset';
    const calls = await open(page, '/passenger?pay=42', base(() => '1000.00', () => ({
      body: { message: 'ok', booking_id: 42, payment_id: 7, amount: '800.00', method: 'wallet', status: 'confirmed', booking_status: 'confirmed', balance: '200.00', replayed: false },
    })));
    await expect(dialog(page).getByText('Balance: KES 1,000.00')).toBeVisible();
    const pay = dialog(page).getByRole('button', { name: /Pay from wallet/ });
    await expect(pay).toBeEnabled();
    page.on('request', (r) => { if (r.url().endsWith('/wallet/') && r.method() === 'POST') sent = r.postData(); });
    await pay.click();
    await page.waitForURL(/\/passenger\/map\?booking=42$/);
    expect(count(calls, `POST ${PAY}`)).toBe(1);
    expect(sent).toBeNull();
  });

  test('a short balance disables it, says why and links to Top up', async ({ page }) => {
    await open(page, '/passenger?pay=42', base(() => '100.00', () => ({ body: {} })));
    const pay = dialog(page).getByRole('button', { name: /Pay from wallet/ });
    await expect(pay).toBeDisabled();
    await expect(dialog(page).getByText('Your wallet has KES 100.00 but this booking costs KES 800.00.')).toBeVisible();
    await expect(dialog(page).getByRole('link', { name: 'Top up' })).toHaveAttribute('href', '/passenger/wallet');
    await expect(pay).toHaveAccessibleDescription(/KES 100\.00/);
  });

  test('an unloadable balance is disabled with Retry, never KES 0.00', async ({ page }) => {
    await open(page, '/passenger?pay=42', (path) => {
      if (path === '/api/bookings/my/') return { body: [booking] };
      if (path === WALLET) return { status: 500, body: {} };
      return undefined;
    });
    await expect(dialog(page).getByText('We could not load your wallet balance.')).toBeVisible();
    await expect(dialog(page).getByRole('button', { name: /Pay from wallet/ })).toBeDisabled();
    await expect(dialog(page).getByText('Balance: --')).toBeVisible();
    await expect(dialog(page).getByRole('button', { name: 'Retry' })).toBeVisible();
  });

  test('a double click sends one payment', async ({ page }) => {
    await open(page, '/passenger?pay=42', base(() => '1000.00', () => ({ body: {} })));
    let posts = 0;
    await page.route(`**${PAY}`, async (route) => {
      posts += 1;
      await new Promise((resolve) => { setTimeout(resolve, 400); });
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ booking_id: 42, status: 'confirmed', booking_status: 'confirmed', balance: '200.00' }) });
    });
    const pay = dialog(page).getByRole('button', { name: /Pay from wallet/ });
    await expect(pay).toBeEnabled();
    await pay.dblclick();
    await page.waitForURL(/\/passenger\/map\?booking=42$/);
    expect(posts).toBe(1);
  });

  test('the button is disabled while the request is pending', async ({ page }) => {
    await open(page, '/passenger?pay=42', base(() => '1000.00', () => ({ body: {} })));
    let release;
    const gate = new Promise((resolve) => { release = resolve; });
    await page.route(`**${PAY}`, async (route) => {
      await gate;
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ booking_status: 'confirmed' }) });
    });
    const pay = dialog(page).getByRole('button', { name: /Pay from wallet/ });
    await expect(pay).toBeEnabled();
    await pay.click();
    await expect(pay).toBeDisabled();
    await expect(dialog(page).getByRole('button', { name: /Pay with cash/ })).toBeDisabled();
    release();
    await page.waitForURL(/\/passenger\/map\?booking=42$/);
  });

  test('409 already_paid says nothing was taken and reloads the booking', async ({ page }) => {
    const calls = await open(page, '/passenger?pay=42', base(() => '1000.00', () => err(409, 'already_paid')));
    await expect(dialog(page).getByRole('button', { name: /Pay from wallet/ })).toBeEnabled();
    const before = count(calls, 'GET /api/bookings/my/');
    await dialog(page).getByRole('button', { name: /Pay from wallet/ }).click();
    await expect(dialog(page).getByText('This booking is already paid. Nothing was taken from your wallet.')).toBeVisible();
    await expect(dialog(page).getByRole('button', { name: /Pay from wallet/ })).toHaveCount(0);
    await expect.poll(() => count(calls, 'GET /api/bookings/my/')).toBeGreaterThan(before);
  });

  test('409 hold_expired explains the window closed', async ({ page }) => {
    await open(page, '/passenger?pay=42', base(() => '1000.00', () => err(409, 'hold_expired')));
    await dialog(page).getByRole('button', { name: /Pay from wallet/ }).click();
    await expect(dialog(page).getByText('The payment window for this seat closed. Nothing was taken from your wallet.')).toBeVisible();
  });

  test('400 insufficient_funds shows both numbers and reloads the balance', async ({ page }) => {
    let balance = '1000.00';
    const calls = await open(page, '/passenger?pay=42', base(() => balance, () => {
      balance = '300.00';
      return err(400, 'insufficient_funds', { balance: '300.00', required: '800.00' });
    }));
    await dialog(page).getByRole('button', { name: /Pay from wallet/ }).click();
    await expect(dialog(page).getByText('Your wallet has KES 300.00 but this booking costs KES 800.00. Top up first.')).toBeVisible();
    await expect(dialog(page).getByRole('button', { name: /Pay from wallet/ })).toBeDisabled();
    expect(count(calls, 'GET /api/wallet/')).toBeGreaterThanOrEqual(2);
  });

  test('a server failure says you will not be charged twice and allows a retry', async ({ page }) => {
    await open(page, '/passenger?pay=42', base(() => '1000.00', () => ({ status: 500, body: {} })));
    await dialog(page).getByRole('button', { name: /Pay from wallet/ }).click();
    await expect(dialog(page).getByText('You will not be charged twice.')).toBeVisible();
    await expect(dialog(page).getByRole('button', { name: /Pay from wallet/ })).toBeEnabled();
  });

  test('the cash and online options are still on the first step', async ({ page }) => {
    await open(page, '/passenger?pay=42', base(() => '1000.00', () => ({ body: {} })));
    await expect(dialog(page).getByRole('button', { name: /Pay with cash/ })).toBeVisible();
    await expect(dialog(page).getByRole('button', { name: /Pay online/ })).toBeVisible();
  });
});

test.describe('cancel a wallet-paid booking', () => {
  const paid = (method) => ({
    booking_id: 8, booking_number: 'CN-0008', status: 'confirmed', payment_status: 'confirmed',
    payment_method: method, trip_status: 'scheduled', total_amount: '800.00', route_name: 'CBD to Rongai',
  });

  test('wallet booking: the confirmation says the refund lands in the wallet at once', async ({ page }) => {
    let message = '';
    page.on('dialog', async (d) => { message = d.message(); await d.dismiss(); });
    await open(page, '/passenger/bookings', (path) => (path === '/api/bookings/my/' ? { body: [paid('wallet')] } : undefined));
    await page.getByRole('button', { name: 'Cancel booking' }).click();
    await expect.poll(() => message).toBe('Cancel this booking? 50% of the fare goes back to your CONNECT wallet at once.');
  });

  test('card booking keeps the old copy', async ({ page }) => {
    let message = '';
    page.on('dialog', async (d) => { message = d.message(); await d.dismiss(); });
    await open(page, '/passenger/bookings', (path) => (path === '/api/bookings/my/' ? { body: [paid('digital')] } : undefined));
    await page.getByRole('button', { name: 'Cancel booking' }).click();
    await expect.poll(() => message).toBe('Cancel this booking? You will be refunded 50% of the fare.');
  });
});
