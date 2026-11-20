export function firstInvalidField(data, fields) {
  if (!data || typeof data !== 'object') return null;
  return fields.find((field) => field in data) ?? null;
}
