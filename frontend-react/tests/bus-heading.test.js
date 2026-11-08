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
