import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  MapContainer,
  TileLayer,
  Marker,
  Popup,
  Polyline,
  useMap,
} from 'react-leaflet';
import L from 'leaflet';
import { ArrowLeft, LocateFixed, Navigation, Radio } from 'lucide-react';
import { apiRequest } from '../../api';
import './PassengerLiveMap.css';
import { useRoadDriverPosition } from '../../components/maps/useRoadDriverPosition';

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


function buildCumulative(geometry) {
  if (!geometry || geometry.length < 2) return null;
  const cum = [0];
  for (let i = 1; i < geometry.length; i += 1) {
    cum.push(cum[i - 1] + haversineKm(geometry[i - 1], geometry[i]));
  }
  return cum;
}

function pointAtDistance(geometry, cum, s) {
  const total = cum[cum.length - 1];
  const d = Math.max(0, Math.min(total, s));
  let lo = 0, hi = cum.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (cum[mid] <= d) lo = mid; else hi = mid;
  }
  const a = geometry[lo], b = geometry[lo + 1];
  const seg = cum[lo + 1] - cum[lo];
  const t = seg > 0 ? (d - cum[lo]) / seg : 0;
  const lat = a[0] + (b[0] - a[0]) * t;
  const lng = a[1] + (b[1] - a[1]) * t;
  const heading =
    (Math.atan2(
      (b[1] - a[1]) * Math.cos((a[0] * Math.PI) / 180),
      b[0] - a[0],
    ) * 180) / Math.PI;
  return { position: [lat, lng], heading: (heading + 360) % 360 };
}



function useDemoDriver(geometry) {
  const enabled =
    typeof window !== 'undefined' &&
    (new URLSearchParams(window.location.search).get('demo') === '1' ||
      window.localStorage.getItem('demo') === '1');
  const [pos, setPos] = useState(null);

  useEffect(() => {
    if (!enabled || !geometry || geometry.length < 2) return undefined;
    const cum = buildCumulative(geometry);
    const total = cum[cum.length - 1];
    let s = 0;

    const id = window.setInterval(() => {
      s += 0.03; // km per 2 s = ~54 km/h
      if (s > total) s = 0;
      const p = pointAtDistance(geometry, cum, s).position;
      setPos([
        p[0] + (Math.random() - 0.5) * 0.0002,
        p[1] + (Math.random() - 0.5) * 0.0002,
      ]);
    }, 2000);

    return () => window.clearInterval(id);
  }, [enabled, geometry]);

  return enabled ? pos : null;
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

function createVehicleIcon() {
  return L.divIcon({
    className: 'passenger-vehicle-marker',
    html: `
      <div class="passenger-vehicle-marker__scene">
        <div class="passenger-vehicle-marker__shadow"></div>
        <div class="passenger-vehicle-marker__glow"></div>

        <div class="passenger-vehicle-marker__bus">
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

const stageDotIcon = L.divIcon({
  className: 'connect-stage-dot',
  html: '<div style="width:14px;height:14px;border-radius:50%;background:#fff;border:3px solid #475569;box-shadow:0 1px 4px rgba(0,0,0,.35)"></div>',
  iconSize: [14, 14],
  iconAnchor: [7, 7],
});

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
  routeGeometry: bookingRouteGeometry = null,
  pickup: bookingPickup = null,
  onBack,
}) {
  const [live, setLive] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [following, setFollowing] = useState(false);
  const [driverHistory, setDriverHistory] = useState([]);
  const pickupAlertSentRef = useRef(false);


  const loadLive = useCallback(async () => {
    if (!bookingId) {
      setLoading(false);
      setError('No active trip selected.');
      return;
    }

    try {
      const data = await apiRequest(
        `/bookings/${bookingId}/live-location/`
      );

      const nextDriver = normalizePosition(data?.driver);
      const now = Date.now();

      if (nextDriver) {
        setDriverHistory((previous) => [
          ...previous.filter(
            (item) => now - item.time < 15 * 60 * 1000
          ),
          {
            position: nextDriver,
            time: now,
          },
        ].slice(-8));
      }

      setLive({ ...data, _fetchedAt: now });
      setError('');
    } catch (err) {
      setError(err.message || 'Unable to load live trip location.');
    } finally {
      setLoading(false);
    }
  }, [bookingId]);

  useEffect(() => {
    loadLive();

    const timer = window.setInterval(loadLive, 2000);

    return () => window.clearInterval(timer);
  }, [loadLive]);

  useEffect(() => {
    if (!bookingId || !navigator.geolocation) {
      return undefined;
    }

    let active = true;
    let lastSent = 0;

    const sendLocation = (position) => {
      if (!active) return;

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
      }).catch(() => {});
    };

    navigator.geolocation.getCurrentPosition(
      sendLocation,
      () => {},
      {
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 10000,
      }
    );

    const watchId = navigator.geolocation.watchPosition(
      sendLocation,
      () => {},
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
  }, [bookingId]);

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

  useEffect(() => {
    if (!Number.isFinite(driverHeading)) return;

    const markerElement =
      vehicleMarkerRef.current?.getElement?.();

    const vehicle =
      markerElement?.querySelector(
        '.passenger-vehicle-marker__bus'
      );

    if (!vehicle) return;

    const previous = vehicleHeadingRef.current;

    const diff =
      ((driverHeading - previous + 540) % 360) - 180;

    const next = previous + diff;

    vehicleHeadingRef.current = next;

    vehicle.style.transformOrigin = 'center center';
    vehicle.style.transition = 'transform 0.35s ease-out';
    vehicle.style.transform = `rotate(${next}deg)`;
  }, [driverHeading, driverPosition]);


  const demoTarget = useDemoDriver(geometry);

  // Simulation may override GPS only when the server confirms an active trip.
  const displayedDriverPosition =
    live?.is_trip_live === true && demoTarget
      ? demoTarget
      : driverPosition;


  const stages = useMemo(
    () => (Array.isArray(live?.stages) ? live.stages : []),
    [live],
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
    () => nearestRouteIndex(displayedDriverPosition, geometry),
    [displayedDriverPosition, geometry]
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
            displayedDriverPosition,
            geometry[driverRouteIndex],
          )
        : null,
    [displayedDriverPosition, geometry, driverRouteIndex],
  );

  const busOffRoute = busGapKm != null && busGapKm > 1.5;

  const locationAgeMin = useMemo(() => {
    const updated = live?.driver?.location_updated_at;

    if (!updated || !live?._fetchedAt) return null;

    const time = Date.parse(updated);

    if (!Number.isFinite(time)) return null;

    return Math.max(0, (live._fetchedAt - time) / 60000);
  }, [live]);

  const busStale =
    typeof live?.is_stale === 'boolean'
      ? live.is_stale
      : locationAgeMin == null || locationAgeMin * 60 > 120;
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
    Boolean(displayedDriverPosition) &&
    !busStale &&
    tripLifecycleLive;

  let busStatus;

  if (tripStatus === 'completed') {
    busStatus = 'Trip completed';
  } else if (!tripLifecycleLive) {
    busStatus = live ? 'Trip is not active' : 'Checking trip status';
  } else if (!displayedDriverPosition) {
    busStatus = 'Waiting for driver location';
  } else if (busStale) {
    busStatus = locationAgeMin == null
      ? 'Driver location is offline'
      : `Last seen ${ageText} ago`;
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
      driverRouteIndex < 0
    ) {
      return [];
    }

    const targetIndex =
      pickupRouteIndex >= driverRouteIndex
        ? pickupRouteIndex
        : destinationRouteIndex;

    return geometry.slice(
      Math.max(driverRouteIndex, 0),
      targetIndex + 1,
    );
  }, [
    geometry,
    driverRouteIndex,
    pickupRouteIndex,
    destinationRouteIndex,
  ]);

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
    busUnreliable || busPastPickup ? null : distanceToPickupKm;

  const driverSpeedKmh = useMemo(() => {
    const history = driverHistory;

    if (history.length < 2) {
      return 25;
    }

    const first = history[0];
    const last = history[history.length - 1];

    const elapsedHours =
      (last.time - first.time) / 3600000;

    if (elapsedHours <= 0) {
      return 25;
    }

    const distance = haversineKm(
      first.position,
      last.position
    );

    if (!distance || distance < 0.02) {
      return 25;
    }

    const speed = distance / elapsedHours;

    return Math.min(Math.max(speed, 8), 80);
  }, [driverHistory, driverPosition]);

  const etaMinutes = useMemo(() => {
    if (
      remainingDistanceKm == null ||
      !Number.isFinite(remainingDistanceKm)
    ) {
      return null;
    }

    return (remainingDistanceKm / driverSpeedKmh) * 60;
  }, [remainingDistanceKm, driverSpeedKmh]);

  const center =
    displayedDriverPosition ||
    passengerPosition ||
    geometry[0] ||
    [-1.286389, 36.817223];

  const routeName =
    live?.route_name ||
    live?.trip?.route_name ||
    live?.route?.name ||
    'Your trip';

  const busNumber =
    live?.driver?.bus_number ||
    live?.driver?.vehicle_registration ||
    live?.driver?.bus_registration ||
    live?.trip?.vehicle_registration ||
    'Vehicle';

  const driverName = live?.driver?.name || null;
  const driverPhone = live?.driver?.phone || null;
  const showPickupLeg =
    Boolean(pickupPosition) && distanceToPickupKm != null && !busUnreliable && !busPastPickup;

  const pickup =
    pickupStage?.name ||
    live?.pickup?.name ||
    bookingPickup?.name ||
    live?.pickup_stage_name ||
    live?.pickup_location ||
    live?.booking?.pickup_stage_name ||
    live?.booking?.pickup_location ||
    'Pickup point';

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
        <MapContainer
          center={center}
          zoom={15}
          zoomControl={false}
          attributionControl
          className="passenger-live-map__leaflet"
        >
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution="&copy; OpenStreetMap contributors"
          />

          <MapResize />

          {geometry.length > 1 && (
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

          {!busUnreliable && remainingRoute.length > 1 && (
            <>
              <Polyline
                positions={remainingRoute}
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
                positions={remainingRoute}
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

          {busOffRoute &&
            displayedDriverPosition &&
            geometry[driverRouteIndex] && (
            <Polyline
              positions={[
                displayedDriverPosition,
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
                icon={stageDotIcon}
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

          {following && passengerPosition && (
            <MapFollow position={passengerPosition} />
          )}

          {tripIsLive && displayedDriverPosition && (
            <Marker
              ref={vehicleMarkerRef}
              position={displayedDriverPosition}
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
      </div>

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
            Live trip
          </span>
        </div>

        <div
          className="passenger-live-map__live"
          style={tripIsLive ? undefined : { opacity: 0.6, filter: 'grayscale(1)' }}
          aria-live="polite"
        >
          <span />
          {tripIsLive ? 'LIVE' : 'OFFLINE'}
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

      {error && !loading && (
        <div className="passenger-live-map__error">
          <strong>Live map unavailable</strong>
          <span>{error}</span>
          <button type="button" onClick={loadLive}>
            Retry
          </button>
        </div>
      )}

      <section className="passenger-live-map__sheet">
        <div className="passenger-live-map__handle" />

        <div className="passenger-live-map__status-row">
          <div>
            <span className="passenger-live-map__eyebrow">
              YOUR TRIP
            </span>
            <h1>{routeName}</h1>
          </div>

          <div className="passenger-live-map__distance">
            <Navigation size={16} />
            <strong>
              {showPickupLeg
                ? formatDistance(distanceToPickupKm)
                : (!busUnreliable && distance) || '—'}
            </strong>
            <span>{showPickupLeg ? 'to pickup' : 'away'}</span>
          </div>
        </div>

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
            {tripIsLive ? 'LIVE' : 'OFFLINE'}
          </div>
        </div>

        <div className="passenger-live-map__pickup">
          <div className="passenger-live-map__pickup-dot" />
          <div>
            <span>YOUR PICKUP</span>
            <strong>{pickup}</strong>
            <span>
              {pickupPosition
                ? (busPastPickup ? 'The bus has already passed this stop' : busUnreliable ? 'ETA appears once the bus is on the route' : `${formatEta(etaMinutes)} · ${formatDistance(distanceToPickupKm)}`)
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
      </section>
    </div>
  );
}
