import assert from 'node:assert/strict';
import test from 'node:test';
import { payCountdown, shouldCheckPaymentStatus } from '../src/utils/payment.js';

const NOW = Date.parse('2026-11-20T10:00:00.000Z');

test('a part second left still shows 0:01 and is not expired (round up, never down)', () => {
  assert.deepEqual(payCountdown('2026-11-20T10:00:00.500Z', NOW), { expired: false, text: '0:01' });
  assert.deepEqual(payCountdown('2026-11-20T10:00:59.001Z', NOW), { expired: false, text: '1:00' });
});

test('a status check is offered on exactly 500, not on 499', () => {
  assert.equal(shouldCheckPaymentStatus({ status: 500 }), true);
  assert.equal(shouldCheckPaymentStatus({ status: 499 }), false);
});

test('seat_limit answers get plain copy with the cap; other errors get none', async () => {
  const { seatLimitMessage, MAX_SEATS_PER_BOOKING } = await import('../src/utils/payment.js');
  assert.equal(MAX_SEATS_PER_BOOKING, 6);
  assert.equal(seatLimitMessage({ data: { code: 'seat_limit', error: 'raw' } }), 'You can book up to 6 seats at a time. Lower the number of seats and try again.');
  assert.equal(seatLimitMessage({ data: { code: 'booking_closed' } }), null);
  assert.equal(seatLimitMessage(undefined), null);
});
