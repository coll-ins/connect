import assert from 'node:assert/strict';
import test from 'node:test';
import { titleForPath } from '../src/utils/pageTitle.js';
import { nextFocusIndex } from '../src/utils/focusTrap.js';

test('titles come from the route and end with CONNECT', () => {
  assert.equal(titleForPath('/passenger'), 'Passenger | CONNECT');
  assert.equal(titleForPath('/passenger/wallet'), 'Wallet | CONNECT');
  assert.equal(titleForPath('/passenger/payment/12'), 'Payment | CONNECT');
  assert.equal(titleForPath('/company-manager/route-planner'), 'Route planner | CONNECT');
  assert.equal(titleForPath('/platform-admin'), 'Platform admin | CONNECT');
  assert.equal(titleForPath('/'), 'CONNECT');
});

test('tab wraps from the last element to the first and shift-tab the other way', () => {
  assert.equal(nextFocusIndex(3, 2, false), 0);
  assert.equal(nextFocusIndex(3, 0, true), 2);
  assert.equal(nextFocusIndex(3, 1, false), null);
  assert.equal(nextFocusIndex(3, -1, false), 0);
  assert.equal(nextFocusIndex(3, -1, true), 2);
  assert.equal(nextFocusIndex(0, -1, false), -1);
});
