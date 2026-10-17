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
import DriverJobs from "./DriverJobs";
import "./DriverPortal.css";

const nav = [
  ["/driver", "Overview", LayoutDashboard],
  ["/driver/trips", "Today's Trips", CalendarDays],
  ["/driver/passengers", "Passengers", Users],
  ["/driver/location", "Live Location", MapPin],
  ["/driver/boarding", "Pickup Manifest", CheckCircle2],
  ["/driver/jobs", "Parcels & Hires", Package],
  ["/driver/profile", "Profile", User],
];

function pageTitle(path) {
  if (path.startsWith("/driver/trips")) return "Today's Trips";
  if (path.startsWith("/driver/passengers")) return "Passengers";
  if (path.startsWith("/driver/location")) return "Live Location";
  if (path.startsWith("/driver/boarding")) return "Pickup Manifest";
  if (path.startsWith("/driver/jobs")) return "Parcels & Hires";
  if (path.startsWith("/driver/profile")) return "Profile";
  return "Overview";
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
  }, [reloadKey]);

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

  const title = pageTitle(location.pathname);
  const driverName = getDriverName(driver);
  const companyName = getCompanyName(driver);
  const initial = driverName.charAt(0).toUpperCase();

  const selectPage = () => {
    setMobileOpen(false);
  };

  return (
    <div className="driver-app">
      {pinTarget && (
        <div style={{position:"fixed",inset:0,zIndex:10000,background:"rgba(0,0,0,.6)",display:"flex",alignItems:"center",justifyContent:"center",padding:16}}>
          <div style={{background:"#fff",color:"#111",borderRadius:16,padding:20,width:"100%",maxWidth:360}}>
            <h3 style={{margin:"0 0 4px"}}>Board passenger</h3>
            <p style={{margin:"0 0 12px"}}>{pinName(pinTarget)} · {pinTarget.booking_number || pinTarget.booking_id}</p>
            <input
              autoFocus
              inputMode="numeric"
              maxLength={6}
              value={pin}
              onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))}
              onKeyDown={(e) => e.key === "Enter" && submitPin()}
              placeholder="Boarding PIN"
              style={{width:"100%",fontSize:24,letterSpacing:6,textAlign:"center",padding:12,borderRadius:10,border:"1px solid #999",boxSizing:"border-box"}}
            />
            {pinError && <p style={{color:"#b42828",margin:"10px 0 0",fontWeight:600}}>{pinError}</p>}
            <div style={{display:"flex",gap:8,marginTop:14}}>
              <button type="button" disabled={pinBusy} onClick={() => setPinTarget(null)} style={{flex:1,padding:12,borderRadius:10,border:"1px solid #999",background:"#fff"}}>Cancel</button>
              <button type="button" disabled={pinBusy || pin.length < 4} onClick={submitPin} style={{flex:1,padding:12,borderRadius:10,border:"none",background:"#16a34a",color:"#fff",fontWeight:700,opacity:(pinBusy || pin.length < 4) ? 0.6 : 1}}>{pinBusy ? "Verifying..." : "Verify"}</button>
            </div>
          </div>
        </div>
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
        <div className="driver-content" style={{display:"flex",flexDirection:"column"}}>

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

          {flash && (
            <div onClick={() => setFlash(null)} style={{margin:"0 0 12px",padding:"12px 14px",borderRadius:12,fontWeight:700,cursor:"pointer",color:"#fff",background:flash.ok ? "#16a34a" : "#b42828"}}>
              {flash.text}
            </div>
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
                  <strong style={{padding:"6px 12px",borderRadius:999,background:"rgba(22,163,74,.18)"}}>Boarded {boarded} / {total}</strong>
                </div>
                <div style={{height:6,borderRadius:3,background:"rgba(255,255,255,.1)",margin:"12px 0 4px"}}>
                  <div style={{height:6,borderRadius:3,width:`${pct}%`,background:"#16a34a",transition:"width .4s"}} />
                </div>
                {rows.length === 0 && <p style={{opacity:.7,margin:"12px 0 0"}}>No passengers assigned yet.</p>}
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
                        <span style={{...btn,background:"#16a34a",cursor:"default",display:"inline-flex",alignItems:"center"}}>Boarded</span>
                      ) : cashDue ? (
                        <button type="button" style={{...btn,background:"#d97706"}} onClick={() => confirmCash(b)}>Confirm cash received</button>
                      ) : canBoard ? (
                        <button type="button" style={{...btn,background:"#2563eb"}} onClick={() => verifyPassenger(b)}>Verify PIN</button>
                      ) : (
                        <span style={{...btn,background:"#475569",cursor:"default",display:"inline-flex",alignItems:"center"}}>{label}</span>
                      )}
                    </div>
                  );
                })}
              </section>
            );
          })()}

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

          {active === "/driver/jobs" && <DriverJobs />}

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
                              background: "#5fd9b0",
                              color: "#03120d",
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

          {/* PICKUP MANIFEST */}
          {active === "/driver/boarding" && (
            <section className="driver-panel">

              <div className="driver-panel-heading">
                <div>
                  <span className="driver-eyebrow">
                    TRIP OPERATIONS
                  </span>

                  <h2>Pickup Manifest</h2>
                </div>
              </div>

              <p className="driver-panel-description">
                Passengers assigned to this trip and where
                they need to be picked up.
              </p>

              {bookings.length === 0 ? (
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
                              background: "#5fd9b0",
                              color: "#03120d",
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
