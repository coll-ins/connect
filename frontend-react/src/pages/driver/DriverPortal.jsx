import { useEffect, useState } from "react";
import {
  Activity,
  Bus,
  CalendarDays,
  CheckCircle2,
  LayoutDashboard,
  LogOut,
  MapPin,
  Menu,
  User,
  Users,
} from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { Link, useLocation } from "react-router-dom";
import { apiRequest } from "../../api";
import "./DriverPortal.css";

const nav = [
  ["/driver", "Overview", LayoutDashboard],
  ["/driver/trips", "Today's Trips", CalendarDays],
  ["/driver/passengers", "Passengers", Users],
  ["/driver/location", "Live Location", MapPin],
  ["/driver/boarding", "Boarding", CheckCircle2],
  ["/driver/profile", "Profile", User],
];

function pageTitle(path) {
  if (path.startsWith("/driver/trips")) return "Today's Trips";
  if (path.startsWith("/driver/passengers")) return "Passengers";
  if (path.startsWith("/driver/location")) return "Live Location";
  if (path.startsWith("/driver/boarding")) return "Boarding";
  if (path.startsWith("/driver/profile")) return "Profile";
  return "Overview";
}

function getDriverName(driver) {
  return (
    driver?.user?.username ||
    driver?.username ||
    "Driver"
  );
}

function getCompanyName(driver) {
  return (
    driver?.company?.name ||
    driver?.company_name ||
    "Company"
  );
}

export default function DriverPortal() {
  const location = useLocation();
  const { logout } = useAuth();

  const [driver, setDriver] = useState(null);
  const [bookings, setBookings] = useState([]);
  const [error, setError] = useState("");
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    let mounted = true;

    async function load() {
      try {
        const d = await apiRequest("/drivers/me/");

        if (!mounted) return;

        setDriver(d);

        const driverId =
          d?.id ||
          d?.driver?.id ||
          d?.profile?.id;

        if (!driverId) return;

        const result = await apiRequest(
          `/bookings/driver/${driverId}/`
        );

        if (!mounted) return;

        setBookings(
          Array.isArray(result)
            ? result
            : result?.results ||
              result?.bookings ||
              []
        );
      } catch (err) {
        if (mounted) {
          setError(
            err?.message ||
            "Driver data could not be loaded."
          );
        }
      }
    }

    load();

    return () => {
      mounted = false;
    };
  }, []);

  const active =
    nav.find(([path]) =>
      path === "/driver"
        ? location.pathname === "/driver"
        : location.pathname.startsWith(path)
    )?.[0] || "/driver";

  const title = pageTitle(location.pathname);
  const driverName = getDriverName(driver);
  const companyName = getCompanyName(driver);
  const initial = driverName.charAt(0).toUpperCase();

  const selectPage = () => {
    setMobileOpen(false);
  };

  return (
    <div className="driver-app">

      {/* SIDEBAR */}
      <aside
        className={`driver-sidebar ${
          mobileOpen ? "driver-sidebar-open" : ""
        }`}
      >
        <div className="driver-brand">
          <div className="driver-brand-mark">
            <Bus size={21} />
          </div>

          <div>
            <strong>CONNECT</strong>
            <span>Driver Operations</span>
          </div>
        </div>

        <div className="driver-company-card">
          <span>COMPANY</span>
          <strong>{companyName}</strong>
          <small>Driver workspace</small>
        </div>

        <nav
          className="driver-nav"
          aria-label="Driver navigation"
        >
          <span className="driver-nav-label">
            WORKSPACE
          </span>

          {nav.map(([path, label, Icon]) => {
            const selected = active === path;

            return (
              <Link
                key={path}
                to={path}
                onClick={selectPage}
                className={`driver-nav-item ${
                  selected
                    ? "driver-nav-item-active"
                    : ""
                }`}
              >
                <span className="driver-nav-icon">
                  <Icon size={18} />
                </span>

                <span>{label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="driver-sidebar-bottom">

          <div className="driver-user-card">
            <div className="driver-user-avatar">
              {initial}
            </div>

            <div>
              <strong>{driverName}</strong>
              <span>Driver</span>
            </div>
          </div>

          <button
            type="button"
            className="driver-logout"
            onClick={logout}
          >
            <LogOut size={17} />
            Sign out
          </button>

        </div>
      </aside>

      {/* MOBILE BACKDROP */}
      {mobileOpen && (
        <button
          type="button"
          className="driver-mobile-backdrop"
          onClick={() => setMobileOpen(false)}
          aria-label="Close navigation"
        />
      )}

      {/* MAIN */}
      <main className="driver-main">

        {/* TOPBAR */}
        <header className="driver-topbar">

          <button
            type="button"
            className="driver-menu-button"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
          >
            <Menu size={20} />
          </button>

          <div className="driver-topbar-title">
            <span>DRIVER OPERATIONS</span>
            <strong>{title}</strong>
          </div>

          <div className="driver-topbar-right">

            <div className="driver-live-indicator">
              <span />
              Live
            </div>

            <div className="driver-topbar-user">
              <div className="driver-topbar-avatar">
                {initial}
              </div>

              <div>
                <strong>{driverName}</strong>
                <span>Driver</span>
              </div>
            </div>

          </div>
        </header>

        {/* CONTENT */}
        <div className="driver-content">

          <div className="driver-page-heading">
            <div>
              <span className="driver-eyebrow">
                DRIVER OPERATIONS
              </span>

              <h1>{title}</h1>

              <p>
                Manage your trips, passengers and
                boarding operations.
              </p>
            </div>
          </div>

          {error && (
            <div className="driver-error">
              <strong>Data connection:</strong>{" "}
              {error}
            </div>
          )}

          {/* OVERVIEW */}
          {active === "/driver" && (
            <>
              <div className="driver-stat-grid">

                <div className="driver-stat-card">
                  <div className="driver-stat-icon">
                    <CalendarDays size={19} />
                  </div>

                  <div className="driver-stat-copy">
                    <span>Assigned Trips</span>
                    <strong>{bookings.length}</strong>
                    <small>Current assignments</small>
                  </div>
                </div>

                <div className="driver-stat-card">
                  <div className="driver-stat-icon">
                    <Users size={19} />
                  </div>

                  <div className="driver-stat-copy">
                    <span>Passengers</span>
                    <strong>
                      {bookings.reduce(
                        (n, b) =>
                          n + Number(b?.seats || 1),
                        0
                      )}
                    </strong>
                    <small>Booked seats</small>
                  </div>
                </div>

                <div className="driver-stat-card">
                  <div className="driver-stat-icon">
                    <Activity size={19} />
                  </div>

                  <div className="driver-stat-copy">
                    <span>Driver Status</span>
                    <strong className="driver-status-active">
                      Active
                    </strong>
                    <small>Operations status</small>
                  </div>
                </div>

              </div>

              <section className="driver-panel">

                <div className="driver-panel-heading">
                  <div>
                    <span className="driver-eyebrow">
                      DRIVER PROFILE
                    </span>

                    <h2>Driver Overview</h2>
                  </div>
                </div>

                <div className="driver-detail-grid">

                  <div className="driver-detail">
                    <span>Name</span>
                    <strong>{driverName}</strong>
                  </div>

                  <div className="driver-detail">
                    <span>Company</span>
                    <strong>{companyName}</strong>
                  </div>

                </div>

              </section>
            </>
          )}

          {/* TRIPS */}
          {active === "/driver/trips" && (
            <section className="driver-panel">

              <div className="driver-panel-heading">
                <div>
                  <span className="driver-eyebrow">
                    DAILY OPERATIONS
                  </span>

                  <h2>Today's Trips</h2>
                </div>
              </div>

              {bookings.length === 0 ? (
                <div className="driver-empty">
                  No assigned trips found.
                </div>
              ) : (
                <div className="driver-list">

                  {bookings.map((b) => (
                    <article
                      className="driver-list-item"
                      key={b.booking_id}
                    >
                      <div className="driver-list-icon">
                        <Bus size={18} />
                      </div>

                      <div className="driver-list-content">
                        <strong>
                          {b.route ||
                            `Booking #${b.booking_id}`}
                        </strong>

                        <span>
                          Pickup:{" "}
                          {b.pickup_location ||
                            b.pickup_stage_name ||
                            "Not specified"}
                        </span>
                      </div>
                    </article>
                  ))}

                </div>
              )}

            </section>
          )}

          {/* PASSENGERS */}
          {active === "/driver/passengers" && (
            <section className="driver-panel">

              <div className="driver-panel-heading">
                <div>
                  <span className="driver-eyebrow">
                    PASSENGER MANIFEST
                  </span>

                  <h2>Passengers</h2>
                </div>
              </div>

              {bookings.length === 0 ? (
                <div className="driver-empty">
                  No passengers found.
                </div>
              ) : (
                <div className="driver-list">

                  {bookings.map((b) => (
                    <article
                      className="driver-list-item"
                      key={b.booking_id}
                    >
                      <div className="driver-list-icon">
                        <Users size={18} />
                      </div>

                      <div className="driver-list-content">
                        <strong>
                          {b.passenger ||
                            "Passenger"}
                        </strong>

                        <span>
                          Seats: {b.seats || 1}
                        </span>
                      </div>
                    </article>
                  ))}

                </div>
              )}

            </section>
          )}

          {/* LOCATION */}
          {active === "/driver/location" && (
            <section className="driver-panel">

              <div className="driver-panel-heading">
                <div>
                  <span className="driver-eyebrow">
                    VEHICLE TRACKING
                  </span>

                  <h2>Live Location</h2>
                </div>
              </div>

              <div className="driver-empty">
                Live driver location is available from
                this section.
              </div>

            </section>
          )}

          {/* BOARDING */}
          {active === "/driver/boarding" && (
            <section className="driver-panel">

              <div className="driver-panel-heading">
                <div>
                  <span className="driver-eyebrow">
                    TRIP OPERATIONS
                  </span>

                  <h2>Boarding Verification</h2>
                </div>
              </div>

              <p className="driver-panel-description">
                Select a passenger booking to verify
                boarding.
              </p>

              {bookings.length === 0 ? (
                <div className="driver-empty">
                  No passenger bookings available.
                </div>
              ) : (
                <div className="driver-list">

                  {bookings.map((b) => (
                    <article
                      className="driver-list-item"
                      key={b.booking_id}
                    >
                      <div className="driver-list-icon">
                        <CheckCircle2 size={18} />
                      </div>

                      <div className="driver-list-content">
                        <strong>
                          {b.passenger ||
                            `Booking #${b.booking_id}`}
                        </strong>

                        <span>
                          Booking #{b.booking_id}
                        </span>
                      </div>
                    </article>
                  ))}

                </div>
              )}

            </section>
          )}

          {/* PROFILE */}
          {active === "/driver/profile" && (
            <section className="driver-panel">

              <div className="driver-panel-heading">
                <div>
                  <span className="driver-eyebrow">
                    ACCOUNT
                  </span>

                  <h2>Driver Profile</h2>
                </div>
              </div>

              <div className="driver-detail-grid">

                <div className="driver-detail">
                  <span>Username</span>
                  <strong>{driverName}</strong>
                </div>

                <div className="driver-detail">
                  <span>Phone</span>
                  <strong>
                    {driver?.phone ||
                      driver?.user?.phone ||
                      "—"}
                  </strong>
                </div>

                <div className="driver-detail">
                  <span>Company</span>
                  <strong>{companyName}</strong>
                </div>

              </div>

            </section>
          )}

        </div>
      </main>
    </div>
  );
}
