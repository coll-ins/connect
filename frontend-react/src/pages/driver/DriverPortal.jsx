import { useEffect, useState } from "react";
import {
  Activity,
  Banknote,
  Bus,
  CalendarDays,
  CheckCircle2,
  LayoutDashboard,
  LogOut,
  MapPin,
  Menu,
  Package,
  User,
  Users,
} from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { Link, useLocation } from "react-router-dom";
import { apiRequest } from "../../api";
import Modal from "../../components/ui/Modal";
import DriverJobs from "./DriverJobs";
import "./DriverPortal.css";

const SERVICE_TIME_ZONE = "Africa/Nairobi";

const nav = [
  ["/driver", "Overview", LayoutDashboard],
  ["/driver/trips", "My timetable", CalendarDays],
  ["/driver/passengers", "Passengers", Users],
  ["/driver/location", "Live location", MapPin],
  ["/driver/boarding", "Pickup manifest", CheckCircle2],
  ["/driver/jobs", "Parcels & hires", Package],
  ["/driver/profile", "Profile", User],
];

const PAGE_DESCRIPTIONS = {
  Overview: "Your next departure and today's numbers at a glance.",
  "My timetable": "Trips assigned to you for the next seven days, in Nairobi time.",
  Passengers: "Everyone booked on your trips and where they board.",
  "Live location": "Share your position so passengers can see the bus coming.",
  "Pickup manifest": "Passengers still to collect on the current trip, in stage order.",
  "Parcels & hires": "Parcels to carry and whole-bus hires assigned to you.",
  Profile: "Your account and the company you drive for.",
};

function pageTitle(path) {
  if (path.startsWith("/driver/trips")) return "My timetable";
  if (path.startsWith("/driver/passengers")) return "Passengers";
  if (path.startsWith("/driver/location")) return "Live location";
  if (path.startsWith("/driver/boarding")) return "Pickup manifest";
  if (path.startsWith("/driver/jobs")) return "Parcels & hires";
  if (path.startsWith("/driver/profile")) return "Profile";
  return "Overview";
}

function getServiceDateKey(value) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: SERVICE_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(value));
}

function formatServiceTime(value) {
  return new Intl.DateTimeFormat("en-KE", {
    timeZone: SERVICE_TIME_ZONE,
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatServiceDate(dateKey) {
  return new Intl.DateTimeFormat("en-KE", {
    timeZone: SERVICE_TIME_ZONE,
    weekday: "long",
    day: "numeric",
    month: "long",
  }).format(new Date(`${dateKey}T12:00:00+03:00`));
}

function getTripStatusLabel(status) {
  return {
    scheduled: "Scheduled",
    boarding: "Boarding",
    departed: "Departed",
    completed: "Completed",
    cancelled: "Cancelled",
  }[status] || "Status unavailable";
}

function TimetableTrip({ trip }) {
  return (
    <article className="driver-timetable-trip">
      <strong className="driver-timetable-time">
        {formatServiceTime(trip.departure_at)}
      </strong>
      <div className="driver-timetable-details">
        <strong>{trip.route_name}</strong>
        <span>
          Bus {trip.bus_number} · {trip.start_point} to {trip.end_point} · {trip.capacity} seats
        </span>
      </div>
      <span className={`driver-timetable-status driver-timetable-status-${trip.status}`}>
        {getTripStatusLabel(trip.status)}
      </span>
    </article>
  );
}

function getDriverName(driver) {


  return (
    driver?.user?.username ||
    driver?.username ||
    driver?.name ||
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

const canConfirmCash = (b) =>
  String(b?.payment_method || "").toLowerCase() === "cash" &&
  String(b?.payment_status || "").toLowerCase() === "pending" &&
  ["pending", "confirmed"].includes(String(b?.status || "").toLowerCase());

export default function DriverPortal() {

  const confirmCash = async (booking) => {
    const passengerName =
      booking.passenger?.name ||
      booking.passenger_name ||
      booking.passenger ||
      `Booking #${booking.booking_id}`;

    if (
      !window.confirm(
        `Confirm you have received the cash from ${passengerName}?`
      )
    ) {
      return;
    }

    try {
      await apiRequest(
        `/bookings/payments/${booking.booking_id}/cash/confirm/`,
        { method: "POST" },
      );

      window.alert(`Cash from ${passengerName} confirmed.`);
      setReloadKey((k) => k + 1);
    } catch (err) {
      window.alert(err?.message || "Unable to confirm this cash payment.");
    }
  };

  const pinName = (b) =>
    b?.passenger?.name || b?.passenger_name ||
    (typeof b?.passenger === "string" ? b.passenger : "") ||
    `Booking #${b?.booking_id}`;

  const verifyPassenger = (booking) => {
    if (!booking?.booking_id) return;
    if (booking.status === "completed") {
      setFlash({ ok: true, text: `${pinName(booking)} is already boarded.` });
      return;
    }
    if (booking.status !== "confirmed") {
      setFlash({ ok: false, text: `Cannot board: booking is ${booking.status || "unknown"}.` });
      return;
    }
    if (String(booking.payment_status || "").toLowerCase() !== "confirmed") {
      setFlash({ ok: false, text: "Payment is not confirmed yet. Confirm cash first." });
      return;
    }
    setPin("");
    setPinError("");
    setFlash(null);
    setPinTarget(booking);
  };

  const submitPin = async () => {
    if (pinBusy || !pinTarget) return;
    const value = pin.trim();
    if (!/^\d{4,6}$/.test(value)) {
      setPinError("Enter the 4 to 6 digit PIN.");
      return;
    }
    setPinBusy(true);
    setPinError("");
    try {
      await apiRequest(`/bookings/${pinTarget.booking_id}/verify-boarding/`, {
        method: "POST",
        body: { boarding_pin: value },
      });
      const target = pinTarget;
      setPinTarget(null);
      setPin("");
      let confirmed = false;
      try {
        const fresh = await apiRequest(`/bookings/driver/${driver?.id}/`);
        const list = Array.isArray(fresh) ? fresh : fresh?.results || fresh?.bookings || [];
        setBookings(list);
        confirmed = list.some((b) => b.booking_id === target.booking_id && b.status === "completed");
      } catch {
        confirmed = false;
      }
      setFlash(confirmed
        ? { ok: true, text: `${pinName(target)} boarded. Confirmed by server.` }
        : { ok: false, text: `PIN accepted, but the server list does not show ${pinName(target)} as boarded yet. Refresh to check.` });
      setReloadKey((k) => k + 1);
    } catch (err) {
      setPinError(err?.message || "Unable to verify. Try again.");
    } finally {
      setPinBusy(false);
    }
  };


  const location = useLocation();
  const { logout } = useAuth();

  const [driver, setDriver] = useState(null);
  const [bookings, setBookings] = useState([]);
  const [timetable, setTimetable] = useState([]);
  const [timetableLoading, setTimetableLoading] = useState(true);
  const [timetableError, setTimetableError] = useState("");
  const [timetableKey, setTimetableKey] = useState(0);
  const [bookingsLoaded, setBookingsLoaded] = useState(false);
  const [error, setError] = useState("");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [pinTarget, setPinTarget] = useState(null);
  const [pin, setPin] = useState("");
  const [pinBusy, setPinBusy] = useState(false);
  const [pinError, setPinError] = useState("");
  const [flash, setFlash] = useState(null);

  useEffect(() => {
    let mounted = true;

    async function load() {
      try {
        const d = await apiRequest("/drivers/me/", { silent: true });

        if (!mounted) return;

        setDriver(d);

        const driverId =
          d?.id ||
          d?.driver?.id ||
          d?.profile?.id;

        if (!driverId) {
          setError("Your driver profile could not be found.");
          return;
        }

        const result = await apiRequest(
          `/bookings/driver/${driverId}/`,
          { silent: true },
        );

        if (!mounted) return;

        setError("");
        setBookingsLoaded(true);

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
  }, [reloadKey]);

  useEffect(() => {
    let mounted = true;
    const loadTimetable = async () => {
      try {
        const result = await apiRequest("/drivers/me/timetable/", { silent: true });
        if (!Array.isArray(result?.trips)) {
          throw new Error("The timetable response was invalid.");
        }
        if (mounted) {
          setTimetable(result.trips);
          setTimetableError("");
        }
      } catch (err) {
        if (mounted) {
          setTimetableError(err?.message || "Unable to load your timetable.");
        }
      } finally {
        if (mounted) setTimetableLoading(false);
      }
    };

    loadTimetable();
    const interval = window.setInterval(loadTimetable, 60_000);
    return () => {
      mounted = false;
      window.clearInterval(interval);
    };
  }, [timetableKey]);

  useEffect(() => {
    const t = window.setInterval(() => {
      if (document.visibilityState === "visible") setReloadKey((k) => k + 1);
    }, 8000);
    return () => window.clearInterval(t);
  }, []);

  const active =
    nav.find(([path]) =>
      path === "/driver"
        ? location.pathname === "/driver"
        : location.pathname.startsWith(path)
    )?.[0] || "/driver";
  const todayKey = getServiceDateKey(new Date());
  const todaysTrips = timetable.filter(
    (trip) => getServiceDateKey(trip.departure_at) === todayKey,
  );
  const timetableDays = [...new Set(
    timetable.map((trip) => getServiceDateKey(trip.departure_at)),
  )].sort();

  const title = pageTitle(location.pathname);
  const driverName = getDriverName(driver);
  const companyName = getCompanyName(driver);
  const initial = driverName.charAt(0).toUpperCase();

  const retryTimetable = () => {
    setTimetableLoading(true);
    setTimetableKey((k) => k + 1);
  };

  const selectPage = () => {
    setMobileOpen(false);
  };

  return (
    <div className="driver-app">
      {pinTarget && (
        <Modal
          labelledBy="board-pin-title"
          onClose={() => { if (!pinBusy) setPinTarget(null); }}
        >
          <form onSubmit={(e) => { e.preventDefault(); submitPin(); }}>
            <h3 id="board-pin-title" style={{margin:"0 0 4px"}}>Board passenger</h3>
            <p style={{margin:"0 0 12px"}}>{pinName(pinTarget)} · {pinTarget.booking_number || pinTarget.booking_id}</p>
            <label htmlFor="board-pin-input" style={{display:"block",margin:"0 0 6px",fontWeight:600}}>Boarding PIN</label>
            <input
              id="board-pin-input"
              className="input"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              value={pin}
              onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))}
              aria-invalid={pinError ? "true" : undefined}
              aria-describedby={pinError ? "board-pin-error" : undefined}
              style={{fontSize:24,letterSpacing:6,textAlign:"center",padding:12,borderRadius:10}}
            />
            {pinError && <p id="board-pin-error" role="alert" style={{color:"var(--danger-text)",margin:"10px 0 0",fontWeight:600}}>{pinError}</p>}
            <div style={{display:"flex",gap:8,marginTop:14}}>
              <button type="button" className="btn btn-secondary" disabled={pinBusy} onClick={() => setPinTarget(null)} style={{flex:1,padding:12,borderRadius:10}}>Cancel</button>
              <button type="submit" disabled={pinBusy || pin.length < 4} style={{flex:1,padding:12,borderRadius:10,border:"none",background:"var(--primary)",color:"var(--primary-ink)",fontWeight:700,opacity:(pinBusy || pin.length < 4) ? 0.6 : 1}}>{pinBusy ? "Verifying…" : "Verify"}</button>
            </div>
          </form>
        </Modal>
      )}

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
          <span>Company</span>
          <strong>{companyName}</strong>
          <small>Driver workspace</small>
        </div>

        <nav
          className="driver-nav"
          aria-label="Driver navigation"
        >
          <span className="driver-nav-label">
            Workspace
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
            <span>Driver operations</span>
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
        <div className="driver-content" style={{display:"flex",flexDirection:"column"}}>

          <div className="driver-page-heading">
            <div>
              <span className="driver-eyebrow">
                Driver operations
              </span>

              <h1>{title}</h1>

              <p>{PAGE_DESCRIPTIONS[title]}</p>
            </div>
          </div>

          {flash && (
            <div role={flash.ok ? "status" : "alert"} style={{margin:"0 0 12px",padding:"12px 14px",borderRadius:12,fontWeight:700,color:flash.ok ? "var(--primary-ink)" : "#fff",background:flash.ok ? "var(--success)" : "var(--danger-fill)",display:"flex",alignItems:"center",justifyContent:"space-between",gap:12}}>
              <span>{flash.text}</span>
              <button type="button" onClick={() => setFlash(null)} style={{minHeight:44,minWidth:44,padding:"0 12px",borderRadius:10,border:"1px solid currentColor",background:"transparent",color:"inherit",fontWeight:700}}>Dismiss</button>
            </div>
          )}

          {active === "/driver" && (
            <section className="driver-panel">
              <div className="driver-panel-heading">
                <div>
                  <span className="driver-eyebrow">Your schedule</span>
                  <h2>Today's timetable</h2>
                </div>
                <Link className="driver-timetable-link" to="/driver/trips">
                  View full timetable
                </Link>
              </div>
              {timetableLoading ? (
                <div className="driver-empty" role="status" aria-busy="true">Loading your timetable…</div>
              ) : timetableError ? (
                <div className="driver-error" role="alert">
                  {timetableError}{" "}
                  <button type="button" className="btn btn-secondary" onClick={retryTimetable}>Retry</button>
                </div>
              ) : todaysTrips.length ? (
                <div className="driver-timetable-list">
                  {todaysTrips.map((trip) => (
                    <TimetableTrip key={trip.id} trip={trip} />
                  ))}
                </div>
              ) : (
                <div className="driver-empty">
                  No trips are scheduled for you today.
                </div>
              )}
            </section>
          )}

          {active === "/driver" && (() => {
            const st = (b) => String(b.status || "").toLowerCase();
            const pay = (b) => String(b.payment_status || "").toLowerCase();
            const rows = bookings
              .filter((b) => !["cancelled", "no_show"].includes(st(b)))
              .sort((a, b) => (st(a) === "completed") - (st(b) === "completed"));
            const total = rows.filter((b) => ["confirmed", "completed"].includes(st(b))).length;
            const boarded = rows.filter((b) => st(b) === "completed").length;
            const pct = total ? Math.round((boarded / total) * 100) : 0;
            const btn = {minHeight:44,padding:"0 16px",borderRadius:10,border:"none",fontWeight:700,color:"#fff",cursor:"pointer"};
            return (
              <section style={{order:5,margin:"16px 0 0",padding:18,borderRadius:16,border:"1px solid rgba(255,255,255,.12)"}}>
                <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",gap:12,flexWrap:"wrap"}}>
                  <h2 style={{margin:0,fontSize:18}}>Boarding desk</h2>
                  <strong style={{padding:"6px 12px",borderRadius:999,background:"rgb(var(--success-rgb) / 0.14)",color:"var(--success-text)"}}>Boarded {boarded} / {total}</strong>
                </div>
                <div style={{height:6,borderRadius:3,background:"rgba(255,255,255,.1)",margin:"12px 0 4px"}}>
                  <div style={{height:6,borderRadius:3,width:`${pct}%`,background:"var(--success)",transition:"width .4s"}} />
                </div>
                {!bookingsLoaded && !error && <p role="status" style={{opacity:.7,margin:"12px 0 0"}}>Loading passengers…</p>}
                {bookingsLoaded && rows.length === 0 && <p style={{opacity:.7,margin:"12px 0 0"}}>No passengers assigned yet.</p>}
                {rows.map((b) => {
                  const boardedRow = st(b) === "completed";
                  const cashDue = canConfirmCash(b);
                  const canBoard = st(b) === "confirmed" && pay(b) === "confirmed";
                  const label = pay(b) === "failed" ? "Payment failed" : st(b) === "pending" ? "Awaiting payment" : st(b) || "unknown";
                  return (
                    <div key={b.booking_id} style={{display:"flex",flexWrap:"wrap",gap:10,alignItems:"center",justifyContent:"space-between",padding:"12px 0",borderTop:"1px solid rgba(255,255,255,.08)"}}>
                      <div style={{minWidth:0}}>
                        <strong>{pinName(b)}</strong>
                        <div style={{fontSize:13,opacity:.75}}>
                          {b.booking_number || `#${b.booking_id}`} · {b.payment_method || "-"} · pay {pay(b) || "-"} · {b.seats || 1} seat(s)
                        </div>
                      </div>
                      {boardedRow ? (
                        <span style={{...btn,background:"var(--success)",color:"var(--primary-ink)",cursor:"default",display:"inline-flex",alignItems:"center"}}>Boarded</span>
                      ) : cashDue ? (
                        <button type="button" style={{...btn,background:"var(--primary)",color:"var(--primary-ink)"}} onClick={() => confirmCash(b)}>Confirm cash received</button>
                      ) : canBoard ? (
                        <button type="button" style={{...btn,background:"var(--primary)",color:"var(--primary-ink)"}} onClick={() => verifyPassenger(b)}>Verify PIN</button>
                      ) : (
                        <span style={{...btn,background:"var(--surface-3)",color:"var(--text-2)",cursor:"default",display:"inline-flex",alignItems:"center"}}>{label}</span>
                      )}
                    </div>
                  );
                })}
              </section>
            );
          })()}

          {error && (
            <div className="driver-error" role="alert">
              <strong>Data connection:</strong>{" "}
              {error}{" "}
              <button type="button" className="btn btn-secondary" onClick={() => setReloadKey((k) => k + 1)}>Retry</button>
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
                      Driver profile
                    </span>

                    <h2>Your details</h2>
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

          {active === "/driver/jobs" && <DriverJobs />}

          {/* TRIPS */}
          {active === "/driver/trips" && (
            <section className="driver-panel">

              <div className="driver-panel-heading">
                <div>
                  <span className="driver-eyebrow">Assigned departures</span>
                  <h2>Next 7 days</h2>
                  <p className="driver-timetable-caption">
                    Your assigned trips for the next seven days, in Nairobi time.
                  </p>
                </div>
              </div>

              {timetableLoading ? (
                <div className="driver-empty" role="status" aria-busy="true">
                  Loading your timetable…
                </div>
              ) : timetableError ? (
                <div className="driver-error" role="alert">
                  {timetableError}{" "}
                  <button type="button" className="btn btn-secondary" onClick={retryTimetable}>Retry</button>
                </div>
              ) : timetableDays.length === 0 ? (
                <div className="driver-empty">
                  No trips are scheduled for you in the next seven days.
                </div>
              ) : (
                <div className="driver-timetable-days">
                  {timetableDays.map((dateKey) => {
                    const dayTrips = timetable.filter(
                      (trip) => getServiceDateKey(trip.departure_at) === dateKey,
                    );
                    return (
                      <section className="driver-timetable-day" key={dateKey}>
                        <h3>
                          {dateKey === todayKey
                            ? "Today"
                            : formatServiceDate(dateKey)}
                        </h3>
                        <div className="driver-timetable-list">
                          {dayTrips.map((trip) => (
                            <TimetableTrip key={trip.id} trip={trip} />
                          ))}
                        </div>
                      </section>
                    );
                  })}
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
                    Passenger manifest
                  </span>

                  <h2>Booked passengers</h2>
                </div>
              </div>

              {!bookingsLoaded ? (
                !error && <div className="driver-empty" role="status" aria-busy="true">Loading passengers…</div>
              ) : bookings.length === 0 ? (
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
                        <span>
                          Payment: {b.payment_method || "-"} · {b.payment_status || "-"}
                        </span>
                        {canConfirmCash(b) && (
                          <button
                            type="button"
                            onClick={() => confirmCash(b)}
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              gap: 6,
                              marginTop: 8,
                              padding: "7px 12px",
                              border: 0,
                              borderRadius: 8,
                              background: "var(--primary)",
                              color: "var(--primary-ink)",
                              fontSize: 12,
                              fontWeight: 800,
                              cursor: "pointer",
                            }}
                          >
                            <Banknote size={14} />
                            Confirm cash received
                          </button>
                        )}
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
                    Vehicle tracking
                  </span>

                  <h2>Live location</h2>
                </div>
              </div>

              <div className="driver-empty">
                Live driver location is available from
                this section.
              </div>

            </section>
          )}

          {/* PICKUP MANIFEST */}
          {active === "/driver/boarding" && (
            <section className="driver-panel">

              <div className="driver-panel-heading">
                <div>
                  <span className="driver-eyebrow">
                    Trip operations
                  </span>

                  <h2>Still to pick up</h2>
                </div>
              </div>

              <p className="driver-panel-description">
                Passengers assigned to this trip and where
                they need to be picked up.
              </p>

              {!bookingsLoaded ? (
                !error && <div className="driver-empty" role="status" aria-busy="true">Loading passengers…</div>
              ) : bookings.length === 0 ? (
                <div className="driver-empty">
                  No passenger pickups assigned.
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
                        <button
                          type="button"
                          onClick={() => verifyPassenger(b)}
                          disabled={b.status === "completed"}
                          style={{
                            border: "0",
                            padding: 0,
                            background: "transparent",
                            color: "inherit",
                            font: "inherit",
                            fontWeight: 700,
                            textAlign: "left",
                            cursor:
                              b.status === "completed"
                                ? "default"
                                : "pointer",
                            opacity:
                              b.status === "completed" ? 0.65 : 1,
                          }}
                        >
                          {b.passenger || "Passenger"}
                        </button>

                        <span>
                          Pickup:{" "}
                          {b.pickup_stage_name ||
                            b.pickup_location ||
                            "Not specified"}
                        </span>

                        <span>
                          Seats: {b.seats || 1}
                          {" • "}
                          {b.status === "completed"
                            ? "Verified"
                            : b.status || "pending"}
                        </span>
                        <span>
                          Payment: {b.payment_method || "-"} · {b.payment_status || "-"}
                        </span>
                        {canConfirmCash(b) && (
                          <button
                            type="button"
                            onClick={() => confirmCash(b)}
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              gap: 6,
                              marginTop: 8,
                              padding: "7px 12px",
                              border: 0,
                              borderRadius: 8,
                              background: "var(--primary)",
                              color: "var(--primary-ink)",
                              fontSize: 12,
                              fontWeight: 800,
                              cursor: "pointer",
                            }}
                          >
                            <Banknote size={14} />
                            Confirm cash received
                          </button>
                        )}
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
                    Account
                  </span>

                  <h2>Account details</h2>
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
