import assert from 'node:assert/strict';
import test from 'node:test';
import {
  estimateBusSpeedKmh,
  recordDriverPosition,
} from '../src/pages/passenger/liveMapUtils.js';

test('requires distinct fresh fixes with enough elapsed time for a speed estimate', () => {
  const start = 1_000_000;
  const initial = recordDriverPosition([], {
    latitude: -1.2864,
    longitude: 36.8172,
    location_updated_at: new Date(start).toISOString(),
  }, start);
  const repeated = recordDriverPosition(initial, {
    latitude: -1.2864,
    longitude: 36.8172,
    location_updated_at: new Date(start + 60_000).toISOString(),
  }, start + 60_000);

  assert.equal(repeated.length, 1);
  assert.equal(estimateBusSpeedKmh(repeated, start + 60_000), null);

  const tooSoon = recordDriverPosition(initial, {
    latitude: -1.2864,
    longitude: 36.8232,
    location_updated_at: new Date(start + 10_000).toISOString(),
  }, start + 10_000);
  assert.equal(estimateBusSpeedKmh(tooSoon, start + 10_000), null);
});

test('estimates speed only from plausible recent bus movement', () => {
  const start = 1_000_000;
  const samples = recordDriverPosition([], {
    latitude: -1.2864,
    longitude: 36.8172,
    location_updated_at: new Date(start).toISOString(),
  }, start);
  const moved = recordDriverPosition(samples, {
    latitude: -1.2864,
    longitude: 36.8232,
    location_updated_at: new Date(start + 60_000).toISOString(),
  }, start + 60_000);

  assert.ok(estimateBusSpeedKmh(moved, start + 60_000) > 30);
  assert.equal(estimateBusSpeedKmh(moved, start + 6 * 60_000), null);
});

test('does not use stale, future, or out-of-order GPS fixes', () => {
  const now = 1_000_000;
  const firstFix = {
    latitude: -1.2864,
    longitude: 36.8172,
    location_updated_at: new Date(now - 30_000).toISOString(),
  };
  const history = recordDriverPosition([], firstFix, now);
  const outOfOrder = recordDriverPosition(history, {
    latitude: -1.2864,
    longitude: 36.8232,
    location_updated_at: new Date(now - 60_000).toISOString(),
  }, now);
  const stale = recordDriverPosition([], {
    latitude: -1.2864,
    longitude: 36.8172,
    location_updated_at: new Date(now - 6 * 60_000).toISOString(),
  }, now);
  const future = recordDriverPosition([], {
    latitude: -1.2864,
    longitude: 36.8172,
    location_updated_at: new Date(now + 2 * 60_000).toISOString(),
  }, now);

  assert.equal(outOfOrder, history);
  assert.equal(stale.length, 0);
  assert.equal(future.length, 0);
});
