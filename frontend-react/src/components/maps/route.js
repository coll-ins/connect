const R = 6371000, D = Math.PI / 180;

export function buildRoute(geometry) {
  const pts = (geometry?.coordinates || []).map(([lng, lat]) => [lat, lng]);
  const cum = [0];
  for (let i = 1; i < pts.length; i++) {
    const k = Math.cos(pts[i][0] * D);
    const dx = (pts[i][1] - pts[i - 1][1]) * D * R * k;
    const dy = (pts[i][0] - pts[i - 1][0]) * D * R;
    cum.push(cum[i - 1] + Math.hypot(dx, dy));
  }
  return { pts, cum, length: cum[cum.length - 1] || 0 };
}

// nearest point on the route to (lat,lng); optional window [fromS,toS] in metres
export function snapToRoute(route, lat, lng, fromS = 0, toS = Infinity) {
  const { pts, cum } = route;
  const k = Math.cos(lat * D);
  let best = null;
  for (let i = 0; i < pts.length - 1; i++) {
    if (cum[i + 1] < fromS || cum[i] > toS) continue;
    const ax = (pts[i][1] - lng) * D * R * k, ay = (pts[i][0] - lat) * D * R;
    const bx = (pts[i + 1][1] - lng) * D * R * k, by = (pts[i + 1][0] - lat) * D * R;
    const dx = bx - ax, dy = by - ay, len2 = dx * dx + dy * dy;
    let t = len2 ? -(ax * dx + ay * dy) / len2 : 0;
    t = Math.max(0, Math.min(1, t));
    const d = Math.hypot(ax + dx * t, ay + dy * t);
    if (!best || d < best.dist) {
      best = {
        dist: d,
        s: cum[i] + (cum[i + 1] - cum[i]) * t,
        lat: pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t,
        lng: pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t,
      };
    }
  }
  return best;
}

export function pointAt(route, s) {
  const { pts, cum, length } = route;
  s = Math.max(0, Math.min(length, s));
  let lo = 0, hi = cum.length - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (cum[m] <= s) lo = m; else hi = m; }
  const seg = cum[hi] - cum[lo] || 1;
  const t = (s - cum[lo]) / seg;
  return [
    pts[lo][0] + (pts[hi][0] - pts[lo][0]) * t,
    pts[lo][1] + (pts[hi][1] - pts[lo][1]) * t,
  ];
}

export function bearing(a, b) {
  const k = Math.cos(a[0] * D);
  return (Math.atan2((b[1] - a[1]) * k, b[0] - a[0]) / D + 360) % 360;
}

// heading over a short look-behind/ahead window, so turns rotate smoothly
export function headingAt(route, s) {
  return bearing(pointAt(route, s - 8), pointAt(route, s + 12));
}

// stages snapped onto the route
export function snapStages(route, stages) {
  return (stages || []).map((st) => {
    const lat = Number(st.latitude ?? st.lat), lng = Number(st.longitude ?? st.lng ?? st.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lng) || route.pts.length < 2) {
      return { ...st, snapped: false, lat, lng };
    }
    const sn = snapToRoute(route, lat, lng);
    if (sn.dist > 100) {
      console.warn(`Stage "${st.name}" is ${Math.round(sn.dist)} m from the route: bad stage coordinates in the DB`);
    }
    return { ...st, snapped: true, lat: sn.lat, lng: sn.lng, offsetM: sn.dist };
  });
}
