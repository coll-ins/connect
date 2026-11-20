import assert from 'node:assert/strict';
import test from 'node:test';
import { gpsPayload, wasIgnored } from '../src/pages/driver/gpsPayload.js';

const fix = (over = {}) => ({
  coords: { latitude: -1.2921, longitude: 36.8219, accuracy: 12.4, ...over.coords },
  timestamp: 1_700_000_000_000,
  ...over,
});

test('payload carries the device fix time as ISO and the accuracy in metres', () => {
  assert.deepEqual(gpsPayload(fix()), {
    latitude: -1.2921,
    longitude: 36.8219,
    fix_at: '2023-11-14T22:13:20.000Z',
    accuracy_m: 12.4,
  });
});

test('a missing accuracy or timestamp is left out, not sent as null', () => {
  const body = gpsPayload({ coords: { latitude: 1, longitude: 2 } });
  assert.deepEqual(body, { latitude: 1, longitude: 2 });
});

test('a non-finite accuracy is left out', () => {
  const body = gpsPayload(fix({ coords: { accuracy: NaN } }));
  assert.equal('accuracy_m' in body, false);
});

test('the server saying ignored means the position is not fresh', () => {
  assert.equal(wasIgnored({ ignored: 'stale' }), true);
  assert.equal(wasIgnored({ ignored: true }), true);
  assert.equal(wasIgnored({ latitude: 1 }), false);
  assert.equal(wasIgnored(null), false);
});
