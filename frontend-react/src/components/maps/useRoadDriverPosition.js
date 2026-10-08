import { useEffect, useMemo, useRef, useState } from 'react';

function haversineKm(a, b) {
  if (!a || !b) return null;

  const R = 6371;
  const dLat = ((b[0] - a[0]) * Math.PI) / 180;
  const dLon = ((b[1] - a[1]) * Math.PI) / 180;
  const lat1 = (a[0] * Math.PI) / 180;
  const lat2 = (b[0] * Math.PI) / 180;

  const value =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) *
      Math.cos(lat2) *
      Math.sin(dLon / 2) ** 2;

  return (
    R *
    2 *
    Math.atan2(
      Math.sqrt(value),
      Math.sqrt(1 - value),
    )
  );
}

function buildCumulative(geometry) {
  if (!geometry || geometry.length < 2) return null;

  const cumulative = [0];

  for (let i = 1; i < geometry.length; i += 1) {
    cumulative.push(
      cumulative[i - 1] +
        (haversineKm(
          geometry[i - 1],
          geometry[i],
        ) || 0),
    );
  }

  return cumulative;
}

function snapToRoute(geometry, point) {
  if (!geometry || geometry.length < 2 || !point) {
    return null;
  }

  const kx =
    111.32 *
    Math.cos((point[0] * Math.PI) / 180);

  const ky = 110.574;

  let best = null;

  for (let i = 0; i < geometry.length - 1; i += 1) {
    const a = geometry[i];
    const b = geometry[i + 1];

    const ax =
      (a[1] - point[1]) * kx;

    const ay =
      (a[0] - point[0]) * ky;

    const bx =
      (b[1] - point[1]) * kx;

    const by =
      (b[0] - point[0]) * ky;

    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy;

    const t = len2
      ? Math.max(
          0,
          Math.min(
            1,
            -(ax * dx + ay * dy) / len2,
          ),
        )
      : 0;

    const distance = Math.hypot(
      ax + t * dx,
      ay + t * dy,
    );

    if (!best || distance < best.distKm) {
      best = {
        distKm: distance,
        index: i,
        t,
      };
    }
  }

  return best;
}

function pointAtDistance(
  geometry,
  cumulative,
  distance,
) {
  const total =
    cumulative[cumulative.length - 1];

  const d = Math.max(
    0,
    Math.min(total, distance),
  );

  let lo = 0;
  let hi = cumulative.length - 1;

  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;

    if (cumulative[mid] <= d) {
      lo = mid;
    } else {
      hi = mid;
    }
  }

  const a = geometry[lo];
  const b = geometry[lo + 1];

  const segment =
    cumulative[lo + 1] -
    cumulative[lo];

  const t =
    segment > 0
      ? (d - cumulative[lo]) / segment
      : 0;

  const lat =
    a[0] + (b[0] - a[0]) * t;

  const lng =
    a[1] + (b[1] - a[1]) * t;

  const heading =
    (Math.atan2(
      (b[1] - a[1]) *
        Math.cos((a[0] * Math.PI) / 180),
      b[0] - a[0],
    ) *
      180) /
    Math.PI;

  return {
    position: [lat, lng],
    heading: (heading + 360) % 360,
  };
}

export function useRoadDriverPosition(target, geometry) {
  const cumulative = useMemo(
    () => buildCumulative(geometry),
    [geometry],
  );

  const [state, setState] = useState({
    position: target || null,
    heading: 0,
  });

  const segRef = useRef(null); // { from, to, start, dur }
  const shownRef = useRef(null);
  const lastGoalAtRef = useRef(0);
  const backCountRef = useRef(0);
  const geomRef = useRef({ geometry, cumulative });

  useEffect(() => {
    geomRef.current = { geometry, cumulative };
  }, [geometry, cumulative]);

  const targetKey = target ? JSON.stringify(target) : null;

  // New GPS reading: only ever moves the goal FORWARD.
  useEffect(() => {
    const { geometry: g, cumulative: c } = geomRef.current;

    if (!target || !g || g.length < 2 || !c) {
      if (target) {
        setState((prev) => ({
          position: target,
          heading: prev.heading,
        }));
      }
      return;
    }

    const snap = snapToRoute(g, target);
    if (!snap) return;

    const d =
      c[snap.index] +
      snap.t * (c[snap.index + 1] - c[snap.index]);
    const now = performance.now();

    const jumpTo = () => {
      segRef.current = { from: d, to: d, start: now, dur: 1 };
      shownRef.current = d;
      lastGoalAtRef.current = now;
      backCountRef.current = 0;
      setState(pointAtDistance(g, c, d));
    };

    // First reading.
    if (!segRef.current) {
      jumpTo();
      return;
    }

    const goal = segRef.current.to;
    const shown = shownRef.current;

    // Same reading again (e.g. route object re-created): do nothing.
    if (Math.abs(d - goal) < 1e-9) return;

    if (d > goal) {
      backCountRef.current = 0;

      // Huge forward jump: snap.
      if (d - shown > 2) {
        jumpTo();
        return;
      }

      // Glide at constant speed, over the time since the last reading.
      const dur = Math.min(
        Math.max(now - lastGoalAtRef.current, 1000),
        6000,
      );
      lastGoalAtRef.current = now;
      segRef.current = { from: shown, to: d, start: now, dur };
      return;
    }

    // Reading is BEHIND the bus: ignore it unless it keeps happening.
    backCountRef.current += 1;
    if (backCountRef.current >= 4) jumpTo();
  }, [targetKey, geometry, cumulative]);

  // One animation loop for the whole lifetime of the map.
  useEffect(() => {
    let frame;

    const step = (time) => {
      const seg = segRef.current;
      const { geometry: g, cumulative: c } = geomRef.current;

      if (seg && g && c && shownRef.current !== seg.to) {
        const p = Math.min(
          1,
          Math.max(0, (time - seg.start) / seg.dur),
        );
        const next =
          p >= 1 ? seg.to : seg.from + (seg.to - seg.from) * p;

        shownRef.current = next;
        setState(pointAtDistance(g, c, next));
      }

      frame = window.requestAnimationFrame(step);
    };

    frame = window.requestAnimationFrame(step);
    return () => window.cancelAnimationFrame(frame);
  }, []);

  return state;
}

