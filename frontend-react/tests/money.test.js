import assert from 'node:assert/strict';
import test from 'node:test';
import { formatMoney, parseMoneyInput } from '../src/utils/money.js';

test('formats a loaded amount with two decimals', () => {
  assert.equal(formatMoney(1500), 'KES 1,500.00');
  assert.equal(formatMoney('250.5'), 'KES 250.50');
});

test('a real zero is shown as zero', () => {
  assert.equal(formatMoney(0), 'KES 0.00');
  assert.equal(formatMoney('0'), 'KES 0.00');
});

test('a value that never loaded is never shown as KES 0.00', () => {
  for (const missing of [undefined, null, '', 'abc', NaN]) {
    assert.equal(formatMoney(missing), '--');
  }
});

test('parses money input to at most 2 decimals', () => {
  assert.equal(parseMoneyInput('1,500'), 1500);
  assert.equal(parseMoneyInput(' 99.5 '), 99.5);
  assert.equal(parseMoneyInput('10.456'), 10.46);
  assert.equal(parseMoneyInput('KES 20'), 20);
});

test('rejects empty, zero, negative and non-numeric money input', () => {
  for (const bad of ['', '   ', '0', '-5', 'abc', '1.2.3', null, undefined]) {
    assert.equal(parseMoneyInput(bad), null);
  }
});
