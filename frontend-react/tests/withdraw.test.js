import assert from 'node:assert/strict';
import test from 'node:test';
import {
  createWithdrawKeys, isFinalStatus, isValidKey, parseWithdrawAmount, withdrawErrorInfo,
  withdrawStatusCopy,
} from '../src/utils/withdraw.js';

const err = (status, data) => Object.assign(new Error('x'), { status, data });

test('amount: accepts whole and 2-decimal KES, trims', () => {
  assert.deepEqual(parseWithdrawAmount(' 500 '), { ok: true, value: '500' });
  assert.deepEqual(parseWithdrawAmount('500.50'), { ok: true, value: '500.50' });
});

test('amount: rejects empty, zero, negative, 3 decimals, letters, comma, huge', () => {
  for (const bad of ['', '   ', '0', '0.00', '-5', '10.999', 'abc', '1,000', '12345678', undefined, 50]) {
    const r = parseWithdrawAmount(bad);
    assert.equal(r.ok, false, `should reject ${String(bad)}`);
    assert.ok(r.error.length > 10);
  }
});

test('key: valid shape is 8-64 chars of A-Za-z0-9_-', () => {
  assert.equal(isValidKey('abcdefgh'), true);
  assert.equal(isValidKey('a'.repeat(64)), true);
  assert.equal(isValidKey('a'.repeat(65)), false);
  assert.equal(isValidKey('short'), false);
  assert.equal(isValidKey('has space 123'), false);
  assert.equal(isValidKey('12345678.'), false);
});

test('key: the same amount reuses the key on retry, a new amount gets a new one', () => {
  let n = 0;
  const keys = createWithdrawKeys(() => `key-${(n += 1)}-aaaaaaaa`);
  const first = keys.keyFor('500');
  assert.equal(keys.keyFor('500'), first);
  assert.equal(keys.keyFor('500.00'), first, '500 and 500.00 are the same intent');
  assert.notEqual(keys.keyFor('600'), first);
});

test('key: kept while the payout is in progress, renewed once it is final', () => {
  let n = 0;
  const keys = createWithdrawKeys(() => `key-${(n += 1)}-aaaaaaaa`);
  const first = keys.keyFor('500');
  keys.settle('requested');
  assert.equal(keys.keyFor('500'), first);
  keys.settle('submitted');
  assert.equal(keys.keyFor('500'), first);
  keys.settle('paid');
  assert.notEqual(keys.keyFor('500'), first);
  const second = keys.keyFor('500');
  keys.settle('failed');
  assert.notEqual(keys.keyFor('500'), second);
  const third = keys.keyFor('500');
  keys.settle('review');
  assert.notEqual(keys.keyFor('500'), third);
});

test('key: reset drops the key (key_reused)', () => {
  let n = 0;
  const keys = createWithdrawKeys(() => `key-${(n += 1)}-aaaaaaaa`);
  const first = keys.keyFor('500');
  keys.reset();
  assert.notEqual(keys.keyFor('500'), first);
});

test('final statuses', () => {
  assert.deepEqual(['requested', 'submitted', 'paid', 'failed', 'review', 'weird'].map(isFinalStatus),
    [false, false, true, true, true, false]);
});

test('status copy: every status has plain words and the right tone', () => {
  assert.equal(withdrawStatusCopy('requested').label, 'In progress');
  assert.equal(withdrawStatusCopy('submitted').label, 'In progress');
  assert.equal(withdrawStatusCopy('paid').label, 'Sent');
  assert.match(withdrawStatusCopy('failed').text, /returned to your wallet/);
  assert.match(withdrawStatusCopy('review').text, /your money is safe/);
  assert.equal(withdrawStatusCopy('review').tone, 'info');
  assert.equal(withdrawStatusCopy('failed').tone, 'warn');
  assert.equal(withdrawStatusCopy('???').label, 'Status unavailable');
});

test('errors: field codes point at the field and use the server numbers', () => {
  assert.deepEqual(
    (({ field, text }) => ({ field, text }))(withdrawErrorInfo(err(400, { code: 'amount_too_small', min: '50' }))),
    { field: 'amount', text: 'The minimum withdrawal is KES 50.00.' },
  );
  assert.equal(withdrawErrorInfo(err(400, { code: 'amount_too_large', max: '20000' })).text,
    'The maximum withdrawal is KES 20,000.00.');
  assert.equal(withdrawErrorInfo(err(400, { code: 'invalid_amount' })).field, 'amount');
  assert.equal(withdrawErrorInfo(err(400, { code: 'password_required' })).field, 'password');
  assert.equal(withdrawErrorInfo(err(403, { code: 'wrong_password' })).field, 'password');
});

test('errors: daily limit shows limit and remaining', () => {
  const info = withdrawErrorInfo(err(400, { code: 'daily_limit', limit: '50000', remaining: '12000.50' }));
  assert.match(info.text, /KES 50,000\.00/);
  assert.match(info.text, /KES 12,000\.50/);
  assert.equal(info.field, 'amount');
});

test('errors: lockout, throttle and wrong password are three different messages', () => {
  const lock = withdrawErrorInfo(err(429, { code: 'too_many_attempts', error: 'x' })).text;
  const throttle = withdrawErrorInfo(err(429, { detail: 'Request was throttled.' })).text;
  const wrong = withdrawErrorInfo(err(403, { code: 'wrong_password' })).text;
  assert.match(lock, /15 minutes/);
  assert.match(throttle, /Too many withdrawal requests/);
  assert.equal(new Set([lock, throttle, wrong]).size, 3);
});

test('errors: feature_disabled is calm, not an error', () => {
  const info = withdrawErrorInfo(err(503, { code: 'feature_disabled' }));
  assert.equal(info.kind, 'disabled');
  assert.equal(info.text, 'Withdrawals are not available yet.');
});

test('errors: in flight is info and refreshes; key_reused renews the key', () => {
  const inflight = withdrawErrorInfo(err(409, { code: 'payout_in_flight' }));
  assert.equal(inflight.kind, 'info');
  assert.equal(inflight.refresh, true);
  assert.equal(withdrawErrorInfo(err(409, { code: 'key_reused' })).resetKey, true);
});

test('errors: insufficient funds asks for a refresh of the balance', () => {
  const info = withdrawErrorInfo(err(400, { code: 'insufficient_funds' }));
  assert.equal(info.refresh, true);
  assert.equal(info.field, 'amount');
});

test('errors: no response or a 5xx says retrying is safe and keeps the key', () => {
  for (const e of [err(undefined, undefined), err(500, {}), err(502, 'bad gateway')]) {
    const info = withdrawErrorInfo(e);
    assert.match(info.text, /safe to try again/);
    assert.notEqual(info.resetKey, true);
  }
});

test('errors: never echoes server text, phone numbers or the password', () => {
  const info = withdrawErrorInfo(err(400, { code: 'invalid_phone', error: 'secret 0712345678' }));
  assert.doesNotMatch(info.text, /0712345678/);
  assert.match(info.text, /phone number/);
});
