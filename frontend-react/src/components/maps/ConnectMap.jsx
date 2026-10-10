import { useEffect, useMemo, useRef } from 'react';
import {
  MapContainer,
  TileLayer,
  Marker,
  Popup,
  Polyline,
  CircleMarker,
  useMap,
} from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import '../../pages/passenger/PassengerLiveMap.css';
import { useRoadDriverPosition } from './useRoadDriverPosition';

const DEFAULT_CENTER = [-1.286389, 36.817223];

const driverIcon = L.divIcon({
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

const passengerIcon = L.divIcon({
  className: 'connect-map-marker',
  html: `
    <div class="connect-map-marker-inner passenger-marker">
      <span>👤</span>
    </div>
  `,
  iconSize: [54, 54],
  iconAnchor: [27, 27],
  popupAnchor: [0, -25],
});

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function stageIcon(stage) {
  const order = Number(stage?.order || 0);
  const name = escapeHtml(stage?.name || 'Stage');
  const passengerCount = Number(stage?.passenger_count || 0);
  const hasPassengers = passengerCount > 0;

  return L.divIcon({
    className: 'connect-stage-marker',
    html: `
      <div class="connect-stage-marker-wrap ${
        hasPassengers ? 'connect-stage-has-passengers' : ''
      }">

        <div class="connect-stage-pin">
          <span class="connect-stage-number">${order}</span>
        </div>

        <div class="connect-stage-label">
          ${name}
        </div>

        ${
          hasPassengers
            ? `
              <div class="connect-stage-passenger-badge">
                👤 ${passengerCount}
              </div>
            `
            : ''
        }

      </div>
    `,
    iconSize: [230, 105],
    iconAnchor: [115, 70],
    popupAnchor: [0, -70],
  });
}
const stageIconCache = new Map();

function cachedStageIcon(stage) {
  const key = `${stage?.order}|${stage?.name}|${stage?.passenger_count || 0}`;
  if (!stageIconCache.has(key)) {
    stageIconCache.set(key, stageIcon(stage));
  }
  return stageIconCache.get(key);
}

function MapResize({ height }) {
  const map = useMap();

  useEffect(() => {
    const timers = [
      setTimeout(() => map.invalidateSize(), 50),
      setTimeout(() => map.invalidateSize(), 250),
      setTimeout(() => map.invalidateSize(), 600),
    ];

    return () => timers.forEach(clearTimeout);
  }, [height, map]);

  return null;
}

function MapCenter({ routePositions }) {
  const map = useMap();
  const previousRoute = useRef('');

  useEffect(() => {
    if (routePositions.length < 2) {
      return;
    }

    const routeKey = routePositions
      .map(([lat, lng]) => `${lat.toFixed(5)},${lng.toFixed(5)}`)
      .join('|');

    if (routeKey === previousRoute.current) {
      return;
    }

    const bounds = L.latLngBounds(routePositions);

    if (bounds.isValid()) {
      map.fitBounds(bounds, {
        padding: [55, 55],
        maxZoom: 14,
      });

      previousRoute.current = routeKey;
    }
  }, [routePositions, map]);

  return null;
}

function PassengerPopup({ passenger, stage }) {
  return (
    <div style={{ minWidth: '210px' }}>
      <div
        style={{
          fontSize: '15px',
          fontWeight: 700,
          marginBottom: '7px',
        }}
      >
        {passenger.passenger || 'Passenger'}
      </div>

      {passenger.passenger_phone && (
        <div style={{ marginBottom: '4px' }}>
          📞 {passenger.passenger_phone}
        </div>
      )}

      <div style={{ marginBottom: '4px' }}>
        🎫 {passenger.booking_number || passenger.booking_id}
      </div>

      <div style={{ marginBottom: '4px' }}>
        💺 {passenger.seats || 1} seat
        {(passenger.seats || 1) !== 1 ? 's' : ''}
      </div>

      <div style={{ marginBottom: '4px' }}>
        📍 {stage?.name || passenger.pickup_location || 'Pickup stage'}
      </div>

      <div
        style={{
          marginTop: '7px',
          paddingTop: '6px',
          borderTop: '1px solid #eee',
          fontSize: '12px',
          color: '#666',
        }}
      >
        Status: {passenger.status || '—'}
      </div>

      {passenger.passenger_latitude != null &&
        passenger.passenger_longitude != null && (
          <div
            style={{
              marginTop: '4px',
              fontSize: '11px',
              color: '#777',
            }}
          >
            Live location available
          </div>
        )}
    </div>
  );
}


export default function ConnectMap({
  driver,
  passenger,
  pickup,
  routeGeometry,
  stages = [],
  height = 380,
  zoom = 14,
  showDriver = true,
  showPassenger = true,
}) {
  const driverGpsPosition =
    driver?.latitude != null && driver?.longitude != null
      ? [Number(driver.latitude), Number(driver.longitude)]
      : null;

  const passengerPosition =
    passenger?.latitude != null && passenger?.longitude != null
      ? [Number(passenger.latitude), Number(passenger.longitude)]
      : null;

  const pickupPosition =
    pickup?.latitude != null && pickup?.longitude != null
      ? [Number(pickup.latitude), Number(pickup.longitude)]
      : null;

  /*
   * ROUTE GEOMETRY IS AUTHORITATIVE.
   *
   * Passenger coordinates are NEVER added to this array.
   */
  const routePositions = useMemo(
    () =>
      routeGeometry?.type === 'LineString' &&
      Array.isArray(routeGeometry.coordinates)
        ? routeGeometry.coordinates
            .filter(
              (point) =>
                Array.isArray(point) &&
                point.length >= 2 &&
                Number.isFinite(Number(point[0])) &&
                Number.isFinite(Number(point[1])),
            )
            .map(([lng, lat]) => [Number(lat), Number(lng)])
        : [],
    [routeGeometry],
  );

  const {
    position: driverPosition,
    heading: driverHeading,
  } = useRoadDriverPosition(
    driverGpsPosition,
    routePositions,
  );

  const stageMarkers = useMemo(
    () =>
      stages
        .filter(
          (stage) =>
            stage?.latitude != null &&
            stage?.longitude != null &&
            Number.isFinite(Number(stage.latitude)) &&
            Number.isFinite(Number(stage.longitude)),
        )
        .map((stage) => ({
          ...stage,
          position: [
            Number(stage.latitude),
            Number(stage.longitude),
          ],
        })),
    [stages],
  );

  /*
   * Build a separate passenger marker for every assigned
   * passenger that has GPS coordinates.
   *
   * This does NOT alter the route.
   */
  const passengerMarkers = useMemo(() => {
    const markers = [];

    stageMarkers.forEach((stage) => {
      if (!Array.isArray(stage.passengers)) {
        return;
      }

      stage.passengers.forEach((assignedPassenger) => {
        const lat = Number(
          assignedPassenger.passenger_latitude,
        );

        const lng = Number(
          assignedPassenger.passenger_longitude,
        );

        if (
          !Number.isFinite(lat) ||
          !Number.isFinite(lng)
        ) {
          return;
        }

        markers.push({
          ...assignedPassenger,
          stage,
          position: [lat, lng],
        });
      });
    });

    return markers;
  }, [stageMarkers]);

  const vehicleMarkerRef = useRef(null);
  const vehicleHeadingRef = useRef(0);

  useEffect(() => {
    if (!Number.isFinite(driverHeading)) return;

    const markerElement =
      vehicleMarkerRef.current?.getElement?.();

    const vehicle =
      markerElement?.querySelector(
        '.passenger-vehicle-marker__bus',
      );

    if (!vehicle) return;

    const previous =
      vehicleHeadingRef.current;

    const diff =
      ((driverHeading - previous + 540) %
        360) -
      180;

    const next =
      previous + diff;

    vehicleHeadingRef.current =
      next;

    vehicle.style.transformOrigin =
      'center center';

    vehicle.style.transition =
      'transform 0.35s ease-out';

    vehicle.style.transform =
      `rotate(${next}deg)`;
  }, [
    driverHeading,
    driverPosition,
  ]);

  const center =
    driverPosition ||
    passengerPosition ||
    pickupPosition ||
    (routePositions.length
      ? routePositions[
          Math.floor(routePositions.length / 2)
        ]
      : null) ||
    DEFAULT_CENTER;

  return (
    <div
      className="connect-map-wrapper"
      style={{ height }}
    >
      <MapContainer
        center={center}
        zoom={zoom}
        scrollWheelZoom
        wheelPxPerZoomLevel={120}
        wheelDebounceTime={60}
        style={{
          height: '100%',
          width: '100%',
          borderRadius: '16px',
        }}
      >
        <TileLayer
          attribution="&copy; OpenStreetMap contributors"
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          maxZoom={19}
        />

        <MapResize height={height} />

        <MapCenter routePositions={routePositions} />

        {routePositions.length > 1 && (
          <>
            <Polyline
              positions={routePositions}
              pathOptions={{
                color: '#1677ff',
                weight: 12,
                opacity: 0.18,
                lineCap: 'round',
                lineJoin: 'round',
                interactive: false,
              }}
            />

            <Polyline
              positions={routePositions}
              pathOptions={{
                color: '#1677ff',
                weight: 7,
                opacity: 0.95,
                lineCap: 'round',
                lineJoin: 'round',
                interactive: false,
              }}
            />

            <Polyline
              positions={routePositions}
              pathOptions={{
                color: '#bfe5ff',
                weight: 2,
                opacity: 0.95,
                lineCap: 'round',
                lineJoin: 'round',
                interactive: false,
              }}
            />
          </>
        )}

        {/*
         * ------------------------------------------------------
         * PICKUP STAGES
         * ------------------------------------------------------
         */}
        {stageMarkers.map((stage) => (
          <Marker
            key={`stage-${stage.id}`}
            position={stage.position}
            icon={cachedStageIcon(stage)}
          >
            <Popup>
              <div style={{ minWidth: '230px' }}>
                <strong>
                  {stage.order}. {stage.name}
                </strong>

                <div
                  style={{
                    marginTop: '6px',
                    marginBottom: '8px',
                    fontSize: '12px',
                    color: '#666',
                  }}
                >
                  {stage.passenger_count || 0} passenger
                  {(stage.passenger_count || 0) !== 1
                    ? 's'
                    : ''}{' '}
                  · {stage.booking_count || 0} booking
                  {(stage.booking_count || 0) !== 1
                    ? 's'
                    : ''}
                </div>

                {Array.isArray(stage.passengers) &&
                stage.passengers.length > 0 ? (
                  <div>
                    <strong>Assigned passengers</strong>

                    <div style={{ marginTop: '7px' }}>
                      {stage.passengers.map(
                        (assignedPassenger) => (
                          <div
                            key={
                              assignedPassenger.booking_id
                            }
                            style={{
                              padding: '8px 0',
                              borderBottom:
                                '1px solid #eee',
                            }}
                          >
                            <div
                              style={{
                                fontWeight: 700,
                                marginBottom: '4px',
                              }}
                            >
                              👤{' '}
                              {assignedPassenger.passenger ||
                                'Passenger'}
                            </div>

                            {assignedPassenger.passenger_phone && (
                              <div>
                                📞{' '}
                                {
                                  assignedPassenger.passenger_phone
                                }
                              </div>
                            )}

                            <div>
                              🎫{' '}
                              {assignedPassenger.booking_number ||
                                assignedPassenger.booking_id}
                            </div>

                            <div>
                              💺 Seats:{' '}
                              {assignedPassenger.seats ||
                                1}
                            </div>

                            <div>
                              Status:{' '}
                              {assignedPassenger.status ||
                                '—'}
                            </div>

                            <div
                              style={{
                                marginTop: '3px',
                                fontSize: '11px',
                                color: '#777',
                              }}
                            >
                              {assignedPassenger.passenger_latitude !=
                                null &&
                              assignedPassenger.passenger_longitude !=
                                null
                                ? '● Passenger GPS available'
                                : '○ Passenger GPS unavailable'}
                            </div>
                          </div>
                        ),
                      )}
                    </div>
                  </div>
                ) : (
                  <div
                    style={{
                      marginTop: '6px',
                      color: '#777',
                    }}
                  >
                    No assigned passengers
                  </div>
                )}
              </div>
            </Popup>
          </Marker>
        ))}

        {/*
         * ------------------------------------------------------
         * PASSENGER GPS MARKERS
         * ------------------------------------------------------
         *
         * Every passenger with GPS coordinates gets their own
         * marker. This is independent of the route geometry.
         */}
        {passengerMarkers.map((assignedPassenger) => (
          <Marker
            key={`passenger-${assignedPassenger.booking_id}`}
            position={assignedPassenger.position}
            icon={passengerIcon}
            zIndexOffset={900}
          >
            <Popup>
              <PassengerPopup
                passenger={assignedPassenger}
                stage={assignedPassenger.stage}
              />
            </Popup>
          </Marker>
        ))}

        {/*
         * ------------------------------------------------------
         * DRIVER
         * ------------------------------------------------------
         */}
        {showDriver && driverPosition && (
          <Marker
            ref={vehicleMarkerRef}
            position={driverPosition}
            icon={driverIcon}
            zIndexOffset={1000}
          >
            <Popup>
              <strong>
                {driver.name || 'Driver'}
              </strong>

              <br />

              {driver.bus_number
                ? `Bus: ${driver.bus_number}`
                : 'Driver location'}

              {driver.phone_number && (
                <>
                  <br />
                  Phone: {driver.phone_number}
                </>
              )}
            </Popup>
          </Marker>
        )}

        {/*
         * ------------------------------------------------------
         * OPTIONAL LEGACY PICKUP MARKER
         * ------------------------------------------------------
         */}
        {pickupPosition && (
          <CircleMarker
            center={pickupPosition}
            radius={8}
            pathOptions={{
              weight: 3,
              fillOpacity: 0.9,
            }}
          >
            <Popup>
              <strong>
                {pickup?.name || 'Pickup stage'}
              </strong>

              <br />

              Selected boarding point
            </Popup>
          </CircleMarker>
        )}

        {/*
         * ------------------------------------------------------
         * OPTIONAL SINGLE PASSENGER
         * ------------------------------------------------------
         *
         * Kept for other pages/components that still use the
         * generic ConnectMap component with one passenger.
         *
         * DriverLiveLocation intentionally passes passenger=null.
         */}
        {showPassenger && passengerPosition && (
          <Marker
            position={passengerPosition}
            icon={passengerIcon}
            zIndexOffset={900}
          >
            <Popup>
              <strong>Your location</strong>

              <br />

              Live passenger location
            </Popup>
          </Marker>
        )}
      </MapContainer>
    </div>
  );
}
