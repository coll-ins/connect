import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertCircle,
  Bell,
  Bus,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  Clock3,
  LayoutDashboard,
  LogOut,
  Menu,
  RefreshCw,
  ShieldCheck,
  Users,
  X,
} from 'lucide-react';
import { apiRequest } from '../../api';
import { useAuth } from '../../context/AuthContext';
import './CompanyOperatorDashboard.css';

const formatDate = (value) => {
  if (!value) return '—';

  return new Date(value).toLocaleString('en-KE', {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
};

const formatShortDate = (value) => {
  if (!value) return '—';

  return new Date(value).toLocaleString('en-KE', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
};

const getBookingId = (booking) =>
  booking.booking_id ?? booking.id ?? booking.booking?.id;

const getBookingDriver = (booking) =>
  booking.driver_name || booking.driver?.name || '';

const getBookingRoute = (booking) => {
  if (booking.route_name) return booking.route_name;

  if (booking.route) {
    if (typeof booking.route === 'string') return booking.route;
    if (booking.route.name) return booking.route.name;
  }

  const origin =
    booking.pickup_location ||
    booking.pickup ||
    booking.start_point ||
    booking.route_details?.start_point;

  const destination =
    booking.destination ||
    booking.end_point ||
    booking.route_details?.end_point;

  if (origin && destination) {
    return `${origin} → ${destination}`;
  }

  return 'Route information unavailable';
};

const getBookingSeats = (booking) =>
  booking.seats ?? booking.number_of_seats ?? booking.seat_count ?? 1;

const getBookingStatus = (booking) =>
  String(booking.status || 'pending').toLowerCase();

const getTripRoute = (trip) => {
  const route = trip.route_details;

  if (route?.name) return route.name;

  if (route?.start_point && route?.end_point) {
    return `${route.start_point} → ${route.end_point}`;
  }

  return trip.route_name || 'Route unavailable';
};

const statusLabel = (status) => {
  const labels = {
    scheduled: 'Scheduled',
    boarding: 'Boarding',
    departed: 'Departed',
    completed: 'Completed',
    cancelled: 'Cancelled',
  };

  return labels[String(status).toLowerCase()] || status || 'Unknown';
};

function StatusBadge({ status }) {
  const normalized = String(status || '').toLowerCase();

  return (
    <span className={`operator-status operator-status-${normalized}`}>
      <span className="operator-status-dot" />
      {statusLabel(status)}
    </span>
  );
}

const navigation = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'bookings', label: 'Bookings', icon: Bell },
  { id: 'departures', label: 'Departures', icon: CalendarDays },
  { id: 'drivers', label: 'Drivers', icon: Users },
  { id: 'capacity', label: 'Capacity', icon: Bus },
  { id: 'operations', label: 'Operations', icon: Activity },
];

function OperatorShell({
  user,
  companyName,
  activeSection,
  setActiveSection,
  onLogout,
  children,
}) {
  const [mobileOpen, setMobileOpen] = useState(false);

  const selectSection = (section) => {
    setActiveSection(section);
    setMobileOpen(false);
  };

  return (
    <div className="operator-app">
      <aside
        className={`operator-sidebar ${
          mobileOpen ? 'operator-sidebar-open' : ''
        }`}
      >
        <div className="operator-brand">
          <div className="operator-brand-mark">
            <Bus size={21} />
          </div>

          <div>
            <strong>CONNECT</strong>
            <span>Operations</span>
          </div>
        </div>

        <div className="operator-company-card">
          <span>COMPANY</span>
          <strong>{companyName}</strong>
          <small>Operator workspace</small>
        </div>

        <nav className="operator-nav" aria-label="Operations navigation">
          <span className="operator-nav-label">WORKSPACE</span>

          {navigation.map((item) => {
            const Icon = item.icon;

            return (
              <button
                key={item.id}
                type="button"
                className={`operator-nav-item ${
                  activeSection === item.id
                    ? 'operator-nav-item-active'
                    : ''
                }`}
                onClick={() => selectSection(item.id)}
              >
                <Icon size={18} />
                <span>{item.label}</span>

                {item.id === 'bookings' && (
                  <ChevronRight size={15} className="operator-nav-arrow" />
                )}
              </button>
            );
          })}
        </nav>

        <div className="operator-sidebar-bottom">
          <div className="operator-user-card">
            <div className="operator-user-avatar">
              {(user?.username || 'O').charAt(0).toUpperCase()}
            </div>

            <div>
              <strong>{user?.username || 'Operator'}</strong>
              <span>Company Operator</span>
            </div>
          </div>

          <button
            type="button"
            className="operator-logout"
            onClick={onLogout}
          >
            <LogOut size={17} />
            Sign out
          </button>
        </div>
      </aside>

      {mobileOpen && (
        <button
          type="button"
          className="operator-mobile-backdrop"
          onClick={() => setMobileOpen(false)}
          aria-label="Close navigation"
        />
      )}

      <main className="operator-main">
        <header className="operator-topbar">
          <button
            type="button"
            className="operator-menu-button"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
          >
            <Menu size={20} />
          </button>

          <div className="operator-topbar-title">
            <span>COMPANY OPERATIONS</span>
            <strong>
              {navigation.find((item) => item.id === activeSection)?.label ||
                'Overview'}
            </strong>
          </div>

          <div className="operator-topbar-right">
            <div className="operator-live-indicator">
              <span />
              Live
            </div>

            <div className="operator-topbar-user">
              <div className="operator-topbar-avatar">
                {(user?.username || 'O').charAt(0).toUpperCase()}
              </div>

              <div>
                <strong>{user?.username || 'Operator'}</strong>
                <span>Operator</span>
              </div>
            </div>
          </div>
        </header>

        <div className="operator-content">{children}</div>
      </main>
    </div>
  );
}

function StatCard({ icon: Icon, label, value, detail, tone = 'green' }) {
  return (
    <article className="operator-stat-card">
      <div className={`operator-stat-icon operator-stat-${tone}`}>
        <Icon size={19} />
      </div>

      <div className="operator-stat-copy">
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
    </article>
  );
}

function NewBookingCard({ booking, onAssign }) {
  const bookingId = getBookingId(booking);

  return (
    <article className="operator-booking-alert">
      <div className="operator-booking-alert-icon">
        <Bell size={19} />
      </div>

      <div className="operator-booking-alert-content">
        <div className="operator-booking-alert-heading">
          <div>
            <span className="operator-eyebrow">NEW BOOKING</span>
            <h3>#{bookingId || '—'}</h3>
          </div>

          <StatusBadge status={getBookingStatus(booking)} />
        </div>

        <strong className="operator-booking-route">
          {getBookingRoute(booking)}
        </strong>

        <div className="operator-booking-meta">
          <span>
            <Users size={14} />
            {getBookingSeats(booking)} seat
            {Number(getBookingSeats(booking)) === 1 ? '' : 's'}
          </span>

          <span>
            <Clock3 size={14} />
            {formatDate(booking.created_at || booking.created)}
          </span>

          {booking.pickup_location && (
            <span>
              <Activity size={14} />
              {booking.pickup_location}
            </span>
          )}
        </div>
      </div>

      <button
        type="button"
        className="operator-primary-button"
        onClick={() => onAssign(booking)}
      >
        Assign driver
        <ChevronRight size={16} />
      </button>
    </article>
  );
}

function BookingRow({ booking, onAssign }) {
  const bookingId = getBookingId(booking);
  const driver = getBookingDriver(booking);

  return (
    <article className="operator-booking-row">
      <div className="operator-booking-main">
        <div className="operator-booking-id">
          <span>BOOKING</span>
          <strong>#{bookingId || '—'}</strong>
        </div>

        <div className="operator-booking-route-cell">
          <strong>{getBookingRoute(booking)}</strong>
          <span>
            {getBookingSeats(booking)} seat
            {Number(getBookingSeats(booking)) === 1 ? '' : 's'}
          </span>
        </div>
      </div>

      <div className="operator-booking-driver">
        <span>DRIVER</span>
        <strong>{driver || 'Not assigned'}</strong>
      </div>

      <StatusBadge status={getBookingStatus(booking)} />

      {!driver && (
        <button
          type="button"
          className="operator-small-button"
          onClick={() => onAssign(booking)}
        >
          Assign
        </button>
      )}
    </article>
  );
}

function TripCard({ trip, onStatusChange, updating }) {
  return (
    <article className="operator-trip-card">
      <div className="operator-trip-card-top">
        <div className="operator-trip-icon">
          <Bus size={19} />
        </div>

        <div className="operator-trip-main">
          <span className="operator-eyebrow">DEPARTURE</span>
          <h3>{getTripRoute(trip)}</h3>
        </div>

        <StatusBadge status={trip.status} />
      </div>

      <div className="operator-trip-details">
        <div>
          <span>DEPARTURE</span>
          <strong>{formatShortDate(trip.departure_at)}</strong>
        </div>

        <div>
          <span>DRIVER</span>
          <strong>{trip.driver_name || 'Not assigned'}</strong>
        </div>

        <div>
          <span>CAPACITY</span>
          <strong>{trip.capacity || '—'} seats</strong>
        </div>
      </div>

      <div className="operator-trip-actions">
        <label htmlFor={`trip-status-${trip.id}`}>
          Operational status
        </label>

        <select
          id={`trip-status-${trip.id}`}
          value={trip.status || 'scheduled'}
          onChange={(event) => onStatusChange(trip, event.target.value)}
          disabled={
            updating ||
            trip.status === 'completed' ||
            trip.status === 'cancelled'
          }
        >
          <option value="scheduled">Scheduled</option>
          <option value="boarding">Boarding</option>
          <option value="departed">Departed</option>
          <option value="completed">Completed</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </div>
    </article>
  );
}

export default function CompanyOperatorDashboard() {
  const { user, logout } = useAuth();

  const [activeSection, setActiveSection] = useState('overview');
  const [trips, setTrips] = useState([]);
  const [drivers, setDrivers] = useState([]);
  const [bookings, setBookings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [assigningBooking, setAssigningBooking] = useState(null);
  const [selectedDriver, setSelectedDriver] = useState('');
  const [savingAssignment, setSavingAssignment] = useState(false);
  const [updatingTrip, setUpdatingTrip] = useState(null);

  const companyId =
    user?.company_id || user?.company?.id || user?.company;

  const loadOperations = useCallback(
    async (showRefresh = false) => {
      if (!companyId) {
        setError(
          'Your operator account is not assigned to a company.'
        );
        setLoading(false);
        return;
      }

      if (showRefresh) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }

      setError('');

      try {
        const [tripData, driverData, bookingData] = await Promise.all([
          apiRequest(`/companies/${companyId}/trips/`),
          apiRequest(`/drivers/?company_id=${companyId}`),
          apiRequest(`/bookings/all/?company_id=${companyId}`),
        ]);

        setTrips(
          Array.isArray(tripData)
            ? tripData
            : tripData?.results || []
        );

        setDrivers(
          Array.isArray(driverData)
            ? driverData
            : driverData?.results || []
        );

        setBookings(
          Array.isArray(bookingData)
            ? bookingData
            : bookingData?.results || []
        );
      } catch (requestError) {
        setError(
          requestError?.message ||
            'Unable to load company operations right now.'
        );
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [companyId]
  );

  useEffect(() => {
    loadOperations();
  }, [loadOperations]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      loadOperations(true);
    }, 30000);

    return () => window.clearInterval(interval);
  }, [loadOperations]);

  const activeBookings = useMemo(
    () =>
      bookings.filter(
        (booking) =>
          !['cancelled', 'completed'].includes(
            getBookingStatus(booking)
          )
      ),
    [bookings]
  );

  const unassignedBookings = useMemo(
    () =>
      activeBookings.filter(
        (booking) => !getBookingDriver(booking)
      ),
    [activeBookings]
  );

  const newBookings = useMemo(
    () =>
      unassignedBookings
        .filter((booking) =>
          ['pending', 'confirmed', 'paid', 'held'].includes(
            getBookingStatus(booking)
          )
        )
        .slice(0, 5),
    [unassignedBookings]
  );

  const upcomingTrips = useMemo(
    () =>
      [...trips]
        .filter(
          (trip) =>
            !['completed', 'cancelled'].includes(
              String(trip.status).toLowerCase()
            )
        )
        .sort(
          (a, b) =>
            new Date(a.departure_at || 0) -
            new Date(b.departure_at || 0)
        ),
    [trips]
  );

  const boardingTrips = useMemo(
    () =>
      trips.filter(
        (trip) =>
          String(trip.status).toLowerCase() === 'boarding'
      ),
    [trips]
  );

  const activeTrips = useMemo(
    () =>
      trips.filter(
        (trip) =>
          !['completed', 'cancelled'].includes(
            String(trip.status).toLowerCase()
          )
      ),
    [trips]
  );

  const handleStatusChange = async (trip, newStatus) => {
    if (trip.status === newStatus) return;

    setUpdatingTrip(trip.id);
    setError('');

    try {
      await apiRequest(
        `/companies/trips/${trip.id}/status/`,
        {
          method: 'POST',
          body: { status: newStatus },
        }
      );

      setTrips((current) =>
        current.map((item) =>
          item.id === trip.id
            ? { ...item, status: newStatus }
            : item
        )
      );
    } catch (requestError) {
      setError(
        requestError?.message ||
          'Unable to update trip status.'
      );
    } finally {
      setUpdatingTrip(null);
    }
  };

  const openAssignment = (booking) => {
    setAssigningBooking(booking);
    setSelectedDriver(
      booking.driver_id ? String(booking.driver_id) : ''
    );
  };

  const closeAssignment = () => {
    if (savingAssignment) return;

    setAssigningBooking(null);
    setSelectedDriver('');
  };

  const handleAssignDriver = async () => {
    if (!assigningBooking || !selectedDriver) return;

    const bookingId = getBookingId(assigningBooking);

    setSavingAssignment(true);
    setError('');

    try {
      await apiRequest(
        `/bookings/${bookingId}/assign-driver/`,
        {
          method: 'POST',
          body: {
            driver_id: Number(selectedDriver),
          },
        }
      );

      const driver = drivers.find(
        (item) =>
          Number(item.id) === Number(selectedDriver)
      );

      setBookings((current) =>
        current.map((booking) =>
          getBookingId(booking) === bookingId
            ? {
                ...booking,
                driver_id: driver?.id,
                driver_name:
                  driver?.name ||
                  driver?.username ||
                  'Assigned',
              }
            : booking
        )
      );

      closeAssignment();
    } catch (requestError) {
      setError(
        requestError?.message ||
          'Unable to assign the selected driver.'
      );
    } finally {
      setSavingAssignment(false);
    }
  };

  const renderOverview = () => (
    <>
      <section className="operator-hero">
        <div>
          <span className="operator-eyebrow">
            LIVE OPERATIONS
          </span>

          <h1>
            Good to see you, {user?.username || 'Operator'}.
          </h1>

          <p>
            Coordinate today's passenger activity, drivers and
            departures from one operational workspace.
          </p>
        </div>

        <button
          type="button"
          className="operator-refresh-button"
          onClick={() => loadOperations(true)}
          disabled={refreshing}
        >
          <RefreshCw
            size={17}
            className={refreshing ? 'operator-spin' : ''}
          />
          {refreshing ? 'Refreshing' : 'Refresh data'}
        </button>
      </section>

      <section className="operator-stat-grid">
        <StatCard
          icon={Bell}
          label="Pending assignment"
          value={unassignedBookings.length}
          detail="Bookings waiting for a driver"
          tone="blue"
        />

        <StatCard
          icon={CalendarDays}
          label="Active departures"
          value={activeTrips.length}
          detail="Trips still in operation"
          tone="green"
        />

        <StatCard
          icon={Bus}
          label="Boarding now"
          value={boardingTrips.length}
          detail="Trips currently boarding"
          tone="purple"
        />

        <StatCard
          icon={Users}
          label="Company drivers"
          value={drivers.length}
          detail="Existing drivers available"
          tone="amber"
        />
      </section>

      <div className="operator-overview-grid">
        <section className="operator-panel operator-panel-wide">
          <div className="operator-panel-heading">
            <div>
              <span className="operator-eyebrow">
                ACTION REQUIRED
              </span>
              <h2>Booking queue</h2>
            </div>

            <button
              type="button"
              className="operator-text-button"
              onClick={() => setActiveSection('bookings')}
            >
              View queue
              <ChevronRight size={16} />
            </button>
          </div>

          {newBookings.length > 0 ? (
            <div className="operator-new-bookings">
              {newBookings.map((booking) => (
                <NewBookingCard
                  key={getBookingId(booking)}
                  booking={booking}
                  onAssign={openAssignment}
                />
              ))}
            </div>
          ) : (
            <div className="operator-clear-state">
              <div>
                <CheckCircle2 size={23} />
              </div>

              <div>
                <strong>No booking assignments waiting</strong>
                <span>
                  New passenger activity will appear here
                  automatically.
                </span>
              </div>
            </div>
          )}
        </section>

        <section className="operator-panel">
          <div className="operator-panel-heading">
            <div>
              <span className="operator-eyebrow">
                SYSTEM
              </span>
              <h2>Operational health</h2>
            </div>
          </div>

          <div className="operator-health">
            <div className="operator-health-icon">
              <ShieldCheck size={21} />
            </div>

            <div>
              <strong>System operational</strong>
              <span>Live company data connected</span>
            </div>

            <span className="operator-health-dot" />
          </div>

          <div className="operator-health-list">
            <div>
              <span>Active bookings</span>
              <strong>{activeBookings.length}</strong>
            </div>

            <div>
              <span>Upcoming trips</span>
              <strong>{upcomingTrips.length}</strong>
            </div>

            <div>
              <span>Boarding</span>
              <strong>{boardingTrips.length}</strong>
            </div>
          </div>
        </section>
      </div>

      <section className="operator-panel">
        <div className="operator-panel-heading">
          <div>
            <span className="operator-eyebrow">
              DEPARTURE BOARD
            </span>
            <h2>Upcoming departures</h2>
          </div>

          <button
            type="button"
            className="operator-text-button"
            onClick={() => setActiveSection('departures')}
          >
            Open departures
            <ChevronRight size={16} />
          </button>
        </div>

        <div className="operator-trip-grid">
          {upcomingTrips.slice(0, 4).map((trip) => (
            <TripCard
              key={trip.id}
              trip={trip}
              onStatusChange={handleStatusChange}
              updating={updatingTrip === trip.id}
            />
          ))}

          {upcomingTrips.length === 0 && (
            <div className="operator-inline-empty">
              No upcoming departures are currently available.
            </div>
          )}
        </div>
      </section>
    </>
  );

  const renderBookings = () => (
    <>
      <section className="operator-page-heading">
        <div>
          <span className="operator-eyebrow">
            BOOKING DESK
          </span>
          <h1>Bookings</h1>
          <p>
            Monitor active passenger bookings and assign
            existing company drivers.
          </p>
        </div>

        <button
          type="button"
          className="operator-refresh-button"
          onClick={() => loadOperations(true)}
          disabled={refreshing}
        >
          <RefreshCw
            size={17}
            className={refreshing ? 'operator-spin' : ''}
          />
          Refresh
        </button>
      </section>

      <section className="operator-panel">
        <div className="operator-panel-heading">
          <div>
            <span className="operator-eyebrow">
              ACTIVE QUEUE
            </span>
            <h2>{activeBookings.length} active bookings</h2>
          </div>

          <div className="operator-count-chip">
            {unassignedBookings.length} unassigned
          </div>
        </div>

        <div className="operator-booking-list">
          {activeBookings.map((booking) => (
            <BookingRow
              key={getBookingId(booking)}
              booking={booking}
              onAssign={openAssignment}
            />
          ))}

          {activeBookings.length === 0 && (
            <div className="operator-inline-empty">
              No active bookings at the moment.
            </div>
          )}
        </div>
      </section>
    </>
  );

  const renderDepartures = () => (
    <>
      <section className="operator-page-heading">
        <div>
          <span className="operator-eyebrow">
            DEPARTURE DESK
          </span>
          <h1>Departures</h1>
          <p>
            Monitor company trips and update their operational
            status.
          </p>
        </div>

        <button
          type="button"
          className="operator-refresh-button"
          onClick={() => loadOperations(true)}
          disabled={refreshing}
        >
          <RefreshCw
            size={17}
            className={refreshing ? 'operator-spin' : ''}
          />
          Refresh
        </button>
      </section>

      <section className="operator-panel">
        <div className="operator-panel-heading">
          <div>
            <span className="operator-eyebrow">
              TRIP CONTROL
            </span>
            <h2>{upcomingTrips.length} operational trips</h2>
          </div>
        </div>

        <div className="operator-trip-grid operator-trip-grid-large">
          {upcomingTrips.map((trip) => (
            <TripCard
              key={trip.id}
              trip={trip}
              onStatusChange={handleStatusChange}
              updating={updatingTrip === trip.id}
            />
          ))}

          {upcomingTrips.length === 0 && (
            <div className="operator-inline-empty">
              No departures are currently available.
            </div>
          )}
        </div>
      </section>
    </>
  );

  const renderDrivers = () => (
    <>
      <section className="operator-page-heading">
        <div>
          <span className="operator-eyebrow">
            DRIVER DESK
          </span>
          <h1>Drivers</h1>
          <p>
            View company drivers and their current booking
            workload.
          </p>
        </div>
      </section>

      <section className="operator-panel">
        <div className="operator-panel-heading">
          <div>
            <span className="operator-eyebrow">
              COMPANY FLEET
            </span>
            <h2>{drivers.length} drivers</h2>
          </div>
        </div>

        <div className="operator-driver-grid">
          {drivers.map((driver) => {
            const driverBookings = activeBookings.filter(
              (booking) =>
                String(booking.driver_id) ===
                  String(driver.id) ||
                getBookingDriver(booking) === driver.name
            );

            const driverName =
              driver.name ||
              driver.username ||
              'Unnamed driver';

            return (
              <article
                key={driver.id}
                className="operator-driver-card"
              >
                <div className="operator-driver-avatar">
                  {driverName.charAt(0).toUpperCase()}
                </div>

                <div className="operator-driver-info">
                  <span>DRIVER</span>
                  <h3>{driverName}</h3>

                  {driver.bus_number && (
                    <small>Bus {driver.bus_number}</small>
                  )}
                </div>

                <div className="operator-driver-activity">
                  <strong>{driverBookings.length}</strong>
                  <span>active bookings</span>
                </div>
              </article>
            );
          })}

          {drivers.length === 0 && (
            <div className="operator-inline-empty">
              No drivers are available for this company.
            </div>
          )}
        </div>
      </section>
    </>
  );

  const renderCapacity = () => (
    <>
      <section className="operator-page-heading">
        <div>
          <span className="operator-eyebrow">
            CAPACITY DESK
          </span>
          <h1>Capacity</h1>
          <p>
            Monitor passenger demand across upcoming
            departures.
          </p>
        </div>
      </section>

      <section className="operator-panel">
        <div className="operator-panel-heading">
          <div>
            <span className="operator-eyebrow">
              SEAT UTILIZATION
            </span>
            <h2>Upcoming trip capacity</h2>
          </div>
        </div>

        <div className="operator-capacity-list">
          {upcomingTrips.map((trip) => {
            const tripBookings = activeBookings.filter(
              (booking) =>
                String(booking.trip_id) === String(trip.id)
            );

            const bookedSeats = tripBookings.reduce(
              (total, booking) =>
                total +
                Number(getBookingSeats(booking) || 0),
              0
            );

            const capacity = Number(trip.capacity || 0);

            const percentage =
              capacity > 0
                ? Math.min(
                    100,
                    (bookedSeats / capacity) * 100
                  )
                : 0;

            return (
              <article
                key={trip.id}
                className="operator-capacity-card"
              >
                <div className="operator-capacity-heading">
                  <div>
                    <span>{getTripRoute(trip)}</span>
                    <strong>
                      {bookedSeats} / {capacity || '—'} seats
                    </strong>
                  </div>

                  <StatusBadge status={trip.status} />
                </div>

                <div className="operator-capacity-track">
                  <div
                    className="operator-capacity-fill"
                    style={{
                      width: `${percentage}%`,
                    }}
                  />
                </div>

                <div className="operator-capacity-footer">
                  <span>
                    {formatShortDate(trip.departure_at)}
                  </span>
                  <span>
                    {Math.round(percentage)}% booked
                  </span>
                </div>
              </article>
            );
          })}

          {upcomingTrips.length === 0 && (
            <div className="operator-inline-empty">
              No capacity data is available.
            </div>
          )}
        </div>
      </section>
    </>
  );

  const renderOperations = () => (
    <>
      <section className="operator-page-heading">
        <div>
          <span className="operator-eyebrow">
            OPERATIONS
          </span>
          <h1>Operational monitor</h1>
          <p>
            Review issues and activity that need operator
            attention.
          </p>
        </div>

        <button
          type="button"
          className="operator-refresh-button"
          onClick={() => loadOperations(true)}
          disabled={refreshing}
        >
          <RefreshCw
            size={17}
            className={refreshing ? 'operator-spin' : ''}
          />
          Refresh
        </button>
      </section>

      <section className="operator-alert-grid">
        <article className="operator-alert-card">
          <div className="operator-alert-icon">
            <AlertCircle size={20} />
          </div>

          <div>
            <span>UNASSIGNED BOOKINGS</span>
            <strong>{unassignedBookings.length}</strong>
            <p>
              Active bookings waiting for driver assignment.
            </p>
          </div>
        </article>

        <article className="operator-alert-card">
          <div className="operator-alert-icon">
            <Bus size={20} />
          </div>

          <div>
            <span>BOARDING</span>
            <strong>{boardingTrips.length}</strong>
            <p>
              Existing trips currently marked as boarding.
            </p>
          </div>
        </article>

        <article className="operator-alert-card operator-alert-good">
          <div className="operator-alert-icon">
            <CheckCircle2 size={20} />
          </div>

          <div>
            <span>SYSTEM STATUS</span>
            <strong>Operational</strong>
            <p>
              Company operational data is refreshing
              automatically.
            </p>
          </div>
        </article>
      </section>

      <section className="operator-panel">
        <div className="operator-panel-heading">
          <div>
            <span className="operator-eyebrow">
              LIVE SNAPSHOT
            </span>
            <h2>Current operating position</h2>
          </div>
        </div>

        <div className="operator-operation-grid">
          <div>
            <span>Active bookings</span>
            <strong>{activeBookings.length}</strong>
          </div>

          <div>
            <span>Unassigned</span>
            <strong>{unassignedBookings.length}</strong>
          </div>

          <div>
            <span>Active trips</span>
            <strong>{activeTrips.length}</strong>
          </div>

          <div>
            <span>Boarding</span>
            <strong>{boardingTrips.length}</strong>
          </div>
        </div>
      </section>
    </>
  );

  const renderSection = () => {
    if (loading) {
      return (
        <div className="operator-loading">
          <RefreshCw
            className="operator-spin"
            size={23}
          />
          <span>Loading company operations...</span>
        </div>
      );
    }

    switch (activeSection) {
      case 'bookings':
        return renderBookings();

      case 'departures':
        return renderDepartures();

      case 'drivers':
        return renderDrivers();

      case 'capacity':
        return renderCapacity();

      case 'operations':
        return renderOperations();

      case 'overview':
      default:
        return renderOverview();
    }
  };

  return (
    <>
      <OperatorShell
        user={user}
        companyName={
          user?.company_name ||
          user?.company?.name ||
          'Company Operations'
        }
        activeSection={activeSection}
        setActiveSection={setActiveSection}
        onLogout={logout}
      >
        {error && (
          <div className="operator-error-banner">
            <AlertCircle size={18} />
            <span>{error}</span>

            <button
              type="button"
              onClick={() => setError('')}
              aria-label="Dismiss error"
            >
              <X size={17} />
            </button>
          </div>
        )}

        {renderSection()}

        <footer className="operator-footer">
          <span>CONNECT Operations</span>
          <span>
            Operator access • Company scoped
          </span>
        </footer>
      </OperatorShell>

      {assigningBooking && (
        <div className="operator-modal-backdrop">
          <div
            className="operator-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="operator-assignment-title"
          >
            <div className="operator-modal-header">
              <div>
                <span className="operator-eyebrow">
                  DRIVER ASSIGNMENT
                </span>
                <h2 id="operator-assignment-title">
                  Assign existing driver
                </h2>
              </div>

              <button
                type="button"
                className="operator-modal-close"
                onClick={closeAssignment}
                disabled={savingAssignment}
                aria-label="Close assignment dialog"
              >
                <X size={19} />
              </button>
            </div>

            <div className="operator-modal-booking">
              <span>
                BOOKING #{getBookingId(assigningBooking)}
              </span>

              <strong>
                {getBookingRoute(assigningBooking)}
              </strong>

              <small>
                {getBookingSeats(assigningBooking)} seat
                {Number(
                  getBookingSeats(assigningBooking)
                ) === 1
                  ? ''
                  : 's'}
              </small>
            </div>

            <label
              className="operator-modal-label"
              htmlFor="operator-driver-select"
            >
              Select company driver
            </label>

            <select
              id="operator-driver-select"
              className="operator-driver-select"
              value={selectedDriver}
              onChange={(event) =>
                setSelectedDriver(event.target.value)
              }
              disabled={savingAssignment}
            >
              <option value="">Choose a driver</option>

              {drivers.map((driver) => (
                <option
                  key={driver.id}
                  value={driver.id}
                >
                  {driver.name ||
                    driver.username ||
                    `Driver ${driver.id}`}
                  {driver.bus_number
                    ? ` • Bus ${driver.bus_number}`
                    : ''}
                </option>
              ))}
            </select>

            <p className="operator-modal-note">
              Operators can assign existing company drivers.
              Driver accounts and driver records remain
              managed by the Company Manager.
            </p>

            <div className="operator-modal-actions">
              <button
                type="button"
                className="operator-secondary-button"
                onClick={closeAssignment}
                disabled={savingAssignment}
              >
                Cancel
              </button>

              <button
                type="button"
                className="operator-primary-button"
                onClick={handleAssignDriver}
                disabled={
                  !selectedDriver || savingAssignment
                }
              >
                {savingAssignment
                  ? 'Assigning...'
                  : 'Assign driver'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
