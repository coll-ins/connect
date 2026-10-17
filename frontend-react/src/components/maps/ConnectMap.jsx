import { useEffect, useMemo, useRef } from 'react';
import { MapContainer, Marker, Popup, Polyline, CircleMarker, useMap } from 'react-leaflet';
import BaseTileLayer from './BaseTileLayer';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import '../../pages/passenger/PassengerLiveMap.css';
import TiltedMapFrame, {
  MAP_TILT_ENABLED,
  MAP_TILT_ZOOM,
} from './TiltedMapFrame';
import SmartFollow from './SmartFollow';
import { MapZoomButtons, NextStageBanner } from './MapNavOverlays';
import RouteProgress from './RouteProgress';
import useRouteMatch from './useRouteMatch';
import { useRoadDriverPosition } from './useRoadDriverPosition';
import { nextStageAhead, stagesAlongRoute } from './wazeNav';

import RoadLayer from './RoadLayer';
import { buildRoute, snapStages } from './route';
import './Stage3D.css';
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

function stageIcon(stage) {
  const order = Number(stage?.order || 0);
  const passengerCount = Number(stage?.passenger_count || 0);
  const variant = order === 1 ? 'first' : 'default';
  return L.divIcon({
    className: `stage3d stage3d--${variant}`,
    html: `
      <div class="stage3d__pin"><span>${order}</span></div>
      <i class="stage3d__shadow"></i>
      ${passengerCount > 0 ? `<b class="stage3d__badge">${passengerCount}</b>` : ''}
    `,
    iconSize: [34, 44],
    iconAnchor: [17, 42],
    popupAnchor: [0, -38],
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

function MapReady({ onMapReady }) {
  const map = useMap();

  useEffect(() => {
    onMapReady?.(map);
    return () => onMapReady?.(null);
  }, [map, onMapReady]);

  return null;
}

const LABEL_MIN_ZOOM = 15;

function ZoomLabels() {
  const map = useMap();

  useEffect(() => {
    const el = map.getContainer();
    const apply = () =>
      el.classList.toggle(
        'connect-labels-hidden',
        map.getZoom() < LABEL_MIN_ZOOM,
      );
    apply();
    map.on('zoom', apply);
    return () => {
      map.off('zoom', apply);
      el.classList.remove('connect-labels-hidden');
    };
  }, [map]);

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
  tilt = MAP_TILT_ENABLED,
  onMapReady,
  onDriverPositionChange,
  onHeadingChange,
}) {
  const driverLat = driver?.latitude;
  const driverLng = driver?.longitude;
  const driverGpsPosition = useMemo(
    () =>
      driverLat != null && driverLng != null
        ? [Number(driverLat), Number(driverLng)]
        : null,
    [driverLat, driverLng],
  );

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
    heading: rawDriverHeading,
  } = useRoadDriverPosition(
    driverGpsPosition,
    routePositions,
  );

  const routeMatch = useRouteMatch(routePositions, driverGpsPosition);
  const matchedPosition = routeMatch?.onRoute
    ? driverPosition
    : routeMatch?.position ?? driverPosition;
  const gpsHeading = Number(driver?.heading);
  const matchedHeading =
    routeMatch?.onRoute && routeMatch.heading != null
      ? routeMatch.heading
      : Number.isFinite(gpsHeading)
        ? gpsHeading
        : rawDriverHeading;

  useEffect(() => {
    onHeadingChange?.(matchedHeading);
  }, [matchedHeading, onHeadingChange]);

  useEffect(() => {
    onDriverPositionChange?.(matchedPosition);
  }, [matchedPosition, onDriverPositionChange]);

  const stageMarkers = useMemo(() => {
    const valid = stages.filter(
      (s) =>
        s?.latitude != null && s?.longitude != null &&
        Number.isFinite(Number(s.latitude)) && Number.isFinite(Number(s.longitude)),
    );
    const road = buildRoute(routeGeometry);
    const snapped = road.pts.length > 1 ? snapStages(road, valid) : valid;
    return snapped.map((s) => ({
      ...s,
      position:
        s.snapped && s.offsetM <= 150
          ? [s.lat, s.lng]
          : [Number(s.latitude), Number(s.longitude)],
    }));
  }, [stages, routeGeometry]);

  const stagesOnRoute = useMemo(
    () => stagesAlongRoute(routeMatch?.route, stageMarkers),
    [routeMatch?.route, stageMarkers],
  );
  const routeAlongM = routeMatch?.onRoute
    ? routeMatch.alongM
    : null;
  const nextStage = useMemo(
    () =>
      routeAlongM != null
        ? nextStageAhead(stagesOnRoute, routeAlongM, 25)
        : null,
    [routeAlongM, stagesOnRoute],
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
    if (!Number.isFinite(matchedHeading)) return;

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
      ((matchedHeading - previous + 540) %
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
    matchedHeading,
    matchedPosition,
  ]);

  const center =
    matchedPosition ||
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
      <TiltedMapFrame enabled={tilt} heading={matchedHeading}>
        <MapContainer
          center={center}
          zoom={tilt ? MAP_TILT_ZOOM : zoom}
          zoomSnap={0}
          zoomDelta={0.5}
          zoomControl={!tilt}
          scrollWheelZoom="center"
          touchZoom="center"
          doubleClickZoom="center"
          wheelPxPerZoomLevel={120}
          wheelDebounceTime={60}
          style={{
            height: '100%',
            width: '100%',
            borderRadius: '16px',
          }}
        >
        <MapReady onMapReady={onMapReady} />
        <ZoomLabels />

        <BaseTileLayer />

        <MapResize height={height} />

        {!tilt && <MapCenter routePositions={routePositions} />}
        <SmartFollow
          enabled={tilt}
          position={matchedPosition}
          nextStageM={nextStage?.distanceM ?? null}
        />

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
        <RouteProgress split={routeMatch?.split} weight={7} />

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
        {showDriver && matchedPosition && (
          <Marker
            ref={vehicleMarkerRef}
            position={matchedPosition}
            icon={driverIcon}
            zIndexOffset={1000}
          >
            <Popup>
              <strong>
                {driver?.name || 'Driver'}
              </strong>

              <br />

              {driver?.bus_number
                ? `Bus: ${driver?.bus_number}`
                : 'Driver location'}

              {driver?.phone_number && (
                <>
                  <br />
                  Phone: {driver?.phone_number}
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
        <RoadLayer geometry={routeGeometry} stages={stages} lat={driverLat} lng={driverLng} showStops={false} />
</MapContainer>
      </TiltedMapFrame>
      {tilt && <MapZoomButtons />}
      <NextStageBanner next={nextStage} />
    </div>
  );
}
