import { useEffect, useRef, useState } from 'react';
import { apiRequest } from '../../api';
import {
  distanceFromLineKm,
  geoJsonLinePositions,
} from '../../pages/passenger/liveMapUtils';

const OFF_ROUTE_CONFIRM_MS = 15000;
const MIN_REQUEST_GAP_MS = 20000;
const CHECK_EVERY_MS = 3000;
const DRIFT_FROM_NEW_ROAD_KM = 0.08;

/*
 * Once the bus has stayed off its route for a while, ask the server for the
 * road from where the bus is now to the next goal (`url` names the endpoint).
 * Asks again only if the bus leaves that new road or the goal changes.
 */
export default function useBusReroute({
  url,
  offRoute,
  goal,
  busPosition,
}) {
  const [reroute, setReroute] = useState(null);
  const latestRef = useRef({ url, goal, busPosition });

  useEffect(() => {
    latestRef.current = { url, goal, busPosition };
  }, [url, goal, busPosition]);

  useEffect(() => {
    if (!offRoute) {
      setReroute(null);
      return undefined;
    }

    const offSince = Date.now();
    let active = true;
    let inFlight = false;
    let lastRequest = 0;
    let current = null;

    const check = async () => {
      const now = Date.now();
      const latest = latestRef.current;

      if (
        inFlight ||
        !latest.url ||
        !latest.busPosition ||
        now - offSince < OFF_ROUTE_CONFIRM_MS ||
        now - lastRequest < MIN_REQUEST_GAP_MS
      ) {
        return;
      }

      if (
        current?.goal === latest.goal &&
        distanceFromLineKm(latest.busPosition, current.line) <=
          DRIFT_FROM_NEW_ROAD_KM
      ) {
        return;
      }

      inFlight = true;
      lastRequest = now;

      try {
        const data = await apiRequest(latest.url, {
          silent: true,
          timeoutMs: 15000,
        });
        const line = geoJsonLinePositions(data?.geometry);

        if (active && line.length > 1) {
          current = { goal: latest.goal, line };
          setReroute(current);
        }
      } catch {
        // The planned route is still on the map; try again on a later check.
      } finally {
        inFlight = false;
      }
    };

    const timer = window.setInterval(check, CHECK_EVERY_MS);

    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [offRoute]);

  return offRoute ? reroute : null;
}
