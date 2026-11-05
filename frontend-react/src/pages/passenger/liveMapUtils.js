const DRIVER_HISTORY_WINDOW_MS = 2 * 60 * 1000;
const MIN_SPEED_SAMPLE_MS = 30 * 1000;

function haversineKm(a, b) {
  const radians = (degrees) => (degrees * Math.PI) / 180;
  const latitudeDelta = radians(b[0] - a[0]);
  const longitudeDelta = radians(b[1] - a[1]);
  const value =
    Math.sin(latitudeDelta / 2) ** 2 +
    Math.cos(radians(a[0])) *
      Math.cos(radians(b[0])) *
      Math.sin(longitudeDelta / 2) ** 2;

  return 6371 * 2 * Math.asin(Math.min(1, Math.sqrt(value)));
}

export function recordDriverPosition(history, driver, receivedAt = Date.now()) {
  const latitude = Number(driver?.latitude ?? driver?.lat);
  const longitude = Number(
    driver?.longitude ?? driver?.lng ?? driver?.lon,
  );
  const updatedAt = Date.parse(driver?.location_updated_at || '');
  const time = Number.isFinite(updatedAt) ? updatedAt : receivedAt;

  if (
    !Number.isFinite(latitude) ||
    !Number.isFinite(longitude) ||
    time > receivedAt + 60 * 1000 ||
    receivedAt - time > DRIVER_HISTORY_WINDOW_MS
  ) {
    return history;
  }

  const last = history[history.length - 1];
  if (
    last &&
    (time <= last.time ||
      (latitude === last.position[0] && longitude === last.position[1]))
  ) {
    return history;
  }

  return [
    ...history.filter((sample) => time - sample.time <= DRIVER_HISTORY_WINDOW_MS),
    { position: [latitude, longitude], time },
  ].slice(-8);
}

export function estimateBusSpeedKmh(history, now = Date.now()) {
  const recent = history.filter(
    (sample) =>
      Number.isFinite(sample.time) &&
      now >= sample.time &&
      now - sample.time <= DRIVER_HISTORY_WINDOW_MS,
  );

  if (recent.length < 2) return null;

  const first = recent[0];
  const last = recent[recent.length - 1];
  const elapsedMs = last.time - first.time;

  if (elapsedMs < MIN_SPEED_SAMPLE_MS) return null;

  const distanceKm = haversineKm(first.position, last.position);
  if (distanceKm < 0.02) return null;

  const speedKmh = distanceKm / (elapsedMs / (60 * 60 * 1000));
  if (speedKmh < 5 || speedKmh > 100) return null;

  return Number(speedKmh.toFixed(1));
}
