import assert from 'node:assert/strict';
import test from 'node:test';
import { createIntentKeys, newKey, withIdempotencyKey } from '../src/utils/idempotency.js';

test('the same intent reuses one key on retry', () => {
  const keys = createIntentKeys();
  const first = keys.keyFor('trip:4|seats:2|stage:9');
  assert.equal(keys.keyFor('trip:4|seats:2|stage:9'), first);
});

test('a changed intent gets a new key', () => {
  const keys = createIntentKeys();
  const first = keys.keyFor('trip:4|seats:2|stage:9');
  assert.notEqual(keys.keyFor('trip:4|seats:3|stage:9'), first);
});

test('after success the next intent gets a new key', () => {
  const keys = createIntentKeys();
  const first = keys.keyFor('a');
  keys.clear();
  assert.notEqual(keys.keyFor('a'), first);
});

test('keys are unique uuid-shaped strings, also without crypto.randomUUID', () => {
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
  assert.match(newKey(), uuid);
  assert.match(newKey({ getRandomValues: (a) => a.fill(7) }), uuid);
  assert.notEqual(newKey(), newKey());
});

test('the key goes in the JSON body field idempotency_key and the body is not mutated', () => {
  const body = { trip_id: 1, seats: 2 };
  const out = withIdempotencyKey(body, 'abc');
  assert.deepEqual(out, { trip_id: 1, seats: 2, idempotency_key: 'abc' });
  assert.deepEqual(body, { trip_id: 1, seats: 2 });
});
