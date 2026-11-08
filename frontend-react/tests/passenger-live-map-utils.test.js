import assert from 'node:assert/strict';
import test from 'node:test';
import {
  estimateBusSpeedKmh,
  parkedBusLabel,
  planParkedBus,
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

const line = [[-1.2864, 36.8172], [-1.28, 36.81], [-1.27, 36.8], [-1.26, 36.79]];

test('parks the bus at the route start with the road to the pickup', () => {
  const plan = planParkedBus({
    geometry: line,
    routeStart: [-1.2864, 36.8172],
    pickup: [-1.2701, 36.8001],
    tripStatus: 'scheduled',
  });

  assert.deepEqual(plan.position, line[0]);
  assert.deepEqual(plan.pickupLeg, line.slice(0, 3));
  assert.ok(plan.heading > 270 && plan.heading < 360);
});

test('parks at the correct end when the route line is drawn backwards', () => {
  const plan = planParkedBus({
    geometry: [...line].reverse(),
    routeStart: [-1.2864, 36.8172],
    pickup: [-1.28, 36.81],
    tripStatus: 'boarding',
  });

  assert.deepEqual(plan.position, line[0]);
  assert.deepEqual(plan.pickupLeg, line.slice(0, 2));
});

test('never parks a bus for a trip that has left or ended, or with no location', () => {
  for (const tripStatus of ['departed', 'completed', 'cancelled', '', null]) {
    assert.equal(planParkedBus({ geometry: line, tripStatus }), null);
  }
  assert.equal(planParkedBus({ geometry: [], tripStatus: 'scheduled' }), null);
});

test('labels the departure time, the day when it is not today, and late buses', () => {
  const timeZone = 'Africa/Nairobi';
  const now = Date.parse('2026-11-07T12:00:00+03:00');
  const label = (tripStatus, departureAt) =>
    parkedBusLabel({ tripStatus, departureAt, now, timeZone });

  assert.match(label('scheduled', '2026-11-07T22:30:00+03:00'), /^Departs 10:30\sPM$/);
  assert.match(label('scheduled', '2026-11-08T08:00:00+03:00'), /^Departs Sun 8:00\sAM$/);
  assert.match(label('boarding', '2026-11-07T22:30:00+03:00'), /^Boarding · departs 10:30\sPM$/);
  assert.equal(label('scheduled', '2026-11-07T08:00:00+03:00'), 'Waiting to depart');
  assert.equal(label('boarding', '2026-11-07T08:00:00+03:00'), 'Boarding now');
});

test('estimates speed from fast 2-second polls once 30 seconds have passed', () => {
  const start = 1_000_000;
  let history = [];
  for (let i = 0; i <= 20; i += 1) {
    const time = start + i * 2000;
    history = recordDriverPosition(history, {
      latitude: -1.2864 + i * 0.0001,
      longitude: 36.8172,
      location_updated_at: new Date(time).toISOString(),
    }, time);
  }
  const speed = estimateBusSpeedKmh(history, start + 40_000);
  assert.ok(speed > 15 && speed < 25, `expected ~20 km/h, got ${speed}`);
});
