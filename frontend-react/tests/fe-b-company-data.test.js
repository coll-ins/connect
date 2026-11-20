import assert from 'node:assert/strict';
import test from 'node:test';
import {
  asList,
  bookedSeatsOf,
  findCompany,
  normalizeOperatorRoutes,
  staffOfCompany,
} from '../src/pages/company-manager/companyData.js';

test('asList accepts arrays and paged results, nothing else', () => {
  assert.deepEqual(asList([1, 2]), [1, 2]);
  assert.deepEqual(asList({ results: [3] }), [3]);
  assert.deepEqual(asList({}), []);
  assert.deepEqual(asList(null), []);
  assert.deepEqual(asList('oops'), []);
});

test('an empty array answer from operator-routes does not throw (M-2)', () => {
  assert.deepEqual(normalizeOperatorRoutes([]), { routes: [], operators: [] });
});

test('operator-routes with non-array members is normalised', () => {
  const out = normalizeOperatorRoutes({ routes: {}, operators: [{ id: 1 }, { id: 2, route_ids: [5] }] });
  assert.deepEqual(out.routes, []);
  assert.deepEqual(out.operators.map((o) => o.route_ids), [[], [5]]);
});

test('findCompany matches by numeric id and tolerates junk', () => {
  assert.equal(findCompany([{ id: 4, name: 'A' }], '4').name, 'A');
  assert.equal(findCompany({}, 4), null);
  assert.equal(findCompany([null, { id: 1 }], 9), null);
});

test('staffOfCompany keeps only the company own staff', () => {
  assert.deepEqual(staffOfCompany([{ company: 1 }, { company: '2' }], 2), [{ company: '2' }]);
  assert.deepEqual(staffOfCompany({}, 2), []);
});

test('bookedSeatsOf prefers the server number, including 0', () => {
  assert.equal(bookedSeatsOf({ booked_seats: 0 }, 7), 0);
  assert.equal(bookedSeatsOf({ booked_seats: 12 }, 7), 12);
  assert.equal(bookedSeatsOf({}, 7), 7);
  assert.equal(bookedSeatsOf({ booked_seats: null }, 7), 7);
  assert.equal(bookedSeatsOf({ booked_seats: 'x' }, 7), 7);
});
