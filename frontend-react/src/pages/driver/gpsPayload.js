// Body for POST /drivers/<id>/location/. fix_at is the device's own fix time:
// a request delayed on a weak network must not be read as a fresh position.
// The server requires `accuracy` (metres) and refuses fixes it cannot trust.
export function gpsPayload(position) {
  const { latitude, longitude, accuracy } = position.coords;
  const body = { latitude, longitude };
  if (Number.isFinite(position.timestamp)) {
    body.fix_at = new Date(position.timestamp).toISOString();
  }
  if (Number.isFinite(accuracy)) body.accuracy = accuracy;
  return body;
}

// The server answers with an `ignored` key when it rejected the fix
// (older than the stored one, too old, or too inaccurate).
export const wasIgnored = (response) => Boolean(response?.ignored);
