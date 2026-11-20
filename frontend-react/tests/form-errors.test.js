import assert from 'node:assert/strict';
import test from 'node:test';
import { firstInvalidField } from '../src/utils/formErrors.js';

test('finds the first form field the server complained about', () => {
  const fields = ['name', 'phone_number', 'password'];
  assert.equal(firstInvalidField({ password: ['too short'], phone_number: ['bad'] }, fields), 'phone_number');
});

test('returns null for a general error or no data', () => {
  assert.equal(firstInvalidField({ error: 'Invalid credentials' }, ['phone_number']), null);
  assert.equal(firstInvalidField(null, ['phone_number']), null);
  assert.equal(firstInvalidField('<html>', ['phone_number']), null);
});
