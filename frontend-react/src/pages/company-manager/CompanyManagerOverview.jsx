import { useCallback, useEffect, useState } from 'react';
import { NavLink } from 'react-router-dom';
import {
  Activity,
  ArrowUpRight,
  Bus,
  CalendarDays,
  ClipboardList,
  Menu,
  Route,
  ShieldCheck,
  Users,
  WalletCards,
} from 'lucide-react';
import { apiRequest } from '../../api';
import { useAuth } from '../../context/AuthContext';

const money = (value) =>
  `KES ${Number(value || 0).toLocaleString('en-KE', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

const formatDate = (value) =>
  value
    ? new Date(value).toLocaleString('en-KE', {
        dateStyle: 'medium',
        timeStyle: 'short',
      })
    : '—';


function Stat({ icon: Icon, label, value, detail }) {
  return (
    <div className="company-stat-card">
      <div className="company-stat-icon">
        <Icon size={19} />
      </div>

      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
    </div>
  );
}

export default function CompanyManagerOverview() {
  const { user, logout } = useAuth();

  const companyId = user?.company_id;

  const [company, setCompany] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [routes, setRoutes] = useState([]);
  const [trips, setTrips] = useState([]);
  const [drivers, setDrivers] = useState([]);
  const [bookings, setBookings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    if (!companyId) {
      setError('Your account is not linked to a company.');
      setLoading(false);
      return;
    }

    setLoading(true);
    setError('');

    try {
      const [companies, analyticsData, routesData, tripsData, driversData, bookingsData] =
        await Promise.all([
          apiRequest('/companies/'),
          apiRequest(`/companies/${companyId}/analytics/`),
          apiRequest(`/companies/${companyId}/routes/`),
          apiRequest(`/companies/${companyId}/trips/`),
          apiRequest(`/drivers/?company_id=${companyId}`),
          apiRequest(`/bookings/all/?company_id=${companyId}`),
        ]);

      const ownCompany = (companies || []).find(
        (item) => Number(item.id) === Number(companyId)
      );

      setCompany(ownCompany || null);
      setAnalytics(analyticsData || null);
      setRoutes(routesData || []);
      setTrips(tripsData || []);
      setDrivers(driversData || []);
      setBookings(bookingsData || []);
    } catch (err) {
      setError(err.message || 'Unable to load company manager data.');
    } finally {
      setLoading(false);
    }
  }, [companyId]);

  useEffect(() => {
    load();
  }, [load]);

  const activeTrips = trips.filter(
    (trip) => !['completed', 'cancelled'].includes(trip.status)
  ).length;

  const activeBookings = bookings.filter(
    (booking) => !['completed', 'cancelled'].includes(booking.status)
  ).length;

  const totalCapacity = trips.reduce(
    (sum, trip) => sum + Number(trip.capacity || 0),
    0
  );

  return (
    <div className="company-inner-page">

      <main className="company-management-main">
        <header className="company-management-topbar">
          <button
            className="company-mobile-menu"
            
            aria-label="Open navigation"
          >
            <Menu size={21} />
          </button>

          <div>
            <p className="company-eyebrow">COMPANY MANAGER</p>
            <h1>{company?.name || user?.company_name || 'My Company'}</h1>
          </div>

          <div className="company-top-actions">
            <button className="company-refresh" onClick={load}>
              <Activity size={17} />
              Refresh
            </button>

            <button className="company-logout" onClick={logout}>
              Logout
            </button>
          </div>
        </header>

        <section className="company-content">
          {error && <div className="company-error">{error}</div>}

          {loading ? (
            <div className="company-loading">
              Loading your company workspace...
            </div>
          ) : (
            <>
              <section className="company-welcome">
                <div>
                  <p className="company-eyebrow">WELCOME BACK</p>
                  <h2>{company?.name || user?.company_name || 'Your company'}</h2>
                  <p>
                    Manage your company's routes, departures, drivers,
                    operators, bookings and revenue from one workspace.
                  </p>
                </div>

                <div className="company-live-pill">
                  <span />
                  Operations live
                </div>
              </section>

              <section className="company-stats-grid">
                <Stat
                  icon={WalletCards}
                  label="Settled revenue"
                  value={money(analytics?.total_revenue_settled)}
                  detail="Your company"
                />

                <Stat
                  icon={ClipboardList}
                  label="Active bookings"
                  value={activeBookings}
                  detail={`${bookings.length} total bookings`}
                />

                <Stat
                  icon={CalendarDays}
                  label="Active trips"
                  value={activeTrips}
                  detail={`${trips.length} total trips`}
                />

                <Stat
                  icon={Users}
                  label="Drivers"
                  value={drivers.length}
                  detail="Your company drivers"
                />

                <Stat
                  icon={Route}
                  label="Routes"
                  value={routes.length}
                  detail="Your company routes"
                />
              </section>

              <section className="company-action-grid">
                <NavLink to="/company-manager/trips" className="company-action-card">
                  <CalendarDays size={22} />
                  <div>
                    <strong>Create / manage trips</strong>
                    <span>Schedule departures and manage status.</span>
                  </div>
                  <ArrowUpRight size={18} />
                </NavLink>

                <NavLink to="/company-manager/drivers" className="company-action-card">
                  <Users size={22} />
                  <div>
                    <strong>Manage drivers</strong>
                    <span>Add drivers and maintain vehicle details.</span>
                  </div>
                  <ArrowUpRight size={18} />
                </NavLink>

                <NavLink to="/company-manager/routes" className="company-action-card">
                  <Route size={22} />
                  <div>
                    <strong>Manage routes</strong>
                    <span>Create routes and update company pricing.</span>
                  </div>
                  <ArrowUpRight size={18} />
                </NavLink>

                <NavLink to="/company-manager/operators" className="company-action-card">
                  <ShieldCheck size={22} />
                  <div>
                    <strong>Manage operators</strong>
                    <span>Create and manage your company staff.</span>
                  </div>
                  <ArrowUpRight size={18} />
                </NavLink>
              </section>

              <section className="company-dashboard-grid">
                <div className="company-panel">
                  <div className="company-panel-header">
                    <div>
                      <span className="company-panel-kicker">
                        UPCOMING
                      </span>
                      <h3>Departures</h3>
                    </div>

                    <NavLink to="/company-manager/trips">
                      View all
                    </NavLink>
                  </div>

                  <div className="company-trip-list">
                    {trips.length === 0 ? (
                      <div className="company-empty">
                        No departures yet.
                      </div>
                    ) : (
                      trips.slice(0, 6).map((trip) => (
                        <div className="company-trip-row" key={trip.id}>
                          <div className="company-trip-icon">
                            <Bus size={17} />
                          </div>

                          <div className="company-trip-info">
                            <strong>
                              {trip.route_details?.name || 'Route'}
                            </strong>

                            <span>
                              {formatDate(trip.departure_at)}
                              {' · '}
                              {trip.driver_name || 'No driver'}
                            </span>
                          </div>

                          <span className={`company-status ${trip.status}`}>
                            {trip.status}
                          </span>
                        </div>
                      ))
                    )}
                  </div>
                </div>

                <div className="company-panel">
                  <div className="company-panel-header">
                    <div>
                      <span className="company-panel-kicker">
                        CAPACITY
                      </span>
                      <h3>Network capacity</h3>
                    </div>

                    <NavLink to="/company-manager/capacity">
                      Manage
                    </NavLink>
                  </div>

                  <div className="company-capacity-number">
                    {totalCapacity}
                    <span> seats scheduled</span>
                  </div>

                  <div className="company-capacity-bar">
                    <div
                      style={{
                        width: `${Math.min(
                          100,
                          totalCapacity ? (bookings.length / totalCapacity) * 100 : 0
                        )}%`,
                      }}
                    />
                  </div>

                  <div className="company-capacity-meta">
                    <span>{bookings.length} bookings</span>
                    <span>{totalCapacity} capacity</span>
                  </div>

                  <div className="company-revenue-box">
                    <div>
                      <span>Settled revenue</span>
                      <strong>{money(analytics?.total_revenue_settled)}</strong>
                    </div>

                    <WalletCards size={25} />
                  </div>
                </div>
              </section>

              <section className="company-panel">
                <div className="company-panel-header">
                  <div>
                    <span className="company-panel-kicker">
                      RECENT ACTIVITY
                    </span>
                    <h3>Bookings</h3>
                  </div>

                  <NavLink to="/company-manager/bookings">
                    View all
                  </NavLink>
                </div>

                <div className="company-booking-list">
                  {bookings.length === 0 ? (
                    <div className="company-empty">
                      No bookings yet.
                    </div>
                  ) : (
                    bookings.slice(0, 6).map((booking) => (
                      <div
                        className="company-booking-row"
                        key={booking.booking_id}
                      >
                        <div>
                          <strong>{booking.booking_number}</strong>
                          <span>
                            {booking.user || 'Passenger'} ·{' '}
                            {booking.route_name || 'Route'}
                          </span>
                        </div>

                        <div>
                          <strong>
                            {money(
                              booking.total_amount ||
                                booking.amount ||
                                booking.fare
                            )}
                          </strong>
                          <span>
                            {booking.payment_status ||
                              booking.status ||
                              'Pending'}
                          </span>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </section>
            </>
          )}
        </section>
      </main>
    </div>
  );
}