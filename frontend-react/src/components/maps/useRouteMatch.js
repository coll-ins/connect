import { useMemo } from 'react';
import {
  buildRoute,
  snapToRoute,
  splitRoute,
  toLatLng,
} from './wazeNav';

const MAX_SNAP_DISTANCE_M = 40;

export default function useRouteMatch(routePositions, rawPosition) {
  const route = useMemo(
    () =>
      routePositions?.length > 1
        ? buildRoute(routePositions)
        : null,
    [routePositions],
  );
  const position = toLatLng(rawPosition);
  const latitude = position?.[0];
  const longitude = position?.[1];

  return useMemo(() => {
    if (latitude == null || longitude == null) return null;

    const raw = [latitude, longitude];
    if (!route) {
      return {
        position: raw,
        heading: null,
        alongM: null,
        onRoute: false,
        route: null,
        split: null,
      };
    }

    const snap = snapToRoute(route, raw);
    if (!snap || snap.offM > MAX_SNAP_DISTANCE_M) {
      return {
        position: raw,
        heading: null,
        alongM: snap?.alongM ?? null,
        onRoute: false,
        route,
        split: null,
      };
    }

    return {
      position: snap.point,
      heading: snap.heading,
      alongM: snap.alongM,
      onRoute: true,
      route,
      split: splitRoute(route, snap),
    };
  }, [route, latitude, longitude]);
}
