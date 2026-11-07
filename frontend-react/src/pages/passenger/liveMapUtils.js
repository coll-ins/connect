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

const PARKED_TRIP_STATUSES = ['scheduled', 'boarding'];

function bearingDegrees(from, to) {
  const radians = (degrees) => (degrees * Math.PI) / 180;
  const fromLat = radians(from[0]);
  const toLat = radians(to[0]);
  const longitudeDelta = radians(to[1] - from[1]);
  const y = Math.sin(longitudeDelta) * Math.cos(toLat);
  const x =
    Math.cos(fromLat) * Math.sin(toLat) -
    Math.sin(fromLat) * Math.cos(toLat) * Math.cos(longitudeDelta);

  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

function nearestIndex(point, path) {
  let nearest = 0;
  let best = Infinity;

  path.forEach((candidate, index) => {
    const distance = haversineKm(point, candidate);
    if (distance < best) {
      best = distance;
      nearest = index;
    }
  });

  return nearest;
}

/*
 * Where the bus waits before a trip goes live: the end of the route line
 * nearest the route's start point, facing the way it will drive, with the
 * stretch of road it will cover to reach the passenger's pickup.
 */
export function planParkedBus({
  geometry = [],
  routeStart = null,
  pickup = null,
  tripStatus = '',
}) {
  if (!PARKED_TRIP_STATUSES.includes(String(tripStatus).toLowerCase())) {
    return null;
  }

  if (geometry.length < 2) {
    return routeStart
      ? { position: routeStart, heading: null, pickupLeg: [] }
      : null;
  }

  const startsAtFirstPoint =
    !routeStart ||
    haversineKm(routeStart, geometry[0]) <=
      haversineKm(routeStart, geometry[geometry.length - 1]);
  const path = startsAtFirstPoint ? geometry : [...geometry].reverse();
  const position = path[0];
  const nextPoint = path.find(
    (point) => point[0] !== position[0] || point[1] !== position[1],
  );

  return {
    position,
    heading: nextPoint ? bearingDegrees(position, nextPoint) : null,
    pickupLeg: pickup ? path.slice(0, nearestIndex(pickup, path) + 1) : [],
  };
}

export function parkedBusLabel({ tripStatus, departureAt, now, timeZone }) {
  const departure = Date.parse(departureAt || '');
  const boarding = String(tripStatus || '').toLowerCase() === 'boarding';
  const inFuture = Number.isFinite(departure) && (!now || departure > now);

  if (!inFuture) return boarding ? 'Boarding now' : 'Waiting to depart';

  const date = new Date(departure);
  const time = date.toLocaleTimeString([], {
    hour: 'numeric',
    minute: '2-digit',
    timeZone,
  });
  const dayKey = (value) =>
    new Date(value).toLocaleDateString('en-CA', { timeZone });
  const when =
    !now || dayKey(departure) === dayKey(now)
      ? time
      : `${date.toLocaleDateString([], { weekday: 'short', timeZone })} ${time}`;

  return boarding ? `Boarding · departs ${when}` : `Departs ${when}`;
}

const lowerText = (value) => String(value || '').toLowerCase();

/* Can this booking's map be opened? It stays useful from booking to arrival. */
export function canOpenTripMap(booking) {
  const status = lowerText(booking?.status);
  const tripStatus = lowerText(booking?.trip_status);

  if (!['scheduled', 'boarding', 'departed'].includes(tripStatus)) return false;
  if (status === 'confirmed') return true;
  if (status === 'completed') {
    return booking.boarded === true && tripStatus !== 'scheduled';
  }

  return (
    status === 'pending' &&
    lowerText(booking.payment_method) === 'cash' &&
    lowerText(booking.payment_status) === 'pending'
  );
}

/* Still ahead of the passenger, or still under way. */
export function isActiveBooking(booking) {
  return (
    !['cancelled', 'completed', 'no_show'].includes(lowerText(booking?.status)) ||
    canOpenTripMap(booking)
  );
}

export const OFF_ROUTE_KM = 0.06;

/* Shortest distance from a point to a [lat, lng] line, in km. */
export function distanceFromLineKm(point, line) {
  if (!point || !Array.isArray(line) || line.length === 0) return Infinity;

  const kmPerLng = 111.32 * Math.cos((point[0] * Math.PI) / 180);
  const kmPerLat = 110.574;
  const toLocal = ([lat, lng]) => [
    (lng - point[1]) * kmPerLng,
    (lat - point[0]) * kmPerLat,
  ];

  if (line.length === 1) return Math.hypot(...toLocal(line[0]));

  let best = Infinity;

  for (let i = 0; i < line.length - 1; i += 1) {
    const [ax, ay] = toLocal(line[i]);
    const [bx, by] = toLocal(line[i + 1]);
    const dx = bx - ax;
    const dy = by - ay;
    const lengthSquared = dx * dx + dy * dy;
    const t = lengthSquared
      ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / lengthSquared))
      : 0;
    best = Math.min(best, Math.hypot(ax + t * dx, ay + t * dy));
  }

  return best;
}

export function lineLengthKm(line) {
  if (!Array.isArray(line)) return 0;

  let total = 0;
  for (let i = 0; i < line.length - 1; i += 1) {
    total += haversineKm(line[i], line[i + 1]);
  }
  return total;
}

/* A GeoJSON LineString as [lat, lng] points. */
export function geoJsonLinePositions(geometry) {
  const coordinates = geometry?.coordinates;
  if (!Array.isArray(coordinates)) return [];

  return coordinates
    .map((point) => [Number(point?.[1]), Number(point?.[0])])
    .filter(([lat, lng]) => Number.isFinite(lat) && Number.isFinite(lng));
}

/* The part of a new road still ahead of the bus, starting at the bus. */
export function lineAheadOfBus(busPosition, line) {
  if (!busPosition || !Array.isArray(line) || line.length === 0) return [];
  return [busPosition, ...line.slice(nearestIndex(busPosition, line) + 1)];
}

/*
 * The one thing the passenger needs to know right now, and whether their
 * boarding PIN belongs next to it.
 */
export function tripGuide({
  bookingStatus,
  tripIsLive,
  parked,
  boarding,
  departureLabel,
  boarded,
  rerouted,
  busPastPickup,
  pickupKm,
  etaText,
  startName,
  pickupName,
  destinationName,
  lastSeenText,
}) {
  if (String(bookingStatus || '').toLowerCase() === 'pending') {
    return {
      title: 'Payment needed to confirm your seat',
      detail: 'Your boarding PIN appears once your payment is confirmed.',
      showPin: false,
    };
  }

  if (boarded) {
    return {
      title: "You're on board",
      detail: rerouted
        ? `The bus took another road. The new way to ${destinationName} is in blue.`
        : `The blue line shows the way to ${destinationName}.`,
      showPin: false,
    };
  }

  if (parked) {
    return {
      title: boarding
        ? `Your bus is boarding at ${startName}`
        : `Your bus is waiting at ${startName}`,
      detail: `${departureLabel}. Be at ${pickupName} early and keep your PIN ready.`,
      showPin: true,
    };
  }

  if (!tripIsLive) {
    return {
      title: "Waiting for your bus's location",
      detail: lastSeenText
        ? `Last seen ${lastSeenText} ago. The map updates when the driver's GPS is back.`
        : "The map updates when the driver's GPS is back.",
      showPin: true,
    };
  }

  if (busPastPickup) {
    return {
      title: `Your bus has passed ${pickupName}`,
      detail: 'If you were not picked up, call the driver.',
      showPin: true,
    };
  }

  if (rerouted) {
    return {
      title: 'Your bus took another road',
      detail: `It is still coming to ${pickupName}. The new way is in blue.`,
      showPin: true,
    };
  }

  if (pickupKm != null && pickupKm <= 0.15) {
    return {
      title: `Your bus is at ${pickupName}`,
      detail: 'Show the driver your PIN to board.',
      showPin: true,
    };
  }

  return {
    title: 'Your bus is on the way',
    detail: etaText
      ? `Be at ${pickupName}. It is about ${etaText} away.`
      : `Be at ${pickupName} and keep your PIN ready.`,
    showPin: true,
  };
}
