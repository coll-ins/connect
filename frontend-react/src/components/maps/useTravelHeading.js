import { useEffect, useRef, useState } from 'react';

const MIN_MOVE_M = 8;

function metres(a, b) {
  const kx = 111320 * Math.cos((a[0] * Math.PI) / 180);
  return Math.hypot((b[1] - a[1]) * kx, (b[0] - a[0]) * 110574);
}

function bearing(a, b) {
  const h =
    (Math.atan2((b[1] - a[1]) * Math.cos((a[0] * Math.PI) / 180), b[0] - a[0]) * 180) / Math.PI;
  return (h + 360) % 360;
}

/*
 * Which way the bus is actually travelling, from where it has just been.
 * Used when the bus is off its planned route: the route's own direction is
 * wrong there, and phones often report no compass heading while moving slowly.
 * Returns null until the bus has moved far enough to tell.
 */
export default function useTravelHeading(position, gpsHeading) {
  const last = useRef(null);
  const [heading, setHeading] = useState(null);
  const lat = position?.[0];
  const lng = position?.[1];

  useEffect(() => {
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
    const now = [lat, lng];
    if (last.current && metres(last.current, now) >= MIN_MOVE_M) {
      setHeading(bearing(last.current, now));
      last.current = now;
    } else if (!last.current) {
      last.current = now;
    }
  }, [lat, lng]);

  if (heading != null) return heading;
  return Number.isFinite(gpsHeading) ? gpsHeading : null;
}
