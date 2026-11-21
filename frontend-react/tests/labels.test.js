import assert from 'node:assert/strict';
import test from 'node:test';
import { humanLabel } from '../src/utils/labels.js';

test('known codes use their agreed wording', () => {
  assert.equal(humanLabel('no_show'), 'No-show');
  assert.equal(humanLabel('company_auditor'), 'Company auditor');
  assert.equal(humanLabel('platform_admin'), 'Platform admin');
});

test('any other snake_case code becomes a sentence without underscores', () => {
  assert.equal(humanLabel('pending_payment'), 'Pending payment');
  assert.equal(humanLabel('CONFIRMED'), 'Confirmed');
});

test('empty and missing values give an empty string, not "undefined"', () => {
  assert.equal(humanLabel(undefined), '');
  assert.equal(humanLabel(null), '');
  assert.equal(humanLabel('  '), '');
});
