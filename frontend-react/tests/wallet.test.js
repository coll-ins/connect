import assert from 'node:assert/strict';
import test from 'node:test';
import {
  TOPUP_POLL_MAX, TOPUP_POLL_MS, cancelWarning, formatSigned, parseTopupAmount, topupErrorMessage,
  topupPollAction, topupReturnCopy, toCents, txTypeLabel, walletPayErrorMessage, walletPayState,
} from '../src/utils/wallet.js';

test('top-up amount mirrors the server rule: 1-7 digits, up to 2 decimals, above zero', () => {
  assert.deepEqual(parseTopupAmount('500'), { ok: true, value: '500' });
  assert.deepEqual(parseTopupAmount(' 1250.5 '), { ok: true, value: '1250.5' });
  assert.deepEqual(parseTopupAmount('0.01'), { ok: true, value: '0.01' });
  for (const bad of ['', '   ', '0', '0.00', '-5', 'abc', '10.999', '12345678', 'KES 500', '1,000', '1e3', null, undefined]) {
    const r = parseTopupAmount(bad);
    assert.equal(r.ok, false, `expected ${JSON.stringify(bad)} to be rejected`);
    assert.match(r.error, /amount/i);
  }
});

test('toCents compares money without float drift', () => {
  assert.equal(toCents('0.10'), 10);
  assert.equal(toCents('1234.56'), 123456);
  assert.equal(toCents('50'), 5000);
  assert.equal(toCents('-50.00'), -5000);
  assert.equal(toCents(undefined), null);
  assert.equal(toCents('x'), null);
});

test('pay state: unknown balance blocks with no number, short balance says by how much', () => {
  assert.deepEqual(walletPayState({ balance: undefined, required: '800.00' }), { canPay: false, reason: 'unknown' });
  assert.deepEqual(walletPayState({ balance: '799.99', required: '800.00' }), { canPay: false, reason: 'insufficient' });
  assert.deepEqual(walletPayState({ balance: '800.00', required: '800.00' }), { canPay: true, reason: null });
  assert.deepEqual(walletPayState({ balance: '0.00', required: '800.00' }), { canPay: false, reason: 'insufficient' });
  assert.deepEqual(walletPayState({ balance: '900', required: undefined }), { canPay: false, reason: 'unknown' });
});

test('top-up errors: server code first, then status, never the raw server 5xx text', () => {
  const e = (status, data) => Object.assign(new Error('raw'), { status, data });
  assert.equal(topupErrorMessage(e(503, { code: 'topup_disabled' })), 'Top-up is not available yet.');
  assert.match(topupErrorMessage(e(400, { code: 'amount_too_small', min: '50' })), /minimum.*KES 50\.00/i);
  assert.match(topupErrorMessage(e(400, { code: 'amount_too_large', max: '20000' })), /maximum.*KES 20,000\.00/i);
  assert.match(topupErrorMessage(e(400, { code: 'balance_cap', balance: '49000.00', max_balance: '50000' })), /KES 50,000\.00/);
  assert.match(topupErrorMessage(e(400, { code: 'invalid_amount' })), /amount/i);
  assert.match(topupErrorMessage(e(403, { code: 'passenger_only' })), /passenger accounts/i);
  assert.match(topupErrorMessage(e(502, { code: 'gateway_error' })), /payment provider.*not charged/i);
  assert.match(topupErrorMessage(e(429, { detail: 'throttled' })), /too many/i);
  assert.match(topupErrorMessage(e(undefined, undefined)), /connection/i);
  assert.match(topupErrorMessage(e(500, undefined)), /try again/i);
});

test('wallet pay errors: each code has plain copy and the next step', () => {
  const e = (status, data) => Object.assign(new Error('raw'), { status, data });
  const ins = walletPayErrorMessage(e(400, { code: 'insufficient_funds', balance: '100.00', required: '800.00' }));
  assert.match(ins.text, /KES 100\.00.*KES 800\.00/);
  assert.equal(ins.refreshWallet, true);
  assert.match(walletPayErrorMessage(e(400, { code: 'amount_mismatch' })).text, /price/i);
  assert.match(walletPayErrorMessage(e(400, { code: 'booking_not_payable' })).text, /can no longer be paid/i);
  assert.match(walletPayErrorMessage(e(400, { code: 'trip_departed' })).text, /departed/i);
  assert.match(walletPayErrorMessage(e(403, { code: 'passenger_only' })).text, /passenger accounts/i);
  const paid = walletPayErrorMessage(e(409, { code: 'already_paid' }));
  assert.match(paid.text, /already paid/i);
  assert.equal(paid.refreshBooking, true);
  assert.equal(walletPayErrorMessage(e(409, { code: 'hold_expired' })).refreshBooking, true);
  assert.match(walletPayErrorMessage(e(409, { code: 'hold_expired' })).text, /nothing was taken/i);
  assert.equal(walletPayErrorMessage(e(409, { code: 'booking_moved' })).refreshBooking, true);
  assert.match(walletPayErrorMessage(e(409, { code: 'hold_conflict' })).text, /try again/i);
  assert.match(walletPayErrorMessage(e(404, {})).text, /find this booking/i);
  assert.match(walletPayErrorMessage(e(500, undefined)).text, /not be charged twice/i);
  assert.match(walletPayErrorMessage(e(undefined, undefined)).text, /not be charged twice/i);
});

test('poll rule: stop on a terminal status, give up after the cap, otherwise continue', () => {
  assert.equal(topupPollAction('credited', 1), 'credited');
  assert.equal(topupPollAction('review', 1), 'review');
  assert.equal(topupPollAction('expired', 1), 'expired');
  assert.equal(topupPollAction('pending', 1), 'continue');
  assert.equal(topupPollAction('pending', TOPUP_POLL_MAX - 1), 'continue');
  assert.equal(topupPollAction('pending', TOPUP_POLL_MAX), 'giveup');
  assert.equal(topupPollAction('something_new', 1), 'continue');
  assert.equal(topupPollAction('credited', TOPUP_POLL_MAX), 'credited');
  assert.ok(TOPUP_POLL_MS >= 5000, 'server re-queries Paystack with a 5 s cooldown');
});

test('return copy for each terminal status', () => {
  assert.match(topupReturnCopy('review'), /We received your payment and are checking it/);
  assert.match(topupReturnCopy('expired'), /This top-up expired; if you were charged it will be credited/);
  assert.match(topupReturnCopy('credited', '500.00'), /KES 500\.00.*added/);
  assert.match(topupReturnCopy('pending'), /confirming/i);
});

test('history amounts carry a sign and a word, never colour alone', () => {
  assert.deepEqual(formatSigned('500.00'), { sign: '+', text: '+KES 500.00', words: 'Credit of KES 500.00' });
  assert.deepEqual(formatSigned('-50.00'), { sign: '-', text: '-KES 50.00', words: 'Debit of KES 50.00' });
  assert.deepEqual(formatSigned('oops'), { sign: '', text: '--', words: 'Amount unavailable' });
  assert.equal(txTypeLabel('refund'), 'Refund');
  assert.equal(txTypeLabel('spend'), 'Booking payment');
  assert.equal(txTypeLabel('deposit'), 'Top-up');
  assert.equal(txTypeLabel('brand_new_type'), 'Wallet activity');
});

test('cancel copy says a wallet refund lands in the wallet at once', () => {
  const base = { payment_status: 'confirmed' };
  assert.match(cancelWarning({ ...base, payment_method: 'wallet' }), /50% of the fare.*CONNECT wallet.*at once/);
  assert.equal(cancelWarning({ ...base, payment_method: 'digital' }), 'Cancel this booking? You will be refunded 50% of the fare.');
  assert.equal(cancelWarning({ ...base, payment_method: 'cash' }), 'Cancel this booking? Nothing has been charged.');
  assert.equal(cancelWarning({ payment_status: 'pending', payment_method: 'wallet' }), 'Cancel this booking? Nothing has been charged.');
});
