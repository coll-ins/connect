import assert from 'node:assert/strict';
import test from 'node:test';
import { bodyHeading, buildCumulative } from '../src/components/maps/useRoadDriverPosition.js';

// 200 m north, then 200 m east.
const route = [[-1.3, 36.8], [-1.2982, 36.8], [-1.2982, 36.8018]];
const cumulative = buildCumulative(route);
const corner = cumulative[1];

test('the bus swings through a corner instead of snapping at it', () => {
  assert.ok(Math.abs(bodyHeading(route, cumulative, corner - 0.05)) < 1);
  assert.ok(Math.abs(bodyHeading(route, cumulative, corner) - 45) < 2);
  assert.ok(Math.abs(bodyHeading(route, cumulative, corner + 0.05) - 90) < 1);
  const before = bodyHeading(route, cumulative, corner - 0.01);
  assert.ok(before > 5 && before < 40, `heading 10 m before the corner was ${before}`);
});

test('the bus keeps its speed into the next glide and never rolls backwards', async () => {
  const { planGlide, glideAt } = await import('../src/components/maps/useRoadDriverPosition.js');
  const first = planGlide(null, 0, 0.1, 0, 10000);
  assert.equal(first.m0, 0); // pulls away from rest
  const second = planGlide(first, 0.09, 0.2, 9000, 10000);
  assert.ok(second.m0 > 0, 'carries its speed instead of restarting');
  let last = second.from;
  for (let p = 0; p <= 1.0001; p += 0.01) {
    const d = glideAt(second, p);
    assert.ok(d >= last - 1e-12, `went backwards at ${p}`);
    last = d;
  }
  assert.ok(Math.abs(glideAt(second, 1) - 0.2) < 1e-12);
});
