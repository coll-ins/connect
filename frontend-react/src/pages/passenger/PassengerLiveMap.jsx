import 'leaflet/dist/leaflet.css';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { MapContainer, Marker, Popup, Polyline, useMap } from 'react-leaflet';
import BaseTileLayer from '../../components/maps/BaseTileLayer';
import L from 'leaflet';
import { ArrowLeft, LocateFixed, Navigation, Radio } from 'lucide-react';
import { API_HOST, apiRequest } from '../../api';
import Notice, { NoticeStack } from '../../components/ui/Notice';
import './PassengerLiveMap.css';
import TiltedMapFrame, {
  MAP_TILT_ENABLED,
  MAP_TILT_ZOOM,
} from '../../components/maps/TiltedMapFrame';
import SmartFollow from '../../components/maps/SmartFollow';
import {
  MapZoomButtons,
  NextStageBanner,
} from '../../components/maps/MapNavOverlays';
import RouteProgress from '../../components/maps/RouteProgress';
import useBusReroute from '../../components/maps/useBusReroute';
import useRouteMatch from '../../components/maps/useRouteMatch';
import { useRoadDriverPosition } from '../../components/maps/useRoadDriverPosition';
import { nextStageAhead, stagesAlongRoute } from '../../components/maps/wazeNav';
import { buildRoute as buildRoadRoute, snapToRoute as snapPointToRoute } from '../../components/maps/route';
import { stopIcon } from '../../components/maps/StopMarker';
import {
  estimateBusSpeedKmh,
  OFF_ROUTE_KM,
  distanceFromLineKm,
  lineAheadOfBus,
  lineLengthKm,
  parkedBusLabel,
  tripGuide,
  planParkedBus,
  recordDriverPosition,
} from './liveMapUtils';

function normalizePosition(value) {
  if (!value) return null;

  const latitude = Number(value.latitude ?? value.lat);
  const longitude = Number(value.longitude ?? value.lng ?? value.lon);

  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
    return null;
  }

  return [latitude, longitude];
}

function routePositions(geometry) {
  const coordinates = geometry?.coordinates;

  if (!Array.isArray(coordinates)) return [];

  return coordinates
    .map((point) => {
      if (!Array.isArray(point) || point.length < 2) return null;

      const lng = Number(point[0]);
      const lat = Number(point[1]);

      if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;

      return [lat, lng];
    })
    .filter(Boolean);
}


function haversineKm(a, b) {
  if (!a || !b) return null;

  const R = 6371;
  const dLat = ((b[0] - a[0]) * Math.PI) / 180;
  const dLon = ((b[1] - a[1]) * Math.PI) / 180;
  const lat1 = (a[0] * Math.PI) / 180;
  const lat2 = (b[0] * Math.PI) / 180;

  const value =
    Math.sin(dLat / 2) ** 2 +
    Math.sin(dLon / 2) ** 2 * Math.cos(lat1) * Math.cos(lat2);

  return R * 2 * Math.atan2(
    Math.sqrt(value),
    Math.sqrt(1 - value)
  );
}

function nearestRouteIndex(position, positions) {
  if (!position || !positions.length) return -1;

  let nearest = 0;
  let best = Infinity;

  positions.forEach((point, index) => {
    const distance = haversineKm(position, point);

    if (distance != null && distance < best) {
      best = distance;
      nearest = index;
    }
  });

  return nearest;
}

function routeDistanceKm(positions, startIndex, endIndex) {
  if (
    positions.length < 2 ||
    startIndex < 0 ||
    endIndex < 0
  ) {
    return 0;
  }

  const start = Math.min(startIndex, endIndex);
  const end = Math.max(startIndex, endIndex);

  let total = 0;

  for (let i = start; i < end; i += 1) {
    total += haversineKm(
      positions[i],
      positions[i + 1]
    ) || 0;
  }

  return total;
}

function formatDistance(km) {
  if (km == null || !Number.isFinite(km)) return '—';

  if (km < 1) {
    return `${Math.max(0, Math.round(km * 1000))} m`;
  }

  return `${km.toFixed(km < 10 ? 1 : 0)} km`;
}

function formatEta(minutes) {
  if (minutes == null || !Number.isFinite(minutes)) return '—';

  if (minutes <= 1) return '1 min';

  return `${Math.round(minutes)} min`;
}

function MapResize() {
  const map = useMap();

  useEffect(() => {
    const refresh = () => map.invalidateSize({ pan: false });
    const timer = window.setTimeout(refresh, 150);
    const container = map.getContainer();
    let observer = null;

    if (typeof ResizeObserver !== 'undefined' && container) {
      observer = new ResizeObserver(refresh);
      observer.observe(container);
    }

    return () => {
      window.clearTimeout(timer);
      if (observer) observer.disconnect();
    };
  }, [map]);

  return null;
}


function MapRoute({ positions }) {
  const map = useMap();
  const fittedRouteRef = useRef('');

  useEffect(() => {
    if (!positions || positions.length < 2) return;

    const first = positions[0];
    const last = positions[positions.length - 1];

    const routeKey = [
      positions.length,
      first?.[0],
      first?.[1],
      last?.[0],
      last?.[1],
    ].join('|');

    if (fittedRouteRef.current === routeKey) return;

    fittedRouteRef.current = routeKey;

    const bounds = L.latLngBounds(positions);

    if (!bounds.isValid()) return;

    const timer = window.setTimeout(() => {
      map.invalidateSize({ pan: false });

      map.fitBounds(bounds, {
        paddingTopLeft: [40, 120],
        paddingBottomRight: [40, 120],
        maxZoom: 13,
        animate: false,
      });
    }, 250);

    return () => window.clearTimeout(timer);
  }, [map, positions]);

  return null;
}

function MapFollow({ position }) {
  const map = useMap();

  useEffect(() => {
    if (!position) return;

    map.flyTo(position, Math.max(map.getZoom(), 15), {
      animate: true,
      duration: 0.8,
    });
  }, [map, position]);

  return null;
}

function createVehicleIcon({ label = null, heading = null } = {}) {
  const parked = label != null;
  const busStyle = Number.isFinite(heading)
    ? ` style="transform: rotate(${heading}deg)"`
    : '';
  const labelHtml = parked
    ? `<div class="passenger-vehicle-marker__parked-label">${label}</div>`
    : '';

  return L.divIcon({
    className: `passenger-vehicle-marker${parked ? ' is-parked' : ''}`,
    html: `
      <div class="passenger-vehicle-marker__scene">
        ${labelHtml}
        <div class="passenger-vehicle-marker__shadow"></div>
        <div class="passenger-vehicle-marker__glow"></div>

        <div class="passenger-vehicle-marker__bus"${busStyle}>
          <div class="passenger-vehicle-marker__roof"></div>
          <div class="passenger-vehicle-marker__windshield"></div>

          <div class="passenger-vehicle-marker__side-window one"></div>
          <div class="passenger-vehicle-marker__side-window two"></div>
          <div class="passenger-vehicle-marker__side-window three"></div>

          <div class="passenger-vehicle-marker__bumper"></div>

          <div class="passenger-vehicle-marker__lamp left"></div>
          <div class="passenger-vehicle-marker__lamp right"></div>

          <div class="passenger-vehicle-marker__wheel left"></div>
          <div class="passenger-vehicle-marker__wheel right"></div>
        </div>
      </div>
    `,
    iconSize: [82, 82],
    iconAnchor: [41, 41],
    popupAnchor: [0, -42],
  });
}

function createPassengerIcon() {
  return L.divIcon({
    className: 'passenger-location-marker',
    html: `
      <div class="passenger-location-marker__wrap">
        <div class="passenger-location-marker__shadow"></div>
        <div class="passenger-location-marker__pin">
          <div class="passenger-location-marker__core"></div>
        </div>
      </div>
    `,
    iconSize: [58, 70],
    iconAnchor: [29, 63],
    popupAnchor: [0, -58],
  });
}

const vehicleIcon = createVehicleIcon();
const passengerIcon = createPassengerIcon();

/*
 * ------------------------------------------------------------
 * LIVE WEBSOCKET PUSH
 * ------------------------------------------------------------
 * The backend pushes a 'location' frame on every driver GPS save
 * (BookingLiveConsumer). The socket is a fast path only: HTTP
 * polling stays as the safety net for the full envelope (stages,
 * incidents, trip status), so a dropped socket never breaks the map.
 */
function useLiveSocket(bookingId, onLocation, enabled) {
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!bookingId || !enabled) {
      setConnected(false);
      return undefined;
    }

    let socket = null;
    let closed = false;
    let retryTimer = null;
    let attempt = 0;

    const scheduleRetry = () => {
      if (closed) return;
      attempt += 1;
      retryTimer = window.setTimeout(connect, Math.min(1000 * attempt, 5000));
    };

    const connect = () => {
      if (closed) return;

      const scheme =
        window.location.protocol === 'https:' ? 'wss' : 'ws';
      const url = `${scheme}://${import.meta.env.VITE_WS_HOST || API_HOST || window.location.host}/ws/bookings/${bookingId}/live/`;

      try {
        socket = new WebSocket(url);
      } catch {
        scheduleRetry();
        return;
      }

      socket.onopen = () => {
        attempt = 0;
        setConnected(true);
      };

      socket.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg && msg.type === 'location') onLocation(msg);
        } catch {
          // A malformed frame must never break the live map.
        }
      };

      socket.onerror = () => {
        try {
          socket.close();
        } catch {
          // ignore
        }
      };

      socket.onclose = () => {
        setConnected(false);
        if (!closed) scheduleRetry();
      };
    };

    connect();

    return () => {
      closed = true;
      window.clearTimeout(retryTimer);
      setConnected(false);
      if (socket) {
        socket.onopen = null;
        socket.onmessage = null;
        socket.onerror = null;
        socket.onclose = null;
        try {
          socket.close();
        } catch {
          // ignore
        }
      }
    };
  }, [bookingId, enabled, onLocation]);

  return connected;
}


function createPickupIcon(label) {
  const safe = String(label || 'Pickup')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

  return L.divIcon({
    className: 'connect-pickup-pin',
    html: `
      <div style="display:flex;flex-direction:column;align-items:center;width:200px">
        <div style="width:46px;height:46px;border-radius:50%;background:#dc2626;border:4px solid #fff;box-shadow:0 0 0 4px rgba(220,38,38,.3),0 5px 14px rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center">
          <div style="width:14px;height:14px;border-radius:50%;background:#fff"></div>
        </div>
        <div style="margin-top:8px;padding:6px 12px;border-radius:9px;background:#fff;border:2px solid #111827;color:#111827;font:900 13px Arial,sans-serif;white-space:nowrap;box-shadow:0 3px 10px rgba(0,0,0,.3)">${safe}</div>
      </div>
    `,
    iconSize: [200, 90],
    iconAnchor: [100, 23],
    popupAnchor: [0, -23],
  });
}

export default function PassengerLiveMap({
  bookingId,
  bookingDetails = null,
  trackingAvailable = true,
  routeGeometry: bookingRouteGeometry = null,
  pickup: bookingPickup = null,
  onBack,
  onTripChange,
}) {
  const [live, setLive] = useState(null);
  const [loading, setLoading] = useState(trackingAvailable);
  const [error, setError] = useState('');
  const [locationError, setLocationError] = useState('');
  const [following, setFollowing] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(true);
  const [driverHistory, setDriverHistory] = useState([]);
  const [clockNow, setClockNow] = useState(0);
  const pickupAlertSentRef = useRef(false);

  useEffect(() => {
    const updateClock = () => setClockNow(Date.now());
    updateClock();
    const timer = window.setInterval(updateClock, 10000);

    return () => window.clearInterval(timer);
  }, []);


  const loadLive = useCallback(async () => {
    if (!trackingAvailable) {
      setLoading(false);
      return;
    }

    if (!bookingId) {
      setLoading(false);
      setError('No active trip selected.');
      return;
    }

    try {
      const data = await apiRequest(
        `/bookings/${bookingId}/live-location/`
      );

      const now = Date.now();

      setDriverHistory((previous) =>
        recordDriverPosition(previous, data?.driver, now),
      );

      setLive({ ...data, _fetchedAt: now });
      setError('');
    } catch (err) {
      setError(err.message || 'Unable to load live trip location.');
      // The server says this trip can no longer be tracked, usually because
      // it just ended, so let the page find out what happened.
      if (err.status === 409) onTripChange?.();
    } finally {
      setLoading(false);
    }
  }, [bookingId, trackingAvailable, onTripChange]);

  /*
   * Merge one pushed location frame into the polled envelope.
   * Only the moving parts (driver/passenger coordinates + freshness)
   * come from the socket; route, stages and incidents stay on HTTP.
   */
  const applyLivePush = useCallback((msg) => {
    setLive((prev) => {
      if (!prev) return prev; // wait for the first full HTTP payload

      const now = Date.now();

      return {
        ...prev,
        driver: { ...(prev.driver || {}), ...(msg.driver || {}) },
        passenger: { ...(prev.passenger || {}), ...(msg.passenger || {}) },
        distance_km:
          typeof msg.distance_km === 'number'
            ? msg.distance_km
            : prev.distance_km,
        is_stale:
          typeof msg.is_stale === 'boolean'
            ? msg.is_stale
            : prev.is_stale,
        location_age_seconds:
          typeof msg.location_age_seconds === 'number'
            ? msg.location_age_seconds
            : prev.location_age_seconds,
        is_trip_live:
          typeof msg.is_trip_live === 'boolean'
            ? msg.is_trip_live
            : prev.is_trip_live,
        _fetchedAt: now,
      };
    });

    setDriverHistory((previous) =>
      recordDriverPosition(previous, msg.driver),
    );
  }, []);

  const socketConnected = useLiveSocket(
    bookingId,
    applyLivePush,
    trackingAvailable,
  );

  useEffect(() => {
    if (!trackingAvailable) return undefined;

    loadLive();

    // Socket live: polls slow to a 10s safety net for the full
    // envelope (stages/incidents/status). Socket down: fast 2s polls.
    const interval = socketConnected ? 10000 : 2000;
    const timer = window.setInterval(loadLive, interval);

    return () => window.clearInterval(timer);
  }, [loadLive, socketConnected, trackingAvailable]);

  useEffect(() => {
    if (!bookingId || !trackingAvailable) {
      return undefined;
    }

    if (!navigator.geolocation) {
      setLocationError(
        'Location sharing is not available in this browser. You can still view your trip.',
      );
      return undefined;
    }

    let active = true;
    let lastSent = 0;

    const sendLocation = (position) => {
      if (!active) return;
      setLocationError('');

      const now = Date.now();

      if (now - lastSent < 10000) {
        return;
      }

      lastSent = now;

      apiRequest(`/bookings/${bookingId}/location/`, {
        method: 'POST',
        body: {
          latitude: Number(
            position.coords.latitude.toFixed(6)
          ),
          longitude: Number(
            position.coords.longitude.toFixed(6)
          ),
        },
      }).catch((err) => {
        if (active) {
          setLocationError(
            err.message || "We couldn't share your location. Check your internet connection and try again.",
          );
        }
      });
    };

    const handleLocationError = (locationFailure) => {
      if (!active) return;
      setLocationError(
        locationFailure.code === 1
          ? 'Location access is blocked. Allow location access in your browser settings to show your position.'
          : "We couldn't get your location. Check your device's location settings and try again.",
      );
    };

    navigator.geolocation.getCurrentPosition(
      sendLocation,
      handleLocationError,
      {
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 10000,
      }
    );

    const watchId = navigator.geolocation.watchPosition(
      sendLocation,
      handleLocationError,
      {
        enableHighAccuracy: true,
        timeout: 15000,
        maximumAge: 10000,
      }
    );

    return () => {
      active = false;
      navigator.geolocation.clearWatch(watchId);
    };
  }, [bookingId, trackingAvailable]);

  const passengerPosition = useMemo(
    () => normalizePosition(live?.passenger),
    [live]
  );

  const geometry = useMemo(() => {
    const source =
      bookingRouteGeometry ||
      live?.route_geometry ||
      live?.active_trip?.route_geometry ||
      live?.active_trip?.route?.geometry ||
      live?.trip?.route_geometry ||
      live?.trip?.route?.geometry ||
      live?.route_geometry?.geometry ||
      live?.route?.geometry ||
      live?.route?.route_geometry;

    return routePositions(source);
  }, [bookingRouteGeometry, live]);


  const driverTarget = useMemo(
    () => normalizePosition(live?.driver),
    [live]
  );

  const {
    position: driverPosition,
    heading: driverHeading,
  } = useRoadDriverPosition(
    driverTarget,
    geometry
  );

  const [incidentBusy, setIncidentBusy] = useState(false);
  const [incidentMsg, setIncidentMsg] = useState('');

  const [tripChoices, setTripChoices] = useState(null);

  const loadReplacementTrips = async () => {
    if (!bookingId) return;
    setIncidentBusy(true);

    try {
      const list = await apiRequest(
        `/bookings/${bookingId}/replacement-trips/`,
      );
      setTripChoices(Array.isArray(list) ? list : []);
    } catch (err) {
      setIncidentMsg(err.message || 'Unable to load other trips.');
    } finally {
      setIncidentBusy(false);
    }
  };

  const requestReschedule = async (tripId) => {
    if (!bookingId) return;
    if (!window.confirm('Move your booking to this trip?')) return;

    setIncidentBusy(true);

    try {
      const res = await apiRequest(
        `/bookings/${bookingId}/resolve-incident/`,
        {
          method: 'POST',
          body: { resolution: 'reschedule', replacement_trip_id: tripId },
        },
      );
      setIncidentMsg(res?.message || 'Your booking was moved to the new trip.');
      setTripChoices(null);
      await loadLive();
    } catch (err) {
      setIncidentMsg(err.message || 'Unable to move your booking.');
    } finally {
      setIncidentBusy(false);
    }
  };

  const requestIncidentRefund = async () => {
    if (!bookingId) return;
    if (!window.confirm('Cancel your booking and request a refund?')) return;

    setIncidentBusy(true);

    try {
      const res = await apiRequest(
        `/bookings/${bookingId}/resolve-incident/`,
        { method: 'POST', body: { resolution: 'refund' } },
      );
      setIncidentMsg(res?.message || 'Refund requested.');
      await loadLive();
    } catch (err) {
      setIncidentMsg(err.message || 'Unable to request a refund.');
    } finally {
      setIncidentBusy(false);
    }
  };

  const vehicleMarkerRef = useRef(null);
  const vehicleHeadingRef = useRef(0);

  const routeMatch = useRouteMatch(geometry, driverTarget);
  const matchedDriverPosition = routeMatch?.onRoute
    ? driverPosition
    : routeMatch?.position ?? driverPosition;
  const gpsHeading = Number(live?.driver?.heading);
  const matchedDriverHeading =
    routeMatch?.onRoute && routeMatch.heading != null
      ? routeMatch.heading
      : Number.isFinite(gpsHeading)
        ? gpsHeading
        : driverHeading;

  useEffect(() => {
    if (!Number.isFinite(matchedDriverHeading)) return;

    const markerElement =
      vehicleMarkerRef.current?.getElement?.();
    const vehicle = markerElement?.querySelector(
      '.passenger-vehicle-marker__bus',
    );
    if (!vehicle) return;

    const previous = vehicleHeadingRef.current;
    const diff =
      ((matchedDriverHeading - previous + 540) % 360) - 180;
    const next = previous + diff;

    vehicleHeadingRef.current = next;
    vehicle.style.transformOrigin = 'center center';
    vehicle.style.transition = 'transform 0.35s ease-out';
    vehicle.style.transform = `rotate(${next}deg)`;
  }, [matchedDriverHeading, matchedDriverPosition]);


  const liveStages = live?.stages;
  const rawStages = useMemo(
    () => (Array.isArray(liveStages) ? liveStages : []),
    [liveStages],
  );

  // Snap every stage onto the road geometry so pins sit on the route.
  const stages = useMemo(() => {
    if (!Array.isArray(geometry) || geometry.length < 2) return rawStages;
    const road = buildRoadRoute({
      coordinates: geometry.map((p) => (Array.isArray(p) ? [p[1], p[0]] : [p.lng ?? p.lon, p.lat])),
    });
    return rawStages.map((s) => {
      const pos = normalizePosition(s);
      if (!pos) return s;
      const sn = snapPointToRoute(road, pos[0], pos[1]);
      if (!sn || sn.dist > 150) return s;
      return { ...s, latitude: sn.lat, longitude: sn.lng, lat: sn.lat, lng: sn.lng };
    });
  }, [rawStages, geometry]);
  const stagesOnRoute = useMemo(
    () => stagesAlongRoute(routeMatch?.route, stages),
    [routeMatch?.route, stages],
  );

  const pickupStage = useMemo(() => {
    const candidates = [live?.pickup, bookingPickup].filter(Boolean);

    const located = candidates.find(
      (item) => item.latitude != null && item.longitude != null,
    );

    if (located) return located;

    const wanted = String(
      candidates.find((item) => item.name)?.name || '',
    )
      .trim()
      .toLowerCase();

    if (!wanted) return null;

    return (
      stages.find(
        (stage) =>
          String(stage.name || '').trim().toLowerCase() === wanted,
      ) || null
    );
  }, [live, bookingPickup, stages]);

  const pickupPosition = useMemo(
    () => normalizePosition(pickupStage),
    [pickupStage],
  );

  const pickupIcon = useMemo(
    () => createPickupIcon(pickupStage?.name),
    [pickupStage],
  );

  const driverRouteIndex = useMemo(
    () => nearestRouteIndex(matchedDriverPosition, geometry),
    [matchedDriverPosition, geometry]
  );

  const pickupRouteIndex = useMemo(
    () => nearestRouteIndex(pickupPosition, geometry),
    [pickupPosition, geometry]
  );

  const destinationRouteIndex = geometry.length - 1;

  const busGapKm = useMemo(
    () =>
      driverRouteIndex >= 0
        ? haversineKm(
            matchedDriverPosition,
            geometry[driverRouteIndex],
          )
        : null,
    [matchedDriverPosition, geometry, driverRouteIndex],
  );

  const busOffRoute = busGapKm != null && busGapKm > 1.5;

  const locationAgeMin = useMemo(() => {
    const ageSeconds =
      live?.location_age_seconds ??
      live?.driver?.location_age_seconds;

    if (Number.isFinite(ageSeconds) && live?._fetchedAt) {
      return Math.max(
        0,
        (ageSeconds + (clockNow - live._fetchedAt) / 1000) / 60,
      );
    }

    const updated = live?.driver?.location_updated_at;

    if (!updated) return null;

    const time = Date.parse(updated);

    if (!Number.isFinite(time)) return null;

    return Math.max(0, (clockNow - time) / 60000);
  }, [live, clockNow]);

  const busStale =
    !driverTarget ||
    live?.is_stale === true ||
    locationAgeMin == null ||
    locationAgeMin * 60 > 120;
  const busUnreliable = busOffRoute || busStale;

  const ageText =
    locationAgeMin == null
      ? ''
      : locationAgeMin < 60
        ? `${Math.round(locationAgeMin)} min`
        : locationAgeMin < 2880
          ? `${Math.round(locationAgeMin / 60)} h`
          : `${Math.round(locationAgeMin / 1440)} days`;

  const busPastPickup =
    !busUnreliable &&
    pickupRouteIndex >= 0 &&
    driverRouteIndex > pickupRouteIndex + 5;

  const tripStatus = String(live?.trip_status || '').toLowerCase();
  const inactiveTripStatuses = [
    'completed', 'cancelled', 'ended', 'no_show', 'expired',
  ];
  const tripLifecycleLive =
    live?.is_trip_live === true &&
    !inactiveTripStatuses.includes(tripStatus);

  const tripIsLive =
    Boolean(matchedDriverPosition) &&
    !busStale &&
    tripLifecycleLive;

  // Until the bus is really moving, show it waiting at the start of the route.
  const parkedTripStatus = live?.trip_status || bookingDetails?.trip_status;
  const routeStartLatitude = bookingDetails?.route_start_latitude;
  const routeStartLongitude = bookingDetails?.route_start_longitude;
  const parkedBus = useMemo(
    () =>
      tripIsLive
        ? null
        : planParkedBus({
            geometry,
            routeStart: normalizePosition({
              latitude: routeStartLatitude,
              longitude: routeStartLongitude,
            }),
            pickup: pickupPosition,
            tripStatus: parkedTripStatus,
          }),
    [
      tripIsLive,
      geometry,
      routeStartLatitude,
      routeStartLongitude,
      pickupPosition,
      parkedTripStatus,
    ],
  );
  const parkedLabel = parkedBus
    ? parkedBusLabel({
        tripStatus: parkedTripStatus,
        departureAt: live?.departure_at || bookingDetails?.departure_at,
        now: clockNow,
      })
    : null;
  const parkedHeading = parkedBus?.heading ?? null;
  const parkedIcon = useMemo(
    () =>
      parkedLabel == null
        ? null
        : createVehicleIcon({ label: parkedLabel, heading: parkedHeading }),
    [parkedLabel, parkedHeading],
  );
  const parkedStageName = bookingDetails?.route_start_point || 'the first stage';
  const liveBadge = tripIsLive ? 'Live' : parkedBus ? 'Parked' : 'Offline';

  const boarded = live?.boarded === true;
  const busIsOffRoute = useMemo(
    () =>
      tripIsLive &&
      geometry.length > 1 &&
      distanceFromLineKm(driverTarget, geometry) > OFF_ROUTE_KM,
    [tripIsLive, geometry, driverTarget],
  );
  const rerouteGoal =
    !boarded &&
    pickupPosition &&
    driverRouteIndex <= pickupRouteIndex + 5
      ? 'pickup'
      : 'destination';
  const reroute = useBusReroute({
    bookingId,
    offRoute: busIsOffRoute,
    goal: rerouteGoal,
    busPosition: driverTarget,
  });
  const rerouteLine = useMemo(
    () => (reroute ? lineAheadOfBus(matchedDriverPosition, reroute.line) : null),
    [reroute, matchedDriverPosition],
  );
  const rerouteToPickupKm =
    rerouteLine && reroute.goal === 'pickup' ? lineLengthKm(rerouteLine) : null;

  let busStatus;

  if (tripStatus === 'completed') {
    busStatus = 'Trip completed';
  } else if (parkedBus && !(trackingAvailable && driverTarget)) {
    busStatus = `Parked at ${parkedStageName} · ${parkedLabel}`;
  } else if (!trackingAvailable) {
    busStatus = 'Live tracking starts once boarding begins and a driver is assigned';
  } else if (!matchedDriverPosition) {
    busStatus = 'Waiting for a driver GPS update';
  } else if (busStale) {
    busStatus = locationAgeMin == null
      ? 'Driver GPS is stale; waiting for a fresh update'
      : `Last seen ${ageText} ago`;
  } else if (!tripLifecycleLive) {
    busStatus = live ? 'Trip is not active' : 'Checking trip status';
  } else if (reroute) {
    busStatus = 'Bus took another road · new route shown in blue';
  } else if (busOffRoute) {
    busStatus = `Bus is ${formatDistance(busGapKm)} from the route`;
  } else if (busPastPickup) {
    busStatus = 'Bus has passed your pickup';
  } else {
    busStatus = 'Driver location is live';
  }

  const remainingRoute = useMemo(() => {
    if (
      geometry.length < 2 ||
      driverRouteIndex < 0 ||
      !matchedDriverPosition
    ) {
      return [];
    }

    const targetIndex =
      pickupRouteIndex >= driverRouteIndex
        ? pickupRouteIndex
        : destinationRouteIndex;

    return [
      matchedDriverPosition,
      ...geometry.slice(driverRouteIndex + 1, targetIndex + 1),
    ];
  }, [
    geometry,
    driverRouteIndex,
    pickupRouteIndex,
    destinationRouteIndex,
    matchedDriverPosition,
  ]);

  const blueRoute = parkedBus
    ? parkedBus.pickupLeg
    : rerouteLine
      ? rerouteLine
      : busUnreliable
      ? []
      : remainingRoute;

  const distanceToPickupKm = useMemo(() => {
    if (
      geometry.length < 2 ||
      driverRouteIndex < 0 ||
      pickupRouteIndex < 0
    ) {
      return null;
    }

    if (pickupRouteIndex <= driverRouteIndex) {
      return 0;
    }

    return routeDistanceKm(
      geometry,
      driverRouteIndex,
      pickupRouteIndex
    );
  }, [
    geometry,
    driverRouteIndex,
    pickupRouteIndex,
  ]);


  const remainingDistanceKm =
    rerouteToPickupKm ??
    (busUnreliable || busPastPickup ? null : distanceToPickupKm);

  const driverSpeedKmh = useMemo(
    () => estimateBusSpeedKmh(driverHistory),
    [driverHistory],
  );

  const routeAlongM = routeMatch?.onRoute
    ? routeMatch.alongM
    : null;
  const nextStage = useMemo(
    () =>
      routeAlongM != null && driverSpeedKmh != null
        ? nextStageAhead(
            stagesOnRoute,
            routeAlongM,
            driverSpeedKmh,
          )
        : null,
    [routeAlongM, stagesOnRoute, driverSpeedKmh],
  );

  const etaMinutes = useMemo(() => {
    if (
      remainingDistanceKm == null ||
      !Number.isFinite(remainingDistanceKm) ||
      driverSpeedKmh == null ||
      !tripLifecycleLive
    ) {
      return null;
    }

    return (remainingDistanceKm / driverSpeedKmh) * 60;
  }, [remainingDistanceKm, driverSpeedKmh]);

  const totalRouteKm = useMemo(
    () =>
      geometry.length > 1
        ? routeDistanceKm(geometry, 0, geometry.length - 1)
        : 0,
    [geometry],
  );
  const routeProgressPercent =
    tripLifecycleLive &&
    !busUnreliable &&
    routeMatch?.onRoute &&
    totalRouteKm > 0 &&
    driverRouteIndex >= 0
      ? Math.min(
          100,
          (routeDistanceKm(geometry, 0, driverRouteIndex) / totalRouteKm) *
            100,
        )
      : null;
  const pickupProgressPercent =
    pickupRouteIndex >= 0 && totalRouteKm > 0
      ? Math.min(
          100,
          (routeDistanceKm(geometry, 0, pickupRouteIndex) / totalRouteKm) *
            100,
        )
      : null;

  const center =
    (tripIsLive && matchedDriverPosition) ||
    passengerPosition ||
    geometry[0] ||
    [-1.286389, 36.817223];

  const routeName =
    live?.route_name ||
    live?.trip?.route_name ||
    live?.route?.name ||
    bookingDetails?.route_name ||
    'Your trip';

  const busNumber =
    live?.driver?.bus_number ||
    live?.driver?.vehicle_registration ||
    live?.driver?.bus_registration ||
    live?.trip?.vehicle_registration ||
    bookingDetails?.driver_bus_number ||
    'Vehicle';

  const driverName = live?.driver?.name || bookingDetails?.driver_name || null;
  const driverPhone = live?.driver?.phone || null;
  const showPickupLeg =
    rerouteToPickupKm != null ||
    (Boolean(pickupPosition) && distanceToPickupKm != null && !busUnreliable && !busPastPickup);
  const pickupDistanceKm = rerouteToPickupKm ?? distanceToPickupKm;

  const pickup =
    pickupStage?.name ||
    live?.pickup?.name ||
    bookingPickup?.name ||
    live?.pickup_stage_name ||
    live?.pickup_location ||
    live?.booking?.pickup_stage_name ||
    live?.booking?.pickup_location ||
    'Pickup point';

  const destinationName =
    live?.route?.end_point ||
    bookingDetails?.route_end_point ||
    'your destination';
  const guide = tripGuide({
    bookingStatus: bookingDetails?.status,
    tripIsLive,
    parked: Boolean(parkedBus),
    boarding: String(parkedTripStatus || '').toLowerCase() === 'boarding',
    departureLabel: parkedLabel,
    boarded,
    rerouted: Boolean(reroute),
    busPastPickup: busPastPickup && !reroute,
    pickupKm: showPickupLeg ? pickupDistanceKm : null,
    etaText: etaMinutes == null ? null : formatEta(etaMinutes),
    startName: parkedStageName,
    pickupName: pickup,
    destinationName,
    lastSeenText: ageText,
  });
  const boardingPin = guide.showPin ? bookingDetails?.verification_pin : null;

  const distance =
    live?.distance_km != null
      ? live.distance_km < 1
        ? `${Math.round(live.distance_km * 1000)} m`
        : `${live.distance_km.toFixed(1)} km`
      : null;


  useEffect(() => {
    if (!Number.isFinite(etaMinutes) || etaMinutes <= 0) {
      return;
    }

    if (etaMinutes > 10 || pickupAlertSentRef.current) {
      return;
    }

    pickupAlertSentRef.current = true;

    if (
      typeof window !== 'undefined' &&
      'Notification' in window
    ) {
      const notify = () => {
        new Notification('CONNECT — Your bus is close', {
          body: `Your bus is approximately ${Math.max(
            1,
            Math.round(etaMinutes)
          )} minutes from your pickup stage.`,
        });
      };

      if (Notification.permission === 'granted') {
        notify();
      } else if (Notification.permission === 'default') {
        Notification.requestPermission().then((permission) => {
          if (permission === 'granted') notify();
        }).catch(() => {});
      }
    }
  }, [etaMinutes]);

  return (
    <div
      className="passenger-live-map"
      style={{
        position: 'fixed',
        inset: 0,
        width: '100vw',
        height: '100dvh',
        minHeight: '100dvh',
        zIndex: 9999,
        overflow: 'hidden',
        background: '#07111f',
      }}
    >
      <div className="passenger-live-map__canvas">
        <TiltedMapFrame heading={matchedDriverHeading}>
          <MapContainer
            center={center}
            zoom={MAP_TILT_ENABLED ? MAP_TILT_ZOOM : 15}
            zoomSnap={0}
            zoomDelta={0.5}
            zoomControl={false}
            scrollWheelZoom="center"
            touchZoom="center"
            doubleClickZoom="center"
            attributionControl
            className="passenger-live-map__leaflet"
          >
          <BaseTileLayer />

          <MapResize />
          <SmartFollow
            enabled={MAP_TILT_ENABLED}
            position={matchedDriverPosition}
            nextStageM={nextStage?.distanceM ?? null}
          />

          {geometry.length > 1 &&
            !(MAP_TILT_ENABLED && driverPosition) && (
            <MapRoute positions={geometry} />
          )}

          {geometry.length > 1 && (
            <>
              <Polyline
                positions={geometry}
                pathOptions={{
                  color: '#ffffff',
                  weight: 9,
                  opacity: 0.85,
                  lineCap: 'round',
                  lineJoin: 'round',
                  interactive: false,
                }}
              />

              <Polyline
                positions={geometry}
                pathOptions={{
                  color: '#9db4d3',
                  weight: 5,
                  opacity: 0.9,
                  lineCap: 'round',
                  lineJoin: 'round',
                  interactive: false,
                }}
              />
            </>
          )}

          {blueRoute.length > 1 && (
            <>
              <Polyline
                positions={blueRoute}
                pathOptions={{
                  color: '#1677ff',
                  weight: 12,
                  opacity: 0.22,
                  lineCap: 'round',
                  lineJoin: 'round',
                  interactive: false,
                }}
              />

              <Polyline
                positions={blueRoute}
                pathOptions={{
                  color: '#1677ff',
                  weight: 6,
                  opacity: 0.98,
                  lineCap: 'round',
                  lineJoin: 'round',
                  interactive: false,
                }}
              />
            </>
          )}
          <RouteProgress
            split={routeProgressPercent == null ? null : routeMatch?.split}
            weight={7}
            color="#16a34a"
            opacity={0.95}
          />

          {busOffRoute &&
            !reroute &&
            matchedDriverPosition &&
            geometry[driverRouteIndex] && (
            <Polyline
              positions={[
                matchedDriverPosition,
                geometry[driverRouteIndex],
              ]}
              pathOptions={{
                color: '#64748b',
                weight: 3,
                opacity: 0.8,
                dashArray: '6 10',
                interactive: false,
              }}
            />
          )}

          {stages.map((stage) => {
            const position = normalizePosition(stage);

            if (!position) return null;

            if (
              pickupStage &&
              stage.id != null &&
              stage.id === pickupStage.id
            ) {
              return null;
            }

            return (
              <Marker
                key={stage.id ?? stage.name}
                position={position}
                icon={stopIcon(Number(stage.order) || 1, Number(stage.order) === 1 ? 'first' : 'default')}
              >
                <Popup>
                  <strong>
                    {stage.order}. {stage.name}
                  </strong>
                </Popup>
              </Marker>
            );
          })}

          {pickupPosition && (
            <Marker
              position={pickupPosition}
              icon={pickupIcon}
              zIndexOffset={900}
            >
              <Popup>
                <strong>{pickupStage?.name || 'Pickup stage'}</strong>
                <br />
                Your pickup point
              </Popup>
            </Marker>
          )}

          {!MAP_TILT_ENABLED && following && passengerPosition && (
            <MapFollow position={passengerPosition} />
          )}

          {parkedBus && parkedIcon && (
            <Marker
              position={parkedBus.position}
              icon={parkedIcon}
              zIndexOffset={1000}
            >
              <Popup>
                <strong>{busNumber}</strong>
                <br />
                Parked at {parkedStageName}
                <br />
                {parkedLabel}
              </Popup>
            </Marker>
          )}

          {tripIsLive && matchedDriverPosition && (
            <Marker
              ref={vehicleMarkerRef}
              position={matchedDriverPosition}
              icon={vehicleIcon}
            >
              <Popup>
                <strong>{busNumber}</strong>
                <br />
                Your driver
              </Popup>
            </Marker>
          )}

          {passengerPosition && (
            <Marker
              position={passengerPosition}
              icon={passengerIcon}
            >
              <Popup>
                <strong>You</strong>
                <br />
                Current location
              </Popup>
            </Marker>
          )}
          </MapContainer>
        </TiltedMapFrame>
      </div>
      {MAP_TILT_ENABLED && (
        <>
          <MapZoomButtons
            style={{
              top: '45%',
              bottom: 'max(20px, env(safe-area-inset-bottom))',
            }}
          />
          <NextStageBanner
            next={nextStage}
            style={{
              top: 'max(88px, calc(env(safe-area-inset-top) + 78px))',
            }}
          />
        </>
      )}

      {(error && !loading) || locationError ? (
        <NoticeStack>
          {error && !loading && (
            <Notice title="Live map unavailable" onClose={() => setError('')}>
              {error}{' '}
              <button type="button" onClick={loadLive}>
                Try again
              </button>
            </Notice>
          )}
          {locationError && (
            <Notice title="Location not shared" onClose={() => setLocationError('')}>
              {locationError}
            </Notice>
          )}
        </NoticeStack>
      ) : null}

      <header className="passenger-live-map__topbar">
        <button
          type="button"
          className="passenger-live-map__back"
          onClick={onBack}
          aria-label="Back"
        >
          <ArrowLeft size={20} />
        </button>

        <div className="passenger-live-map__trip-title">
          <strong>{routeName}</strong>
          <span>
            <Radio size={13} />
            {trackingAvailable
              ? 'Live trip'
              : String(bookingDetails?.status || '').toLowerCase() === 'pending'
                ? 'Seat reserved · awaiting payment'
                : 'Trip confirmed'}
          </span>
        </div>

        <div
          className="passenger-live-map__live"
          style={tripIsLive ? undefined : { opacity: 0.6, filter: 'grayscale(1)' }}
          aria-live="polite"
        >
          <span />
          {liveBadge}
        </div>
      </header>

      <button
        type="button"
        className={`passenger-live-map__locate ${
          following ? 'is-active' : ''
        }`}
        onClick={() => setFollowing((value) => !value)}
        aria-label="Center on my location"
      >
        <LocateFixed size={21} />
      </button>

      {loading && (
        <div className="passenger-live-map__loading">
          Loading live trip…
        </div>
      )}

      <section className="passenger-live-map__sheet">
        <div
          role="button"
          aria-label="Toggle trip details"
          onClick={() => setSheetOpen((v) => !v)}
          style={{ padding: '10px 0', cursor: 'pointer', touchAction: 'manipulation' }}
        >
          <div className="passenger-live-map__handle" />
        </div>

        <div className="passenger-live-map__guide" role="status">
          <div className="passenger-live-map__guide-text">
            <strong>{guide.title}</strong>
            <span>{guide.detail}</span>
          </div>
          {boardingPin && (
            <div className="passenger-live-map__guide-pin">
              <span>Boarding PIN</span>
              <strong>{boardingPin}</strong>
            </div>
          )}
        </div>

        <div className="passenger-live-map__status-row">
          <div>
            <span className="passenger-live-map__eyebrow">
              Your trip
            </span>
            <h1>{routeName}</h1>
          </div>

          <div className="passenger-live-map__distance">
            <Navigation size={16} />
            <strong>
              {showPickupLeg
                ? formatDistance(pickupDistanceKm)
                : (!busUnreliable && distance) || '—'}
            </strong>
            <span>{showPickupLeg ? 'to pickup' : 'away'}</span>
          </div>
        </div>

        {!sheetOpen && (
          <p
            onClick={() => setSheetOpen(true)}
            style={{ margin: '8px 0 4px', fontSize: 14, fontWeight: 700, cursor: 'pointer' }}
          >
            {busStatus}
            {etaMinutes != null ? ` · ${formatEta(etaMinutes)} to pickup` : ''}
          </p>
        )}

        {sheetOpen && (<>
        {(live?.incident || incidentMsg) && (
          <div
            style={{
              margin: '12px 0',
              padding: '12px 14px',
              borderRadius: 14,
              border: '1px solid rgba(217, 119, 6, 0.6)',
              background: 'rgba(217, 119, 6, 0.14)',
            }}
          >
            {live?.incident && (
              <>
                <strong style={{ display: 'block', marginBottom: 4 }}>
                  Problem on your trip
                </strong>
                <p style={{ margin: '0 0 8px', fontSize: 13 }}>
                  {live.incident.description}
                </p>
                {live.incident.resolution ? (
                  <p style={{ margin: 0, fontSize: 13 }}>
                    You chose: {live.incident.resolution}
                  </p>
                ) : (
                  <button
                    type="button"
                    onClick={requestIncidentRefund}
                    disabled={incidentBusy}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      borderRadius: 12,
                      border: 'none',
                      background: '#b42828',
                      color: '#fff',
                      fontWeight: 600,
                      cursor: 'pointer',
                    }}
                  >
                    {incidentBusy ? 'Sending...' : 'Cancel and refund'}
                  </button>
                )}
              </>
            )}
            {live?.incident && !live.incident.resolution && (
              <div style={{ marginTop: 8 }}>
                {tripChoices === null ? (
                  <button
                    type="button"
                    onClick={loadReplacementTrips}
                    disabled={incidentBusy}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      borderRadius: 12,
                      border: '1px solid rgba(255,255,255,0.35)',
                      background: 'transparent',
                      color: 'inherit',
                      fontWeight: 600,
                      cursor: 'pointer',
                    }}
                  >
                    Choose another trip
                  </button>
                ) : tripChoices.length === 0 ? (
                  <p style={{ margin: 0, fontSize: 13 }}>
                    No other trips with free seats right now.
                  </p>
                ) : (
                  tripChoices.map((choice) => (
                    <button
                      key={choice.id}
                      type="button"
                      onClick={() => requestReschedule(choice.id)}
                      disabled={incidentBusy}
                      style={{
                        display: 'block',
                        width: '100%',
                        marginBottom: 6,
                        padding: '10px 12px',
                        borderRadius: 12,
                        border: '1px solid rgba(255,255,255,0.35)',
                        background: 'transparent',
                        color: 'inherit',
                        textAlign: 'left',
                        cursor: 'pointer',
                      }}
                    >
                      {new Date(choice.departure_at).toLocaleString()} ·{' '}
                      {choice.available_seats} seats left
                    </button>
                  ))
                )}
              </div>
            )}

            {incidentMsg && (
              <p style={{ margin: '8px 0 0', fontSize: 13 }}>{incidentMsg}</p>
            )}
          </div>
        )}

        <div className="passenger-live-map__vehicle-card">
          <div className="passenger-live-map__vehicle-icon">
            <Navigation size={20} />
          </div>

          <div className="passenger-live-map__vehicle-info">
            <strong>{busNumber}</strong>
            <span>{driverName || 'Driver pending'}</span>
            <span>
              {driverPhone ? (
                <a href={`tel:${driverPhone}`}>{driverPhone}</a>
              ) : (
                'Phone not available'
              )}
            </span>
            <span>
              {busStatus}
            </span>
          </div>

          <div
            className="passenger-live-map__vehicle-live"
            style={tripIsLive ? undefined : { opacity: 0.6, filter: 'grayscale(1)' }}
            aria-live="polite"
          >
            <span />
            {liveBadge}
          </div>
        </div>

        {geometry.length > 1 && (
          <div className="passenger-live-map__route-progress">
            <div className="passenger-live-map__route-progress-heading">
              <strong>Trip route progress</strong>
              <span>
                {routeProgressPercent == null
                  ? busStatus
                  : 'Green shows the route already traveled'}
              </span>
            </div>
            <div
              className="passenger-live-map__route-progress-track"
              role="progressbar"
              aria-label="Bus progress along the trip route"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={routeProgressPercent ?? 0}
              aria-valuetext={
                routeProgressPercent == null
                  ? 'Waiting for a fresh GPS update'
                  : `${Math.round(routeProgressPercent)} percent of the route traveled`
              }
            >
              {routeProgressPercent != null && (
                <>
                  <span
                    className="passenger-live-map__route-progress-fill"
                    style={{ width: `${routeProgressPercent}%` }}
                    aria-hidden="true"
                  />
                  <span
                    className="passenger-live-map__route-progress-bus"
                    style={{ left: `${routeProgressPercent}%` }}
                    aria-hidden="true"
                  />
                </>
              )}
              {pickupProgressPercent != null && (
                <span
                  className="passenger-live-map__route-progress-pickup"
                  style={{ left: `${pickupProgressPercent}%` }}
                  aria-hidden="true"
                />
              )}
            </div>
            <div className="passenger-live-map__route-progress-labels">
              <span>Trip start</span>
              <span>{pickup || 'Pickup'}</span>
              <span>Destination</span>
            </div>
            <div className="passenger-live-map__route-progress-legend">
              <span><i className="is-traveled" />Traveled</span>
              <span><i className="is-to-pickup" />Bus to pickup</span>
              <span><i className="is-route" />Full route</span>
            </div>
          </div>
        )}

        <div className="passenger-live-map__traffic-note" role="status">
          <strong>Traffic information</strong>
          <span>
            {driverSpeedKmh != null && !busUnreliable && tripLifecycleLive
              ? `Recent bus GPS speed: about ${driverSpeedKmh} km/h. This is a bus-speed estimate, not live city traffic.`
              : 'No live city-traffic feed is available. A bus-speed estimate will appear only when recent, reliable GPS updates support one.'}
          </span>
        </div>

        <div className="passenger-live-map__pickup">
          <div className="passenger-live-map__pickup-dot" />
          <div>
            <span>Your pickup</span>
            <strong>{pickup}</strong>
            <span>
              {pickupPosition
                ? (busPastPickup ? 'The bus has already passed this stop' : busStale ? 'ETA paused until a fresh GPS update' : busOffRoute ? 'ETA unavailable while the bus is off route' : `${etaMinutes == null ? 'ETA unavailable' : formatEta(etaMinutes)} · ${formatDistance(distanceToPickupKm)}`)
                : 'This pickup point is not placed on the map'}
            </span>
          </div>
        </div>

        {!passengerPosition && (
          <div className="passenger-live-map__gps-note">
            Your location is not available yet. Enable location sharing
            for a live position on the map.
          </div>
        )}
      </>)}
      </section>
    </div>
  );
}
