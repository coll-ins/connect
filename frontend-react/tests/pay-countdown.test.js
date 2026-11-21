import assert from 'node:assert/strict';
import test from 'node:test';
import { payCountdown, shouldCheckPaymentStatus, bookingClosedMessage } from '../src/utils/payment.js';

const NOW = Date.parse('2026-11-20T10:00:00Z');

test('no pay_before means no countdown is shown', () => {
  assert.equal(payCountdown(undefined, NOW), null);
  assert.equal(payCountdown(null, NOW), null);
  assert.equal(payCountdown('not a date', NOW), null);
});

test('shows minutes and seconds left', () => {
  assert.deepEqual(payCountdown('2026-11-20T10:09:05Z', NOW), { expired: false, text: '9:05' });
  assert.deepEqual(payCountdown('2026-11-20T10:00:09Z', NOW), { expired: false, text: '0:09' });
});

test('expires exactly at pay_before', () => {
  assert.deepEqual(payCountdown('2026-11-20T10:00:00Z', NOW), { expired: true, text: '0:00' });
  assert.deepEqual(payCountdown('2026-11-20T09:00:00Z', NOW), { expired: true, text: '0:00' });
});

test('offers a status check after a timeout, a 5xx or an in-progress 409, not after a 400', () => {
  assert.equal(shouldCheckPaymentStatus({}), true);
  assert.equal(shouldCheckPaymentStatus({ status: 502 }), true);
  assert.equal(shouldCheckPaymentStatus({ status: 409 }), true);
  assert.equal(shouldCheckPaymentStatus({ status: 400 }), false);
  assert.equal(shouldCheckPaymentStatus({ status: 403 }), false);
});

test('booking-closed message names the time when the server sends it', () => {
  const err = { data: { code: 'booking_closed', closes_at: '2026-11-20T10:00:00Z' }, message: 'x' };
  assert.match(bookingClosedMessage(err, 'en-KE', 'UTC'), /^Online booking for this trip closed at \d{2}:\d{2}\./);
  assert.equal(bookingClosedMessage({ data: { code: 'booking_closed' }, message: 'x' }), 'Online booking for this trip has closed. Choose another departure.');
  assert.equal(bookingClosedMessage({ data: { code: 'other' }, message: 'x' }), null);
  assert.equal(bookingClosedMessage(null), null);
});
