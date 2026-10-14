const EARTH_RADIUS_M = 6371000;
const toRadians = (degrees) => (degrees * Math.PI) / 180;
const toDegrees = (radians) => (radians * 180) / Math.PI;

export function toLatLng(position) {
  if (!position) return null;

  const values = Array.isArray(position)
    ? position
    : [
        position.lat ?? position.latitude,
        position.lng ?? position.lon ?? position.longitude,
      ];
  const lat = Number(values[0]);
  const lng = Number(values[1]);

  return Number.isFinite(lat) && Number.isFinite(lng)
    ? [lat, lng]
    : null;
}

export function haversine(a, b) {
  const latitudeDelta = toRadians(b[0] - a[0]);
  const longitudeDelta = toRadians(b[1] - a[1]);
  const value =
    Math.sin(latitudeDelta / 2) ** 2 +
    Math.cos(toRadians(a[0])) *
      Math.cos(toRadians(b[0])) *
      Math.sin(longitudeDelta / 2) ** 2;

  return (
    2 *
    EARTH_RADIUS_M *
    Math.asin(Math.min(1, Math.sqrt(value)))
  );
}

export function bearing(a, b) {
  const longitudeDelta = toRadians(b[1] - a[1]);
  const y =
    Math.sin(longitudeDelta) * Math.cos(toRadians(b[0]));
  const x =
    Math.cos(toRadians(a[0])) * Math.sin(toRadians(b[0])) -
    Math.sin(toRadians(a[0])) *
      Math.cos(toRadians(b[0])) *
      Math.cos(longitudeDelta);

  return (toDegrees(Math.atan2(y, x)) + 360) % 360;
}

export function buildRoute(positions) {
  const points = (positions || [])
    .map(toLatLng)
    .filter(Boolean);
  const cumulative = [0];

  for (let index = 1; index < points.length; index += 1) {
    cumulative.push(
      cumulative[index - 1] +
        haversine(points[index - 1], points[index]),
    );
  }

  return {
    points,
    cumulative,
    total: cumulative[cumulative.length - 1] || 0,
  };
}

function projectOnSegment(start, end, position) {
  const metersPerDegreeY = (Math.PI * EARTH_RADIUS_M) / 180;
  const metersPerDegreeX =
    Math.cos(toRadians(position[0])) * metersPerDegreeY;
  const startX = (start[1] - position[1]) * metersPerDegreeX;
  const startY = (start[0] - position[0]) * metersPerDegreeY;
  const endX = (end[1] - position[1]) * metersPerDegreeX;
  const endY = (end[0] - position[0]) * metersPerDegreeY;
  const dx = endX - startX;
  const dy = endY - startY;
  const lengthSquared = dx * dx + dy * dy;
  const ratio = lengthSquared
    ? Math.max(
        0,
        Math.min(
          1,
          -(startX * dx + startY * dy) / lengthSquared,
        ),
      )
    : 0;
  const x = startX + ratio * dx;
  const y = startY + ratio * dy;

  return {
    ratio,
    distance: Math.hypot(x, y),
    point: [
      position[0] + y / metersPerDegreeY,
      position[1] + x / metersPerDegreeX,
    ],
  };
}

export function pointAt(route, distance) {
  const { points, cumulative, total } = route;
  if (!points.length) return null;

  const target = Math.max(0, Math.min(total, distance));
  let low = 0;
  let high = cumulative.length - 1;

  while (low < high - 1) {
    const middle = (low + high) >> 1;
    if (cumulative[middle] <= target) low = middle;
    else high = middle;
  }

  const segmentLength = cumulative[high] - cumulative[low];
  const ratio = segmentLength
    ? (target - cumulative[low]) / segmentLength
    : 0;

  return [
    points[low][0] + (points[high][0] - points[low][0]) * ratio,
    points[low][1] + (points[high][1] - points[low][1]) * ratio,
  ];
}

export function snapToRoute(route, rawPosition, hint = null) {
  const position = toLatLng(rawPosition);
  if (!position || !route || route.points.length < 2) return null;

  const search = (from, to) => {
    let best = null;
    const start = Math.max(0, from);
    const end = Math.min(route.points.length - 1, to);

    for (let index = start; index < end; index += 1) {
      const projection = projectOnSegment(
        route.points[index],
        route.points[index + 1],
        position,
      );
      if (!best || projection.distance < best.distance) {
        best = { ...projection, index };
      }
    }

    return best;
  };

  let best =
    hint == null
      ? search(0, route.points.length - 1)
      : search(hint - 5, hint + 80);
  if (!best || (hint != null && best.distance > 60)) {
    best = search(0, route.points.length - 1);
  }
  if (!best) return null;

  const segmentLength =
    route.cumulative[best.index + 1] -
    route.cumulative[best.index];
  const alongM =
    route.cumulative[best.index] + best.ratio * segmentLength;
  const ahead = pointAt(route, alongM + 25);

  return {
    point: best.point,
    index: best.index,
    alongM,
    offM: best.distance,
    heading:
      ahead && haversine(best.point, ahead) > 1
        ? bearing(best.point, ahead)
        : null,
  };
}

export function splitRoute(route, snap) {
  if (!route || !snap) return null;

  return {
    passed: [
      ...route.points.slice(0, snap.index + 1),
      snap.point,
    ],
    ahead: [snap.point, ...route.points.slice(snap.index + 1)],
  };
}

export function stagesAlongRoute(route, stages) {
  if (!route || !stages) return [];

  return stages
    .map((stage) => {
      const position = toLatLng(stage.position ?? stage);
      const snap = position && snapToRoute(route, position);
      if (!snap || snap.offM > 150) return null;

      return {
        stage,
        name: stage.name ?? stage.stage_name ?? stage.title ?? 'Stage',
        alongM: snap.alongM,
      };
    })
    .filter(Boolean)
    .sort((a, b) => a.alongM - b.alongM);
}

export function nextStageAhead(stageList, alongM, speedKmh) {
  const next = stageList.find((stage) => stage.alongM > alongM + 15);
  if (!next) return null;

  const distanceM = next.alongM - alongM;
  const metersPerSecond = Math.max(speedKmh, 15) / 3.6;

  return {
    name: next.name,
    stage: next.stage,
    distanceM,
    etaMin: Math.max(
      1,
      Math.round(distanceM / metersPerSecond / 60),
    ),
  };
}

export function speedToZoom(speedKmh, distanceToStageM = null) {
  let zoom =
    speedKmh < 5
      ? 18
      : speedKmh < 25
        ? 17.5
        : speedKmh < 50
          ? 17
          : speedKmh < 80
            ? 16.5
            : 16;

  if (distanceToStageM != null && distanceToStageM < 150) {
    zoom = 18;
  }

  return zoom;
}

export function formatDistance(meters) {
  return meters < 1000
    ? `${Math.round(meters / 10) * 10} m`
    : `${(meters / 1000).toFixed(1)} km`;
}
