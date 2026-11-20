import assert from 'node:assert/strict';
import test from 'node:test';
import {
  CUTOFF_MAX,
  parseCutoff,
  walkInBlockReason,
  walkInDesk,
} from '../src/utils/seatSummary.js';

test('parseCutoff accepts whole minutes 0..240 and nothing else', () => {
  assert.deepEqual(parseCutoff('0'), { value: 0, error: '' });
  assert.deepEqual(parseCutoff(' 30 '), { value: 30, error: '' });
  assert.deepEqual(parseCutoff(String(CUTOFF_MAX)), { value: 240, error: '' });
  for (const bad of ['', '  ', '-1', '241', '1.5', 'abc', '1e2', '+5']) {
    const out = parseCutoff(bad);
    assert.equal(out.value, null, bad);
    assert.match(out.error, /whole number of minutes from 0 to 240/);
  }
});

test('walk-in is blocked with a reason when no seats are open or walk-ups are off', () => {
  assert.equal(walkInBlockReason(undefined), '');
  assert.equal(walkInBlockReason({ open_seats: 3, walkup_allowed: true }), '');
  assert.match(walkInBlockReason({ open_seats: 0, walkup_allowed: true }), /No seats are open/);
  assert.match(walkInBlockReason({ open_seats: 4, walkup_allowed: false }), /Walk-up booking is not allowed/);
  assert.match(walkInBlockReason({ open_seats: 0, walkup_allowed: false }), /Walk-up booking is not allowed/);
});

test('walk-in desk: boarding trips always show the form, scheduled only once the server allows walk-ups', () => {
  const open = { open_seats: 5, walkup_allowed: true };
  assert.deepEqual(walkInDesk('boarding', undefined), { showForm: true, reason: '' });
  assert.deepEqual(walkInDesk('boarding', open), { showForm: true, reason: '' });
  assert.equal(walkInDesk('boarding', { open_seats: 0, walkup_allowed: true }).showForm, true);
  assert.match(walkInDesk('boarding', { open_seats: 0, walkup_allowed: true }).reason, /No seats are open/);

  assert.deepEqual(walkInDesk('scheduled', open), { showForm: true, reason: '' });
  assert.equal(walkInDesk('Scheduled', open).showForm, true);
  const noSeats = walkInDesk('scheduled', { open_seats: 0, walkup_allowed: true });
  assert.equal(noSeats.showForm, true);
  assert.match(noSeats.reason, /No seats are open/);

  const online = walkInDesk('scheduled', { open_seats: 5, walkup_allowed: false, online_open: true });
  assert.equal(online.showForm, false);
  assert.match(online.reason, /Walk-up booking is not allowed/);
  assert.deepEqual(walkInDesk('scheduled', undefined), { showForm: false, reason: '' });
  assert.deepEqual(walkInDesk('completed', open), { showForm: false, reason: '' });
});
