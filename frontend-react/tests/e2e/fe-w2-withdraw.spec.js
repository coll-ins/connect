import { test, expect } from '@playwright/test';
import { collectPageErrors, openCompanyPage } from './fe-b-helpers.js';

const WALLET = '/api/wallet/';
const WITHDRAW = '/api/wallet/withdraw/';
const LIST = '/api/wallet/withdrawals/';

const open = (page, handler) => openCompanyPage(page, 'passenger', '/passenger/wallet', handler);
const bal = (v) => ({ body: { available_balance: v, held_balance: '0.00' } });
const err = (status, code, extra = {}) => ({ status, body: { code, error: 'server text', ...extra } });
const payout = (over = {}) => ({
  payout_id: 7, status: 'submitted', amount: '500.00', destination_masked: '2547****678', created_at: '2026-11-20T10:00:00Z', ...over,
});
const count = (calls, line) => calls.filter((c) => c === line).length;

// Handler factory: wallet balance, a withdraw answer, a list answer.
const mock = ({ balance = '1000.00', onPost, list = { results: [], next_cursor: null }, bodies = [] } = {}) => (path, request, url) => {
  if (path === WALLET) return bal(balance);
  if (path === LIST) return typeof list === 'function' ? list(url) : { body: list };
  if (path === WITHDRAW && request.method() === 'POST') {
    bodies.push(request.postDataJSON());
    return onPost ? onPost(bodies.length) : { status: 201, body: payout() };
  }
  return undefined;
};

const AMOUNT = 'How much to withdraw (KES)';
const PASSWORD = 'Account password';
async function review(page, amount = '500', password = 'pw-secret-1') {
  if (amount !== null) await page.getByLabel(AMOUNT).fill(amount);
  if (password !== null) await page.getByLabel(PASSWORD).fill(password);
  await page.getByRole('button', { name: 'Review withdrawal' }).click();
}
const confirm = (page) => page.getByRole('dialog').getByRole('button', { name: 'Confirm withdrawal' }).click();
async function send(page, amount, password) {
  await review(page, amount, password);
  await confirm(page);
}

test.describe('withdraw: success paths', () => {
  test('confirm step shows the amount, posts exactly amount, key and password, and shows the result', async ({ page }) => {
    const errors = collectPageErrors(page);
    const bodies = [];
    const calls = await open(page, mock({ bodies }));
    await review(page);
    const dialog = page.getByRole('dialog');
    await expect(dialog).toContainText('KES 500.00');
    await expect(dialog).toContainText('Sent to your registered M-PESA number');
    expect(bodies).toEqual([]);
    await confirm(page);
    await expect(page.getByRole('status').filter({ hasText: 'In progress' })).toBeVisible();
    await expect(page.getByText('2547****678').first()).toBeVisible();
    expect(Object.keys(bodies[0]).sort()).toEqual(['amount', 'idempotency_key', 'password']);
    expect(bodies[0].amount).toBe('500');
    expect(bodies[0].password).toBe('pw-secret-1');
    expect(bodies[0].idempotency_key).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
    expect(count(calls, 'POST /api/wallet/withdraw/')).toBe(1);
    expect(errors).toEqual([]);
  });

  test('balance and history refresh after a request', async ({ page }) => {
    const calls = await open(page, mock());
    const before = { wallet: count(calls, 'GET /api/wallet/'), list: calls.filter((c) => c.startsWith('GET /api/wallet/withdrawals/')).length };
    await send(page);
    await expect(page.getByRole('status').filter({ hasText: 'In progress' })).toBeVisible();
    await expect.poll(() => count(calls, 'GET /api/wallet/')).toBeGreaterThan(before.wallet);
    await expect.poll(() => calls.filter((c) => c.startsWith('GET /api/wallet/withdrawals/')).length).toBeGreaterThan(before.list);
  });

  test('a replay (200) shows the same payout without a second one', async ({ page }) => {
    await open(page, mock({ onPost: () => ({ status: 200, body: payout({ status: 'paid' }) }) }));
    await send(page);
    await expect(page.getByRole('status').filter({ hasText: 'Sent' })).toBeVisible();
  });

  test('failed says the money is back in the wallet', async ({ page }) => {
    await open(page, mock({ onPost: () => ({ status: 201, body: payout({ status: 'failed' }) }) }));
    await send(page);
    await expect(page.getByRole('status').filter({ hasText: 'returned to your wallet' })).toBeVisible();
  });

  test('review says the money is safe', async ({ page }) => {
    await open(page, mock({ onPost: () => ({ status: 201, body: payout({ status: 'review' }) }) }));
    await send(page);
    await expect(page.getByRole('status').filter({ hasText: 'your money is safe' })).toBeVisible();
  });
});

test.describe('withdraw: errors', () => {
  const cases = [
    ['wrong password', err(403, 'wrong_password'), 'That password is not correct', PASSWORD],
    ['lockout', err(429, 'too_many_attempts'), '15 minutes', null],
    ['hourly throttle', { status: 429, body: { detail: 'Request was throttled.' } }, 'Too many withdrawal requests', null],
    ['daily limit', err(400, 'daily_limit', { limit: '50000', remaining: '12000' }), 'KES 12,000.00', AMOUNT],
    ['insufficient funds', err(400, 'insufficient_funds'), 'does not have enough', AMOUNT],
    ['minimum', err(400, 'amount_too_small', { min: '50' }), 'The minimum withdrawal is KES 50.00', AMOUNT],
    ['maximum', err(400, 'amount_too_large', { max: '20000' }), 'The maximum withdrawal is KES 20,000.00', AMOUNT],
    ['invalid phone', err(400, 'invalid_phone'), 'cannot receive M-PESA', null],
    ['in flight', err(409, 'payout_in_flight'), 'already have a withdrawal in progress', null],
  ];
  for (const [name, answer, text, field] of cases) {
    test(`${name}: plain copy in an alert, never the server text`, async ({ page }) => {
      await open(page, mock({ onPost: () => answer }));
      await send(page);
      const alert = page.getByRole(name === 'in flight' ? 'status' : 'alert').filter({ hasText: text });
      await expect(alert).toBeVisible();
      await expect(page.getByText('server text')).toHaveCount(0);
      await expect(page.getByRole('dialog')).toHaveCount(0);
      if (field) {
        const input = page.getByLabel(field);
        await expect(input).toHaveAttribute('aria-invalid', 'true');
        await expect(input).toBeFocused();
        await expect(input).toHaveAttribute('aria-describedby', /.+/);
      }
    });
  }

  test('key reuse: the key is renewed so the next try is accepted', async ({ page }) => {
    const bodies = [];
    await open(page, mock({ bodies, onPost: (n) => (n === 1 ? err(409, 'key_reused') : { status: 201, body: payout() }) }));
    await send(page);
    await expect(page.getByRole('alert').filter({ hasText: 'already used for a different amount' })).toBeVisible();
    await send(page);
    await expect(page.getByRole('status').filter({ hasText: 'In progress' })).toBeVisible();
    expect(bodies[1].idempotency_key).not.toBe(bodies[0].idempotency_key);
  });

  test('a network or 5xx failure keeps the key, so the retry is the same intent', async ({ page }) => {
    const bodies = [];
    await open(page, mock({ bodies, onPost: (n) => (n === 1 ? { status: 502, body: {} } : { status: 200, body: payout() }) }));
    await send(page);
    await expect(page.getByRole('alert').filter({ hasText: 'safe to try again' })).toBeVisible();
    await send(page);
    await expect(page.getByRole('status').filter({ hasText: 'In progress' })).toBeVisible();
    expect(bodies[1].idempotency_key).toBe(bodies[0].idempotency_key);
  });

  test('a final status makes the next withdrawal use a new key', async ({ page }) => {
    const bodies = [];
    await open(page, mock({ bodies, onPost: () => ({ status: 201, body: payout({ status: 'paid' }) }) }));
    await send(page);
    await expect(page.getByRole('status').filter({ hasText: 'Sent' })).toBeVisible();
    await send(page);
    await expect.poll(() => bodies.length).toBe(2);
    expect(bodies[1].idempotency_key).not.toBe(bodies[0].idempotency_key);
  });

  test('a bad amount is caught before the confirm step and before any request', async ({ page }) => {
    const calls = await open(page, mock());
    await review(page, '10.999');
    await expect(page.getByRole('alert').filter({ hasText: 'at most 2 decimals' })).toBeVisible();
    await expect(page.getByLabel(AMOUNT)).toBeFocused();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    expect(count(calls, 'POST /api/wallet/withdraw/')).toBe(0);
  });

  test('a missing password is caught before the confirm step', async ({ page }) => {
    const calls = await open(page, mock());
    await review(page, '500', null);
    await expect(page.getByRole('alert').filter({ hasText: 'Enter your account password' })).toBeVisible();
    await expect(page.getByLabel(PASSWORD)).toBeFocused();
    expect(count(calls, 'POST /api/wallet/withdraw/')).toBe(0);
  });
});

test.describe('withdraw: safety', () => {
  test('feature_disabled is a calm status, not an error, and the form goes away', async ({ page }) => {
    await open(page, mock({ onPost: () => err(503, 'feature_disabled') }));
    await send(page);
    await expect(page.getByRole('status').filter({ hasText: 'Withdrawals are not available yet.' })).toBeVisible();
    await expect(page.getByRole('alert').filter({ hasText: 'not available' })).toHaveCount(0);
    await expect(page.getByLabel(PASSWORD)).toHaveCount(0);
  });

  test('feature_disabled on the history load shows the same calm status up front', async ({ page }) => {
    await open(page, (path, request, url) => (path === LIST ? err(503, 'feature_disabled') : mock()(path, request, url)));
    await expect(page.getByRole('status').filter({ hasText: 'Withdrawals are not available yet.' })).toBeVisible();
    await expect(page.getByLabel(PASSWORD)).toHaveCount(0);
  });

  test('a double click sends one request', async ({ page }) => {
    const calls = await open(page, mock());
    await review(page);
    await page.route('**/api/wallet/withdraw/', async (route) => {
      await new Promise((resolve) => { setTimeout(resolve, 400); });
      await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(payout()) });
    });
    let posts = 0;
    page.on('request', (r) => { if (r.method() === 'POST' && r.url().endsWith('/wallet/withdraw/')) posts += 1; });
    const button = page.getByRole('dialog').getByRole('button', { name: 'Confirm withdrawal' });
    await button.evaluate((b) => { b.click(); b.click(); });
    await expect(page.getByRole('status').filter({ hasText: 'In progress' })).toBeVisible();
    expect(posts).toBe(1);
    expect(count(calls, 'POST /api/wallet/withdraw/')).toBe(0);
  });

  test('the password is cleared after submit, on success and on failure, and hidden by default', async ({ page }) => {
    await open(page, mock({ onPost: (n) => (n === 1 ? err(403, 'wrong_password') : { status: 201, body: payout() }) }));
    const input = page.getByLabel(PASSWORD);
    await expect(input).toHaveAttribute('type', 'password');
    await send(page);
    await expect(page.getByRole('alert').filter({ hasText: 'not correct' })).toBeVisible();
    await expect(input).toHaveValue('');
    await send(page);
    await expect(page.getByRole('status').filter({ hasText: 'In progress' })).toBeVisible();
    await expect(input).toHaveValue('');
    const stored = await page.evaluate(() => JSON.stringify([localStorage, sessionStorage]));
    expect(stored).not.toContain('pw-secret-1');
  });

  test('the password is never in the page text or the history request', async ({ page }) => {
    const calls = await open(page, mock());
    await send(page);
    await expect(page.getByRole('status').filter({ hasText: 'In progress' })).toBeVisible();
    expect(await page.locator('body').innerText()).not.toContain('pw-secret-1');
    expect(calls.join('\n')).not.toContain('pw-secret-1');
  });

  test('no balance gives a calm notice, not an error', async ({ page }) => {
    await open(page, mock({ balance: '0.00' }));
    await expect(page.getByRole('status').filter({ hasText: 'no money in your wallet' })).toBeVisible();
    await expect(page.getByRole('alert')).toHaveCount(0);
  });

  test('while the balance is loading or failed there is no no-balance notice', async ({ page }) => {
    await open(page, (path, request, url) => (path === WALLET ? { status: 500, body: {} } : mock()(path, request, url)));
    await expect(page.getByText('no money in your wallet')).toHaveCount(0);
  });
});

test.describe('withdrawals history', () => {
  const rows = (from, n, status = 'paid') => Array.from({ length: n }, (_, i) => payout({
    payout_id: from - i, status, amount: `${100 + i}.00`, created_at: '2026-11-20T10:00:00Z',
  }));

  test('shows status words, amounts and masked destination, and pages with the cursor', async ({ page }) => {
    const seen = [];
    const calls = await open(page, mock({
      list: (url) => {
        seen.push(url.search);
        return url.searchParams.get('cursor') === '51'
          ? { body: { results: [payout({ payout_id: 50, status: 'failed', amount: '77.00' })], next_cursor: null } }
          : { body: { results: rows(100, 3), next_cursor: 51 } };
      },
    }));
    await expect(page.getByRole('list', { name: 'Withdrawals' }).getByRole('listitem')).toHaveCount(3);
    await expect(page.getByText('KES 100.00')).toBeVisible();
    await page.getByRole('button', { name: 'Load more' }).click();
    await expect(page.getByRole('list', { name: 'Withdrawals' }).getByRole('listitem')).toHaveCount(4);
    await expect(page.getByText('KES 77.00')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Load more' })).toHaveCount(0);
    expect(calls).toContain('GET /api/wallet/withdrawals/?cursor=51');
    expect(seen.filter((s) => s.includes('cursor=51')).length).toBe(1);
  });

  test('empty state, no fake rows', async ({ page }) => {
    await open(page, mock());
    await expect(page.getByText('No withdrawals yet.')).toBeVisible();
  });

  test('a failed load shows Retry, and Retry loads', async ({ page }) => {
    // Fails until the test clicks Retry, so it does not depend on how many times the
    // first mount loads (twice under StrictMode in dev, once in a production build).
    let failing = true;
    await open(page, (path, request, url) => {
      if (path === LIST) return failing ? { status: 500, body: {} } : { body: { results: rows(9, 1), next_cursor: null } };
      return mock()(path, request, url);
    });
    const alert = page.getByRole('alert').filter({ hasText: 'Could not load your withdrawals' });
    await expect(alert).toBeVisible();
    failing = false;
    await alert.getByRole('button', { name: 'Retry' }).click();
    await expect(page.getByRole('list', { name: 'Withdrawals' }).getByRole('listitem')).toHaveCount(1);
  });

  test('a failed Load more keeps the rows and offers Retry', async ({ page }) => {
    let page2 = 0;
    await open(page, mock({
      list: (url) => {
        if (url.searchParams.get('cursor')) {
          page2 += 1;
          return page2 === 1 ? { status: 500, body: {} } : { body: { results: rows(40, 1), next_cursor: null } };
        }
        return { body: { results: rows(100, 2), next_cursor: 41 } };
      },
    }));
    await page.getByRole('button', { name: 'Load more' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'Could not load more' })).toBeVisible();
    await expect(page.getByRole('list', { name: 'Withdrawals' }).getByRole('listitem')).toHaveCount(2);
    await page.getByRole('button', { name: 'Load more' }).click();
    await expect(page.getByRole('list', { name: 'Withdrawals' }).getByRole('listitem')).toHaveCount(3);
  });
});

test.describe('withdraw layout', () => {
  test('no horizontal scroll at 375px and 44px targets', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await open(page, mock());
    await expect(page.getByLabel(PASSWORD)).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBe(false);
    for (const target of [page.getByLabel(AMOUNT), page.getByLabel(PASSWORD), page.getByRole('button', { name: 'Review withdrawal' })]) {
      const box = await target.boundingBox();
      expect(box.height).toBeGreaterThanOrEqual(44);
    }
  });
});
