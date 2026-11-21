// loading | error | ready, derived from facts instead of stored as a fourth
// piece of state. Data already on screen stays ready if a refresh fails.
export function deriveStatus({ loading, error, hasData }) {
  if (hasData) return 'ready';
  if (loading) return 'loading';
  if (error) return 'error';
  return 'loading';
}

export const isEmptyList = (status, list) =>
  status === 'ready' && Array.isArray(list) && list.length === 0;
