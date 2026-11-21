import assert from 'node:assert/strict';
import test from 'node:test';
import { statusGroup } from '../src/utils/statusChip.js';

test('pending and confirmed bookings fall in different groups', () => {
  assert.equal(statusGroup('pending'), 'pending');
  assert.equal(statusGroup('confirmed'), 'confirmed');
  assert.notEqual(statusGroup('pending'), statusGroup('confirmed'));
});

test('each of the five status colours has at least one booking status', () => {
  assert.equal(statusGroup('boarded'), 'boarding');
  assert.equal(statusGroup('cancelled'), 'cancelled');
  assert.equal(statusGroup('refunded'), 'refunded');
});

test('done states read as confirmed, failures as failed', () => {
  assert.equal(statusGroup('completed'), 'confirmed');
  assert.equal(statusGroup('failed'), 'failed');
});

test('case and spaces do not matter, unknown or missing is no group', () => {
  assert.equal(statusGroup(' Confirmed '), 'confirmed');
  assert.equal(statusGroup('no such status'), '');
  assert.equal(statusGroup(undefined), '');
});
