import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  BusFront,
  CheckCircle2,
  Clock3,
  Crosshair,
  Gauge,
  LogOut,
  MapPin,
  Menu,
  Navigation,
  RefreshCw,
  ShieldCheck,
  UserRound,
  Users,
  X,
} from 'lucide-react';
import { apiRequest } from '../../api';
import { useAuth } from '../../context/AuthContext';
import ConnectMap from '../../components/maps/ConnectMap';
import useBookingLiveLocation from '../../hooks/useBookingLiveLocation';

const formatDate = (value) =>
  value
    ? new Date(value).toLocaleString('en-KE', {
        dateStyle: 'medium',
        timeStyle: 'short',
      })
    : '—';

function DriverShell({ user, driver, logout, children }) {
  const [mobileOpen, setMobileOpen] = useState(false);

  const closeMobile = () => setMobileOpen(false);

  return (
    <div className="driver-app">
      <aside className={`driver-sidebar ${mobileOpen ? 'driver-sidebar-open' : ''}`}>
        <div className="driver-brand">
          <div className="driver-brand-mark">C</div>
          <div>
            <strong>CONNECT</strong>
            <span>Driver portal</span>
          </div>
        </div>

        <nav className="driver-nav">
          <a href="#overview" onClick={closeMobile} className="driver-nav-item active">
            <Gauge size={18} />
            <span>Dashboard</span>
          </a>

          <a href="#trips" onClick={closeMobile} className="driver-nav-item">
            <BusFront size={18} />
            <span>My trips</span>
          </a>

          <a href="#passengers" onClick={closeMobile} className="driver-nav-item">
            <Users size={18} />
            <span>Passengers</span>
          </a>

          <a href="#location" onClick={closeMobile} className="driver-nav-item">
            <Navigation size={18} />
            <span>Live location</span>
          </a>

          <a href="#profile" onClick={closeMobile} className="driver-nav-item">
            <UserRound size={18} />
            <span>Profile</span>
          </a>
        </nav>

        <div className="driver-sidebar-bottom">
          <div className="driver-mini-profile">
            <div className="driver-avatar">
              {(user?.name || 'D').charAt(0).toUpperCase()}
            </div>
            <div className="driver-mini-copy">
              <strong>{user?.name || 'Driver'}</strong>
              <span>{driver?.company_name || 'CONNECT'}</span>
            </div>
          </div>

          <button className="driver-signout" onClick={logout}>
            <LogOut size={17} />
            Sign out
          </button>
        </div>
      </aside>

      {mobileOpen && (
        <button
          className="driver-mobile-backdrop"
          aria-label="Close navigation"
          onClick={closeMobile}
        />
      )}

      <main className="driver-main">
        <header className="driver-topbar">
          <div>
            <button
              className="driver-mobile-menu"
              onClick={() => setMobileOpen(true)}
              aria-label="Open navigation"
            >
              <Menu size={20} />
            </button>

            <div className="driver-topbar-title">
              <span>DRIVER PORTAL</span>
              <strong>Today's operations</strong>
            </div>
          </div>

          <div className="driver-topbar-user">
            <div className="driver-status-dot" />
            <span>{driver?.company_name || 'CONNECT'}</span>
            <div className="driver-topbar-avatar">
              {(user?.name || 'D').charAt(0).toUpperCase()}
            </div>
          </div>
        </header>

        {children}
      </main>
    </div>
  );
}

function StatCard({ icon: Icon, label, value, detail, tone = 'green' }) {
  return (
    <div className={`driver-stat-card driver-stat-${tone}`}>
      <div className="driver-stat-icon">
        <Icon size={20} />
      </div>
      <div className="driver-stat-content">
        <span>{label}</span>
        <strong>{value}</strong>
        {detail && <small>{detail}</small>}
      </div>
    </div>
  );
}

function BookingCard({ booking, onBoard }) {
  const confirmed = booking.status === 'confirmed';

  return (
    <article className="driver-booking-card">
      <div className="driver-booking-header">
        <div>
          <span className="driver-booking-number">{booking.booking_number}</span>
          <h3>{booking.passenger || 'Passenger'}</h3>
        </div>

        <span className={`driver-booking-status ${confirmed ? 'confirmed' : 'other'}`}>
          {confirmed ? 'Confirmed' : booking.status}
        </span>
      </div>

      <div className="driver-route-box">
        <MapPin size={17} />
        <div>
          <span>Route</span>
          <strong>{booking.route || 'Assigned route'}</strong>
        </div>
      </div>

      <div className="driver-booking-details">
        <div>
          <span>Pickup</span>
          <strong>{booking.pickup_location || '—'}</strong>
        </div>

        <div>
          <span>Seats</span>
          <strong>{booking.seats || 0}</strong>
        </div>

        <div>
          <span>Payment</span>
          <strong>{booking.payment_status || '—'}</strong>
        </div>

        <div>
          <span>Departure</span>
          <strong>{formatDate(booking.departure_at)}</strong>
        </div>
      </div>

      {confirmed && (
        <button
          className="driver-board-button"
          onClick={() => onBoard(booking.booking_id)}
        >
          <ShieldCheck size={17} />
          Verify boarding
        </button>
      )}
    </article>
  );
}

export default function DriverDashboard() {
  const { user, logout } = useAuth();

  const [driver, setDriver] = useState(null);
  const [bookings, setBookings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [location, setLocation] = useState(null);
  const [mapExpanded, setMapExpanded] = useState(false);
  const [selectedMapBooking, setSelectedMapBooking] = useState(null);
  const [routeMap, setRouteMap] = useState(null);
  const [boardingBooking, setBoardingBooking] = useState(null);
  const [boardingPin, setBoardingPin] = useState('');
  const [boardingError, setBoardingError] = useState('');
  const [boardingSubmitting, setBoardingSubmitting] = useState(false);

  const load = useCallback(async (showRefresh = false) => {
    try {
      if (showRefresh) setRefreshing(true);
      setError('');

      const driverProfile = await apiRequest('/drivers/me/');
      setDriver(driverProfile);

      const assignedBookings = await apiRequest(
        `/bookings/driver/${driverProfile.id}/`,
      );

      setBookings(assignedBookings || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const loadRouteMap = useCallback(async (booking) => {
    if (!booking?.route_id || !booking?.trip_id) {
      setRouteMap(null);
      return;
    }

    try {
      const data = await apiRequest(
        `/companies/routes/${booking.route_id}/map/?trip_id=${booking.trip_id}`,
      );

      setRouteMap(data);
    } catch (err) {
      console.error("Unable to load the trip route map:", err);
      setRouteMap(null);
      setError(err.message || "Unable to load the trip route map.");
    }
  }, []);

  useEffect(() => {
    loadRouteMap(selectedMapBooking);
  }, [selectedMapBooking, loadRouteMap]);

  const selectedBookingId = selectedMapBooking?.booking_id || null;

  const {
    liveLocation,
    loading: liveLocationLoading,
    error: liveLocationError,
  } = useBookingLiveLocation(
    selectedBookingId,
    Boolean(selectedBookingId),
  );

  useEffect(() => {
    if (!selectedMapBooking && bookings.length) {
      setSelectedMapBooking(bookings[0]);
    }

    if (
      selectedMapBooking &&
      !bookings.some(
        (booking) => booking.booking_id === selectedMapBooking.booking_id,
      )
    ) {
      setSelectedMapBooking(bookings[0] || null);
    }
  }, [bookings, selectedMapBooking]);

  const sendDriverLocation = useCallback(
    async (position) => {
      if (!driver) return;
      // Simulator mode: never post the laptop's fixed GPS.
      if (window.location.search.includes('sim=1') || window.localStorage.getItem('sim') === '1') return;

      try {
        setError('');

        const updatedDriver = await apiRequest(
          `/drivers/${driver.id}/location/`,
          {
            method: 'POST',
            body: {
              latitude: position.coords.latitude,
              longitude: position.coords.longitude,
            },
          },
        );

        setLocation(updatedDriver);
        setDriver((current) => ({
          ...current,
          ...updatedDriver,
        }));

        // GPS is now active — open the live map automatically.
        setMapExpanded(true);
      } catch (err) {
        setError(err.message || 'Unable to update driver location.');
      }
    },
    [driver],
  );

  const locate = useCallback(() => {
    if (!driver) return;

    if (!navigator.geolocation) {
      setError('Location services are not available on this device.');
      return;
    }

    navigator.geolocation.getCurrentPosition(
      sendDriverLocation,
      () => {
        setError('Location permission was not granted.');
      },
      {
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 5000,
      },
    );
  }, [driver, sendDriverLocation]);

  // Location is requested only on the live-location page or via locate(),
  // not automatically when the dashboard opens after login.

  const openBoardingModal = (booking) => {
    setBoardingBooking(booking);
    setBoardingPin('');
    setBoardingError('');
    setError('');
  };

  const closeBoardingModal = () => {
    if (boardingSubmitting) return;

    setBoardingBooking(null);
    setBoardingPin('');
    setBoardingError('');
  };

  const board = async () => {
    if (!boardingBooking) return;

    const pin = boardingPin.trim();

    if (!pin) {
      setBoardingError('Enter the passenger boarding PIN.');
      return;
    }

    if (!/^\d{4,6}$/.test(pin)) {
      setBoardingError('The boarding PIN must be 4 to 6 digits.');
      return;
    }

    try {
      setBoardingSubmitting(true);
      setBoardingError('');
      setError('');

      await apiRequest(
        `/bookings/${boardingBooking.booking_id}/verify-boarding/`,
        {
          method: 'POST',
          body: { boarding_pin: pin },
        },
      );

      setBoardingBooking(null);
      setBoardingPin('');
      setBoardingError('');

      await load();
    } catch (err) {
      setBoardingError(err.message || 'Unable to verify boarding.');
    } finally {
      setBoardingSubmitting(false);
    }
  };

  const confirmedBookings = useMemo(
    () => bookings.filter((booking) => booking.status === 'confirmed').length,
    [bookings],
  );

  const upcomingBookings = useMemo(
    () =>
      bookings.filter(
        (booking) =>
          booking.departure_at &&
          new Date(booking.departure_at) > new Date(),
      ).length,
    [bookings],
  );

  return (
    <DriverShell user={user} driver={driver} logout={logout}>
      <div className="driver-content">
        <section className="driver-welcome" id="overview">
          <div>
            <span className="driver-eyebrow">GOOD TO SEE YOU</span>
            <h1>
              Welcome, {driver?.name || user?.name || 'Driver'}
            </h1>
            <p>
              Stay on top of your trips, passengers and vehicle operations.
            </p>
          </div>

          <div className="driver-vehicle-chip">
            <BusFront size={20} />
            <div>
              <span>Assigned vehicle</span>
              <strong>{driver?.bus_number || 'Not assigned'}</strong>
            </div>
          </div>
        </section>

        {error && (
          <div className="driver-error">
            <span>{error}</span>
            <button onClick={() => setError('')} aria-label="Dismiss error">
              <X size={17} />
            </button>
          </div>
        )}

        <section className="driver-stats">
          <StatCard
            icon={Users}
            label="Assigned passengers"
            value={bookings.length}
            detail={`${confirmedBookings} confirmed`}
          />

          <StatCard
            icon={Clock3}
            label="Upcoming assignments"
            value={upcomingBookings}
            detail="Future bookings"
            tone="blue"
          />

          <StatCard
            icon={BusFront}
            label="Vehicle"
            value={driver?.bus_number || '—'}
            detail={driver?.company_name || 'No company'}
            tone="purple"
          />

          <StatCard
            icon={CheckCircle2}
            label="Availability"
            value={driver?.is_available ? 'Available' : 'Unavailable'}
            detail="Current driver status"
            tone={driver?.is_available ? 'green' : 'amber'}
          />
        </section>

        <section className="driver-primary-grid">
          <article className="driver-panel driver-location-panel" id="location">
            <div className="driver-panel-heading">
              <div>
                <span className="driver-panel-kicker">LIVE OPERATIONS</span>
                <h2>Live location</h2>
              </div>

              <div className="driver-live-indicator">
                <span />
                GPS
              </div>
            </div>

            <div
              className={
                mapExpanded
                  ? "driver-location-map driver-location-map-expanded"
                  : "driver-location-map"
              }
            >
              {mapExpanded && (
                <button
                  type="button"
                  className="driver-map-back-button"
                  onClick={() => setMapExpanded(false)}
                >
                  ← Back to Dashboard
                </button>
              )}

              <ConnectMap
                driver={
                  location || liveLocation?.driver || driver
                    ? {
                        ...(driver || {}),
                        ...(liveLocation?.driver || {}),
                        ...(location || {}),
                      }
                    : null
                }
                passenger={liveLocation?.passenger}
                routeGeometry={routeMap?.geometry}
                stages={routeMap?.stages || []}
                pickup={routeMap?.stages?.find(
                  (stage) => stage.id === selectedMapBooking?.pickup_stage_id,
                )}
                showDriver
                showPassenger
                height={mapExpanded ? "100%" : 440}
                zoom={13}
              />
            </div>

            <div className="driver-map-controls">
              <div className="driver-map-status">
                <div className="driver-location-icon">
                  <Crosshair size={24} />
                </div>

                <div className="driver-location-copy">
                  <strong>
                    {location || driver?.location_updated_at
                      ? 'GPS location active'
                      : 'Waiting for GPS'}
                  </strong>

                  <span>
                    {location?.location_updated_at
                      ? `Updated ${formatDate(location.location_updated_at)}`
                      : driver?.location_updated_at
                        ? `Last update ${formatDate(driver.location_updated_at)}`
                        : 'Allow location access to start live tracking.'}
                  </span>
                </div>
              </div>

              <button
                className="driver-primary-button"
                onClick={locate}
                disabled={!driver}
              >
                <Navigation size={17} />
                Update location
              </button>
            </div>

            <div className="driver-map-passenger">
              <div>
                <span className="driver-panel-kicker">TRACK PASSENGER</span>
                <strong>
                  {selectedMapBooking
                    ? selectedMapBooking.passenger || 'Passenger'
                    : 'Select an assigned passenger'}
                </strong>
              </div>

              <select
                className="driver-map-select"
                value={selectedMapBooking?.booking_id || ''}
                onChange={(event) => {
                  const booking = bookings.find(
                    (item) =>
                      String(item.booking_id) === event.target.value,
                  );

                  setSelectedMapBooking(booking || null);
                }}
                disabled={!bookings.length}
              >
                <option value="">
                  {bookings.length
                    ? 'Select passenger'
                    : 'No assigned passengers'}
                </option>

                {bookings.map((booking) => (
                  <option
                    key={booking.booking_id}
                    value={booking.booking_id}
                  >
                    {booking.passenger || 'Passenger'} — {booking.booking_number}
                  </option>
                ))}
              </select>
            </div>

            {selectedMapBooking && (
              <div className="driver-map-live-info">
                <div>
                  <span>Passenger pickup</span>
                  <strong>
                    {selectedMapBooking.pickup_location || 'Pickup location not provided'}
                  </strong>
                </div>

                <div>
                  <span>Live tracking</span>
                  <strong>
                    {liveLocationLoading
                      ? 'Updating…'
                      : liveLocationError
                        ? 'Unavailable'
                        : liveLocation?.passenger?.latitude != null
                          ? 'Passenger location available'
                          : 'Waiting for passenger GPS'}
                  </strong>
                </div>
              </div>
            )}
          </article>

          <article className="driver-panel driver-profile-panel" id="profile">
            <div className="driver-panel-heading">
              <div>
                <span className="driver-panel-kicker">DRIVER PROFILE</span>
                <h2>Your details</h2>
              </div>
              <UserRound size={20} />
            </div>

            <div className="driver-profile-list">
              <div>
                <span>Username</span>
                <strong>{user?.name || '—'}</strong>
              </div>

              <div>
                <span>Company</span>
                <strong>{driver?.company_name || '—'}</strong>
              </div>

              <div>
                <span>Phone</span>
                <strong>{driver?.phone_number || user?.phone || '—'}</strong>
              </div>

              <div>
                <span>Vehicle</span>
                <strong>{driver?.bus_number || '—'}</strong>
              </div>
            </div>
          </article>
        </section>

        <section className="driver-bookings-section" id="passengers">
          <div className="driver-section-heading">
            <div>
              <span className="driver-panel-kicker">PASSENGER OPERATIONS</span>
              <h2>Assigned passengers</h2>
              <p>Verify boarding when passengers arrive for their trip.</p>
            </div>

            <button
              className="driver-refresh-button"
              onClick={() => load(true)}
              disabled={loading || refreshing}
            >
              <RefreshCw size={16} className={refreshing ? 'driver-spin' : ''} />
              {refreshing ? 'Refreshing' : 'Refresh'}
            </button>
          </div>

          <div id="trips">
            {loading ? (
              <div className="driver-empty-state">
                <div className="driver-loading-spinner" />
                <strong>Loading assignments</strong>
                <span>Fetching your current passenger bookings…</span>
              </div>
            ) : !bookings.length ? (
              <div className="driver-empty-state">
                <div className="driver-empty-icon">
                  <Users size={25} />
                </div>
                <strong>No assigned passengers</strong>
                <span>
                  Passenger assignments will appear here when your company
                  assigns bookings to your vehicle.
                </span>
              </div>
            ) : (
              <div className="driver-bookings-grid">
                {bookings.map((booking) => (
                  <BookingCard
                    key={booking.booking_id}
                    booking={booking}
                    onBoard={() => openBoardingModal(booking)}
                  />
                ))}
              </div>
            )}
          </div>
        </section>
      </div>

      {boardingBooking && (
        <div
          className="driver-modal-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              closeBoardingModal();
            }
          }}
        >
          <div
            className="driver-boarding-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="boarding-modal-title"
          >
            <div className="driver-boarding-modal-icon">
              <ShieldCheck size={26} />
            </div>

            <div className="driver-boarding-modal-header">
              <div>
                <span>PASSENGER OPERATIONS</span>
                <h2 id="boarding-modal-title">Verify boarding</h2>
              </div>

              <button
                type="button"
                className="driver-boarding-close"
                onClick={closeBoardingModal}
                disabled={boardingSubmitting}
                aria-label="Close boarding verification"
              >
                <X size={20} />
              </button>
            </div>

            <div className="driver-boarding-summary">
              <div>
                <span>Passenger</span>
                <strong>
                  {boardingBooking.passenger || 'Passenger'}
                </strong>
              </div>

              <div>
                <span>Booking</span>
                <strong>
                  {boardingBooking.booking_number || boardingBooking.booking_id}
                </strong>
              </div>

              <div>
                <span>Route</span>
                <strong>
                  {boardingBooking.route || 'Assigned route'}
                </strong>
              </div>
            </div>

            <div className="driver-boarding-form">
              <label htmlFor="boarding-pin">
                Boarding PIN
              </label>

              <input
                id="boarding-pin"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                value={boardingPin}
                onChange={(event) => {
                  const value = event.target.value
                    .replace(/\D/g, '')
                    .slice(0, 6);

                  setBoardingPin(value);
                  setBoardingError('');
                }}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                    board();
                  }

                  if (event.key === 'Escape') {
                    closeBoardingModal();
                  }
                }}
                placeholder="Enter boarding PIN"
                autoFocus
                disabled={boardingSubmitting}
              />

              <span className="driver-boarding-help">
                Ask the passenger for the PIN shown in their booking.
              </span>

              {boardingError && (
                <div className="driver-boarding-error">
                  <X size={16} />
                  <span>{boardingError}</span>
                </div>
              )}
            </div>

            <div className="driver-boarding-actions">
              <button
                type="button"
                className="driver-boarding-cancel"
                onClick={closeBoardingModal}
                disabled={boardingSubmitting}
              >
                Cancel
              </button>

              <button
                type="button"
                className="driver-boarding-submit"
                onClick={board}
                disabled={boardingSubmitting || boardingPin.length < 4}
              >
                {boardingSubmitting ? (
                  <>
                    <span className="driver-button-spinner" />
                    Verifying…
                  </>
                ) : (
                  <>
                    <ShieldCheck size={17} />
                    Verify boarding
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </DriverShell>
  );
}
