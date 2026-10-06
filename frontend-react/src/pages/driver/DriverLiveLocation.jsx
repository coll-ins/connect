import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowLeft,
  Crosshair,
  MapPin,
  Navigation,
  Users,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { apiRequest } from '../../api';
import ConnectMap from '../../components/maps/ConnectMap';

const formatDate = (value) =>
  value
    ? new Date(value).toLocaleString('en-KE', {
        dateStyle: 'medium',
        timeStyle: 'short',
      })
    : '—';

export default function DriverLiveLocation() {
  const navigate = useNavigate();

  const [driver, setDriver] = useState(null);
  const [activeTrip, setActiveTrip] = useState(null);
  const [location, setLocation] = useState(null);
  const [error, setError] = useState('');
  const [sheetOpen, setSheetOpen] = useState(false);
  const [endingTrip, setEndingTrip] = useState(false);

  const watchRef = useRef(null);
  const driverRef = useRef(null);
  const driverIdRef = useRef(null);
  const lastSentAtRef = useRef(0);
  const sendingRef = useRef(false);

  /*
   * ------------------------------------------------------------
   * LOAD DRIVER + SINGLE ACTIVE TRIP
   * ------------------------------------------------------------
   *
   * The backend decides which trip belongs on the driver's board.
   * The frontend does NOT select a booking or build a route.
   */
  const load = useCallback(async () => {
    try {
      setError('');

      const profile = await apiRequest('/drivers/me/');
      // Keep the live GPS position; the profile can hold a stale one.
      setDriver((current) => ({
        ...profile,
        latitude: current?.latitude ?? profile.latitude,
        longitude: current?.longitude ?? profile.longitude,
      }));

      const data = await apiRequest(`/bookings/driver/${profile.id}/`);





      setDriver((current) => ({
        ...(current || {}),
        ...(data?.driver || {}),
      }));

      setActiveTrip(data?.active_trip || null);
    } catch (err) {
      console.error('[DRIVER LIVE] load error:', err);
      setError(err.message || 'Unable to load live trip data.');
      // keep the last known trip so the route and bus survive one bad poll
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    const refresh = async () => {
      if (cancelled) return;
      await load();
    };

    refresh();

    // Keep the driver's map synchronized with the backend.
    // This is what allows the simulator and real GPS updates
    // to animate on the driver map.
    const interval = setInterval(refresh, 10000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [load]);

  /*
   * ------------------------------------------------------------
   * SEND DRIVER GPS
   * ------------------------------------------------------------
   */
  useEffect(() => {
    driverRef.current = driver;

    if (driver?.id) {
      driverIdRef.current = driver.id;
    }
  }, [driver]);

  const sendLocation = useCallback(async (position, force = false) => {
    const currentDriver = driverRef.current;
    const driverId = currentDriver?.id ?? driverIdRef.current;

    if (!driverId || sendingRef.current) return;

    const simulatorMode =
      window.location.search.includes('sim=1') ||
      window.localStorage.getItem('sim') === '1';

    if (simulatorMode) return;

    const now = Date.now();

    // Django throttles this endpoint at roughly 3 seconds.
    // Keep a small safety margin so we do not hit 429 responses.
    if (!force && now - lastSentAtRef.current < 4000) {
      return;
    }

    // Even a forced/initial GPS update must respect the backend throttle.
    if (force && lastSentAtRef.current && now - lastSentAtRef.current < 4000) {
      return;
    }

    sendingRef.current = true;
    lastSentAtRef.current = now;

    try {
      const updated = await apiRequest(
        `/drivers/${driverId}/location/`,
        {
          method: 'POST',
          body: {
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
          },
        },
      );

      console.info(
        '[DRIVER LIVE] GPS sent successfully:',
        position.coords.latitude,
        position.coords.longitude,
      );

      setLocation(updated);

      setDriver((current) => ({
        ...(current || {}),
        ...(updated || {}),
      }));
    } catch (err) {
      console.error('[DRIVER LIVE] GPS update error:', err);

      // Do not turn a temporary throttle into a permanent page error.
      if (!String(err.message || '').includes('throttled')) {
        setError(err.message || 'Unable to update GPS location.');
      }
    } finally {
      sendingRef.current = false;
    }
  }, []);


  /*
   * ------------------------------------------------------------
   * CONTINUOUS DRIVER GPS WATCH
   * ------------------------------------------------------------
   */
  useEffect(() => {
    const simulatorMode =
      window.location.search.includes('sim=1') ||
      window.localStorage.getItem('sim') === '1';

    const driverId = driver?.id ?? null;

    console.info('[DRIVER LIVE] GPS effect state:', {
      driverId,
      hasGeolocation: !!navigator.geolocation,
      simulatorMode,
    });

    if (!driverId || !navigator.geolocation || simulatorMode) {
      console.warn('[DRIVER LIVE] GPS watcher NOT started:', {
        driverId,
        hasGeolocation: !!navigator.geolocation,
        simulatorMode,
      });
      return undefined;
    }

    let active = true;

    const gpsOptions = {
      enableHighAccuracy: true,
      timeout: 15000,
      maximumAge: 5000,
    };

    console.info(
      '[DRIVER LIVE] Starting GPS watcher for driver:',
      driverId,
    );

    navigator.geolocation.getCurrentPosition(
      (position) => {
        if (!active) return;

        console.info(
          '[DRIVER LIVE] Initial GPS:',
          position.coords.latitude,
          position.coords.longitude,
        );

        sendLocation(position, true);
      },
      (error) => {
        if (!active) return;

        console.error(
          '[DRIVER LIVE] Initial GPS error:',
          error.code,
          error.message,
        );

        setError(
          error.message
            ? `GPS error: ${error.message}`
            : 'Unable to read your GPS location.',
        );
      },
      {
        ...gpsOptions,
        maximumAge: 0,
      },
    );

    const watchId = navigator.geolocation.watchPosition(
      (position) => {
        if (!active) return;

        console.info(
          '[DRIVER LIVE] GPS update:',
          position.coords.latitude,
          position.coords.longitude,
        );

        sendLocation(position);
      },
      (error) => {
        if (!active) return;

        console.error(
          '[DRIVER LIVE] GPS watch error:',
          error.code,
          error.message,
        );

        setError(
          error.message
            ? `GPS error: ${error.message}`
            : 'Unable to read your GPS location.',
        );
      },
      gpsOptions,
    );

    watchRef.current = watchId;

    return () => {
      active = false;
      navigator.geolocation.clearWatch(watchId);
      watchRef.current = null;

      console.info('[DRIVER LIVE] GPS watcher stopped');
    };
  }, [driver?.id, sendLocation]);


  /*
   * ------------------------------------------------------------
   * MANUAL GPS LOCATION
   * ------------------------------------------------------------
   */
  const locate = useCallback(() => {
    if (!navigator.geolocation) {
      setError('Location services are unavailable.');
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (position) => {
        sendLocation(position, true);
      },
      () => {
        setError('Location permission was not granted.');
      },
      {
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 0,
      },
    );
  }, [sendLocation]);

  /*
   * ------------------------------------------------------------
   * MAP DRIVER
   * ------------------------------------------------------------
   *
   * Driver GPS comes from the live GPS update when available,
   * otherwise from the driver's stored profile location.
   */
  const mapDriver = useMemo(() => {
    if (!driver && !location) return null;

    // Polled backend position (simulator / real GPS) wins.
    // Browser geolocation is only a fallback.
    const base = { ...(location || {}), ...(driver || {}) };

    if (driver?.latitude == null || driver?.longitude == null) {
      base.latitude = location?.latitude;
      base.longitude = location?.longitude;
    }

    return base;
  }, [driver, location]);

  // Tick so GPS age keeps updating even when no new data arrives.
  const [nowTick, setNowTick] = useState(() => Date.now());

  useEffect(() => {
    const id = window.setInterval(() => setNowTick(Date.now()), 5000);
    return () => window.clearInterval(id);
  }, []);

  const gpsAgeSec = useMemo(() => {
    const t = Date.parse(mapDriver?.location_updated_at || '');
    return Number.isFinite(t) ? Math.max(0, (nowTick - t) / 1000) : null;
  }, [mapDriver, nowTick]);

  const gpsLost = gpsAgeSec != null && gpsAgeSec > 120;

  /*
   * ------------------------------------------------------------
   * TRIP DATA
   * ------------------------------------------------------------
   *
   * IMPORTANT:
   * route_geometry is authoritative.
   *
   * The map receives the route exactly as stored on Route.geometry.
   * Bookings/passengers NEVER modify this geometry.
   */
  const routeGeometry = activeTrip?.route_geometry || {
    type: 'LineString',
    coordinates: [],
  };

  const stages = activeTrip?.stages || [];
  const bookings = activeTrip?.bookings || [];

  const passengerCount =
    activeTrip?.passenger_count ??
    bookings.reduce(
      (total, booking) => total + Number(booking.seats || 0),
      0,
    );

  const bookingCount =
    activeTrip?.booking_count ?? bookings.length;

  const [reportOpen, setReportOpen] = useState(false);
  const [reportType, setReportType] = useState('breakdown');
  const [reportText, setReportText] = useState('');
  const [reportSending, setReportSending] = useState(false);
  const [reportDone, setReportDone] = useState('');

  const submitIncident = async () => {
    const tripId =
      activeTrip?.id ?? activeTrip?.trip_id ?? activeTrip?.trip?.id;

    if (!tripId) {
      setError('Could not find the trip id for this report.');
      return;
    }

    setReportSending(true);

    try {
      await apiRequest('/bookings/incidents/report/', {
        method: 'POST',
        body: {
          trip_id: tripId,
          incident_type: reportType,
          description: reportText.trim(),
        },
      });

      setReportDone('Problem reported.');
      setReportOpen(false);
      setReportText('');
    } catch (err) {
      setError(err.message || 'Unable to report the problem.');
    } finally {
      setReportSending(false);
    }
  };

  const endTrip = async () => {
    if (!driver || endingTrip) return;
    if (!window.confirm('End this trip for all passengers?')) return;

    setEndingTrip(true);
    setError('');

    try {
      const result = await apiRequest(
        `/bookings/driver/${driver.id}/end-trip/`,
        { method: 'POST' },
      );

      const settled = result?.no_shows_settled ?? 0;
      const held = result?.incident_protected ?? 0;
      const parts = ['Trip completed.'];
      if (settled > 0) {
        parts.push(`${settled} passenger(s) who did not board were marked no-show.`);
      }
      if (held > 0) {
        parts.push(`${held} booking(s) are held so passengers can choose a refund or a new trip.`);
      }
      setReportDone(parts.join(' '));

      setActiveTrip(null);
      await load();
    } catch (err) {
      setError(err.message || 'Unable to end the trip.');
    } finally {
      setEndingTrip(false);
    }
  };

  return (
    <div className="driver-live-page">
      <div className="driver-live-map">
        <ConnectMap
          driver={mapDriver}
          passenger={null}
          routeGeometry={routeGeometry}
          stages={stages}
          pickup={null}
          showDriver
          showPassenger={false}
          height="100%"
          zoom={14}
        />

        {gpsLost && (
          <div
            role="status"
            style={{
              position: 'absolute',
              top: 12,
              left: '50%',
              transform: 'translateX(-50%)',
              zIndex: 1000,
              padding: '8px 14px',
              borderRadius: 999,
              background: 'rgba(180, 40, 40, 0.88)',
              color: '#fff',
              fontSize: 13,
              fontWeight: 600,
              backdropFilter: 'blur(8px)',
              boxShadow: '0 4px 14px rgba(0,0,0,0.25)',
            }}
          >
            GPS signal lost · last update {Math.round(gpsAgeSec / 60)} min ago
          </div>
        )}

        <button
          type="button"
          className="driver-live-back"
          onClick={() => navigate('/driver')}
        >
          <ArrowLeft size={19} />
          Dashboard
        </button>

        <div className="driver-live-status">
          <span />
          GPS LIVE
        </div>
      </div>

      <section
        className={`driver-live-sheet ${
          sheetOpen ? 'driver-live-sheet-open' : ''
        }`}
      >
        <button
          type="button"
          className="driver-live-handle"
          onClick={() => setSheetOpen((open) => !open)}
          aria-label="Toggle trip details"
        >
          <span />
        </button>

        <div className="driver-live-sheet-header">
          <div>
            <span>LIVE TRIP</span>

            <h1>
              {activeTrip?.route_name || 'No assigned trip'}
            </h1>
          </div>

          <button
            type="button"
            className="driver-live-locate"
            onClick={locate}
            aria-label="Locate me"
          >
            <Crosshair size={19} />
          </button>
        </div>

        {activeTrip ? (
          <>
            <div className="driver-live-route">
              <MapPin size={18} />

              <div>
                <strong>
                  {activeTrip.route_name || 'Assigned route'}
                </strong>

                <span>
                  Departure: {formatDate(activeTrip.departure_at)}
                </span>
              </div>
            </div>

            <div className="driver-live-stats">
              <div>
                <Navigation size={18} />
                <strong>{stages.length}</strong>
                <span>Stages</span>
              </div>

              <div>
                <Users size={18} />
                <strong>{passengerCount}</strong>
                <span>Passengers</span>
              </div>

              <div>
                <Users size={18} />
                <strong>{bookingCount}</strong>
                <span>Bookings</span>
              </div>

              <div>
                <Crosshair size={18} />
                <strong>{location ? 'ON' : 'OFF'}</strong>
                <span>GPS</span>
              </div>
            </div>

            <button
              type="button"
              className="driver-live-end-trip"
              onClick={endTrip}
              disabled={endingTrip}
              style={{
                width: '100%',
                margin: '12px 0',
                padding: '12px 16px',
                borderRadius: 14,
                border: '1px solid rgba(255,255,255,0.25)',
                background: 'rgba(180, 40, 40, 0.9)',
                color: '#fff',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              {endingTrip ? 'Ending trip...' : 'End trip'}
            </button>

            {reportDone && (
              <p style={{ margin: '8px 0', fontSize: 13, color: '#9be3a8' }}>
                {reportDone}
              </p>
            )}

            {reportOpen ? (
              <div style={{ margin: '12px 0' }}>
                <select
                  value={reportType}
                  onChange={(e) => setReportType(e.target.value)}
                  style={{ padding: '10px 12px', borderRadius: 12, border: '1px solid rgba(255,255,255,0.25)', background: 'rgba(255,255,255,0.08)', color: '#fff', width: '100%', marginBottom: 8 }}
                >
                  <option value="breakdown">Breakdown</option>
                  <option value="accident">Accident</option>
                  <option value="road_blocked">Road blocked</option>
                  <option value="stage_issue">Stage issue</option>
                  <option value="other">Other</option>
                </select>

                <textarea
                  value={reportText}
                  onChange={(e) => setReportText(e.target.value)}
                  placeholder="What happened?"
                  rows={3}
                  style={{ padding: '10px 12px', borderRadius: 12, border: '1px solid rgba(255,255,255,0.25)', background: 'rgba(255,255,255,0.08)', color: '#fff', width: '100%', marginBottom: 8 }}
                />

                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    type="button"
                    onClick={submitIncident}
                    disabled={reportSending || !reportText.trim()}
                    style={{ flex: 1, padding: '10px 12px', borderRadius: 12, border: 'none', background: '#d97706', color: '#fff', fontWeight: 600, cursor: 'pointer' }}
                  >
                    {reportSending ? 'Sending...' : 'Send report'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setReportOpen(false)}
                    style={{ padding: '10px 12px', borderRadius: 12, border: '1px solid rgba(255,255,255,0.25)', background: 'transparent', color: '#fff', cursor: 'pointer' }}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => { setReportDone(''); setReportOpen(true); }}
                style={{ width: '100%', margin: '12px 0', padding: '12px 16px', borderRadius: 14, border: '1px solid rgba(255,255,255,0.25)', background: 'rgba(217, 119, 6, 0.9)', color: '#fff', fontWeight: 600, cursor: 'pointer' }}
              >
                Report a problem
              </button>
            )}

            <div className="driver-live-trip-card">
              <label>ASSIGNED TRIP</label>

              <div className="driver-live-trip-info">
                <strong>{activeTrip.route_name}</strong>

                <span>
                  {activeTrip.company_name || 'Transport company'}
                  {' • '}
                  {activeTrip.departure_at
                    ? formatDate(activeTrip.departure_at)
                    : 'Departure pending'}
                </span>

                <span>
                  {activeTrip.start_point || 'Start'}
                  {' → '}
                  {activeTrip.end_point || 'Destination'}
                </span>
              </div>
            </div>

            {activeTrip.bookings?.length > 0 ? (
              <div className="driver-live-passenger-section">
                <label>PASSENGERS ON THIS TRIP</label>

                {activeTrip.bookings.map((booking) => (
                  <div
                    key={booking.booking_id}
                    className="driver-live-passenger-card"
                  >
                    <div className="driver-live-passenger-main">
                      <div className="driver-live-passenger-identity">
                        <strong>
                          {booking.passenger?.name ||
                            booking.passenger ||
                            'Passenger'}
                        </strong>

                        <span className="driver-live-passenger-phone">
                          {booking.passenger?.phone ||
                            booking.passenger_phone ||
                            booking.phone ||
                            'Phone unavailable'}
                        </span>
                      </div>

                      <span className="driver-live-passenger-status">
                        {booking.status || 'pending'}
                      </span>
                    </div>

                    <div className="driver-live-passenger-meta">
                      <div className="driver-live-receipt">
                        <small>RECEIPT</small>
                        <strong>
                          {booking.booking_number || booking.booking_id}
                        </strong>
                      </div>

                      <div>
                        <small>PICKUP</small>
                        <strong>
                          {booking.pickup_stage_name ||
                            booking.pickup_location ||
                            '—'}
                        </strong>
                      </div>

                      <div>
                        <small>SEATS</small>
                        <strong>{booking.seats || 1}</strong>
                      </div>

                      <div>
                        <small>GPS</small>
                        <strong>
                          {booking.passenger_latitude != null &&
                          booking.passenger_longitude != null
                            ? 'Live'
                            : 'Waiting'}
                        </strong>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="driver-live-bookings">
                <label>PASSENGERS</label>
                <div>
                  <strong>No passengers assigned yet</strong>
                  <span>
                    Passengers assigned to this trip will appear here
                    automatically.
                  </span>
                </div>
              </div>
            )}

            <div
              className="driver-live-bookings"
              style={{ marginTop: 14 }}
            >
              <label>PICKUP STAGES</label>

              <div className="driver-live-stage-list">
                {stages.map((stage) => (
                  <div
                    key={stage.id}
                    className={`driver-live-stage-row ${
                      stage.passenger_count > 0
                        ? 'driver-live-stage-assigned'
                        : ''
                    }`}
                  >
                    <span>
                      {stage.order}. {stage.name}
                    </span>

                    <strong>
                      {stage.passenger_count || 0}
                    </strong>
                  </div>
                ))}
              </div>
            </div>
          </>
        ) : (
          <div className="driver-live-bookings">
            <label>
              Assigned trip
            </label>

            <div>
              <strong>No upcoming trip assigned</strong>

              <span>
                Your driver map will appear here when a scheduled
                trip is assigned to you.
              </span>
            </div>
          </div>
        )}

        {error && (
          <div className="driver-live-error">
            {error}
          </div>
        )}

        <button
          type="button"
          className="driver-live-update"
          onClick={locate}
        >
          <Navigation size={18} />
          Update my location
        </button>
      </section>
    </div>
  );
}
