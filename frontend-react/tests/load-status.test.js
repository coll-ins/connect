import assert from 'node:assert/strict';
import test from 'node:test';
import { deriveStatus, isEmptyList } from '../src/utils/loadStatus.js';

test('loading until the first response arrives', () => {
  assert.equal(deriveStatus({ loading: true, error: '', hasData: false }), 'loading');
});

test('error wins when the request failed and no data was loaded', () => {
  assert.equal(deriveStatus({ loading: false, error: 'boom', hasData: false }), 'error');
});

test('ready once data is present, even if a later refresh failed', () => {
  assert.equal(deriveStatus({ loading: false, error: 'boom', hasData: true }), 'ready');
});

test('a refresh while data is shown stays ready', () => {
  assert.equal(deriveStatus({ loading: true, error: '', hasData: true }), 'ready');
});

test('a retry after an error shows loading, not the stale error', () => {
  assert.equal(deriveStatus({ loading: true, error: 'boom', hasData: false }), 'loading');
});

test('an empty list is empty only when ready', () => {
  assert.equal(isEmptyList('ready', []), true);
  assert.equal(isEmptyList('loading', []), false);
  assert.equal(isEmptyList('error', []), false);
  assert.equal(isEmptyList('ready', [1]), false);
});
