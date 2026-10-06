import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import {
  MapContainer,
  Marker,
  Popup,
  Polyline,
  TileLayer,
  useMap,
} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

const API = "";

async function api(path, options = {}) {
  const opts = {
    credentials: "include",
    ...options,
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  };

  if (["POST", "PUT", "PATCH", "DELETE"].includes((opts.method || "GET").toUpperCase())) {
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (match) {
      opts.headers["X-CSRFToken"] = decodeURIComponent(match[1]);
    }
  }

  const response = await fetch(`${API}${path}`, opts);

  let data = null;
  const text = await response.text();

  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }

  if (!response.ok) {
    const message =
      data?.detail ||
      data?.error ||
      data?.message ||
      (typeof data === "string" ? data : `Request failed (${response.status})`);

    throw new Error(message);
  }

  return data;
}

function first(value, fallback = "") {
  return value === undefined || value === null || value === "" ? fallback : value;
}

function getUserName(driver) {
  return (
    driver?.user?.full_name ||
    driver?.user?.name ||
    driver?.user?.username ||
    driver?.name ||
    driver?.user_name ||
    "Driver"
  );
}

function getCompanyName(driver) {
  return (
    driver?.company?.name ||
    driver?.company_name ||
    driver?.user?.company?.name ||
    "Assigned company"
  );
}

function getVehicle(driver) {
  return (
    driver?.vehicle_number ||
    driver?.vehicle?.registration_number ||
    driver?.vehicle?.plate_number ||
    driver?.plate_number ||
    "Vehicle"
  );
}

function bookingPassenger(booking) {
  return (
    booking?.passenger_name ||
    booking?.user_name ||
    booking?.passenger?.name ||
    booking?.passenger?.full_name ||
    booking?.user?.name ||
    booking?.user?.username ||
    "Passenger"
  );
}

function bookingPhone(booking) {
  return (
    booking?.passenger_phone ||
    booking?.phone ||
    booking?.passenger?.phone ||
    booking?.user?.phone ||
    ""
  );
}

function bookingRoute(booking) {
  return (
    booking?.route_name ||
    booking?.route?.name ||
    `${first(booking?.start_point, "Origin")} → ${first(booking?.end_point, "Destination")}`
  );
}

function bookingStage(booking) {
  return (
    booking?.pickup_stage_name ||
    booking?.pickup_stage?.name ||
    booking?.pickup_location ||
    "Pickup stage not specified"
  );
}

function bookingStatus(booking) {
  return String(booking?.status || "confirmed").replaceAll("_", " ");
}

function bookingSeats(booking) {
  return Number(booking?.seats || booking?.number_of_seats || 1);
}

function bookingId(booking) {
  return booking?.id || booking?.booking_id;
}

function tripId(booking) {
  return booking?.trip_id || booking?.trip?.id;
}

function routeId(booking) {
  return booking?.route_id || booking?.trip?.route_id || booking?.route?.id;
}

function formatDate(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleDateString([], {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function formatTime(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function stageIcon(stage) {
  const order = Number(stage?.order || 0);

  return L.divIcon({
    className: "driver-stage-marker",
    html: `
      <div class="driver-stage-pin">
        <span>${order}</span>
      </div>
    `,
    iconSize: [42, 48],
    iconAnchor: [21, 44],
    popupAnchor: [0, -42],
  });
}

function busIcon() {
  return L.divIcon({
    className: "driver-bus-marker",
    html: `<div class="driver-bus-pin">🚌</div>`,
    iconSize: [50, 50],
    iconAnchor: [25, 25],
  });
}

function passengerIcon() {
  return L.divIcon({
    className: "driver-passenger-marker",
    html: `<div class="driver-passenger-pin">●</div>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });
}

function MapFit({ positions }) {
  const map = useMap();
  const previous = useRef("");

  useEffect(() => {
    if (!positions || positions.length < 2) return;

    const key = positions
      .map(([lat, lng]) => `${Number(lat).toFixed(5)},${Number(lng).toFixed(5)}`)
      .join("|");

    if (key === previous.current) return;

    const bounds = L.latLngBounds(positions);

    if (bounds.isValid()) {
      map.fitBounds(bounds, {
        padding: [60, 60],
        maxZoom: 14,
      });
      previous.current = key;
    }
  }, [map, positions]);

  return null;
}

function useDriverData() {
  const [driver, setDriver] = useState(null);
  const [bookings, setBookings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const me = await api("/drivers/me/");
      const profile = me?.driver || me?.profile || me;
      setDriver(profile);

      const id = profile?.id || profile?.driver_id;

      if (!id) {
        setBookings([]);
        return;
      }

      const result = await api(`/bookings/driver/${id}/`);
      const rows = Array.isArray(result)
        ? result
        : result?.results || result?.bookings || result?.data || [];

      setBookings(rows);
    } catch (err) {
      setError(err.message || "Unable to load driver information.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return {
    driver,
    bookings,
    loading,
    error,
    reload: load,
  };
}

function DriverShell({ driver, children, active, onRefresh }) {
  const navigate = useNavigate();

  const links = [
    ["overview", "/driver", "Overview", "⌂"],
    ["trips", "/driver/trips", "Today's Trips", "▣"],
    ["passengers", "/driver/passengers", "Passengers", "♟"],
    ["location", "/driver/location", "Live Location", "⌖"],
    ["boarding", "/driver/boarding", "Boarding", "✓"],
    ["profile", "/driver/profile", "Profile", "●"],
  ];

  const logout = async () => {
    try {
      await api("/users/logout/", { method: "POST" });
    } catch {
      // Local session is cleared even when the backend logout endpoint is unavailable.
    }

    localStorage.removeItem("user_session");
    localStorage.removeItem("access_token");
    sessionStorage.clear();
    navigate("/login", { replace: true });
  };

  return (
    <div className="driver-portal">
      <aside className="driver-sidebar">
        <div className="driver-brand">
          <div className="driver-brand-mark">C</div>
          <div>
            <strong>CONNECT</strong>
            <span>Driver Portal</span>
          </div>
        </div>

        <div className="driver-user-card">
          <div className="driver-avatar">
            {getUserName(driver).charAt(0).toUpperCase()}
          </div>
          <div>
            <strong>{getUserName(driver)}</strong>
            <span>{getCompanyName(driver)}</span>
          </div>
        </div>

        <nav className="driver-nav">
          {links.map(([key, path, label, icon]) => (
            <button
              key={key}
              type="button"
              className={`driver-nav-item ${active === key ? "active" : ""}`}
              onClick={() => navigate(path)}
            >
              <span className="driver-nav-icon">{icon}</span>
              <span>{label}</span>
            </button>
          ))}
        </nav>

        <div className="driver-sidebar-bottom">
          <button type="button" className="driver-nav-item" onClick={onRefresh}>
            <span className="driver-nav-icon">↻</span>
            <span>Refresh</span>
          </button>

          <button type="button" className="driver-nav-item driver-logout" onClick={logout}>
            <span className="driver-nav-icon">↪</span>
            <span>Sign out</span>
          </button>
        </div>
      </aside>

      <main className="driver-main">
        {children}
      </main>
    </div>
  );
}

function PageHeader({ eyebrow, title, description, action }) {
  return (
    <header className="driver-page-header">
      <div>
        {eyebrow && <div className="driver-eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {action}
    </header>
  );
}

function StatCard({ label, value, detail }) {
  return (
    <div className="driver-stat-card">
      <span>{label}</span>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
    </div>
  );
}

function BookingCard({ booking, onBoard }) {
  return (
    <article className="driver-booking-card">
      <div className="driver-booking-top">
        <div>
          <span className="driver-card-label">Passenger</span>
          <h3>{bookingPassenger(booking)}</h3>
        </div>

        <span className={`driver-status driver-status-${String(booking?.status || "confirmed").toLowerCase()}`}>
          {bookingStatus(booking)}
        </span>
      </div>

      <div className="driver-booking-grid">
        <div>
          <span>Route</span>
          <strong>{bookingRoute(booking)}</strong>
        </div>

        <div>
          <span>Pickup</span>
          <strong>{bookingStage(booking)}</strong>
        </div>

        <div>
          <span>Seats</span>
          <strong>{bookingSeats(booking)}</strong>
        </div>

        <div>
          <span>Phone</span>
          <strong>{bookingPhone(booking) || "—"}</strong>
        </div>
      </div>

      <div className="driver-booking-actions">
        <span>Booking #{bookingId(booking) || "—"}</span>

        {String(booking?.status || "").toLowerCase() === "confirmed" && (
          <button type="button" className="driver-primary-button" onClick={() => onBoard(booking)}>
            Verify boarding
          </button>
        )}
      </div>
    </article>
  );
}

function OverviewPage({ driver, bookings, navigate, onBoard }) {
  const today = new Date().toDateString();

  const todayBookings = bookings.filter((b) => {
    const departure =
      b?.departure_at ||
      b?.trip_departure_at ||
      b?.trip?.departure_at;

    if (!departure) return true;
    return new Date(departure).toDateString() === today;
  });

  const boarded = bookings.filter((b) =>
    ["boarded", "completed"].includes(String(b?.status || "").toLowerCase())
  ).length;

  const pending = bookings.filter((b) =>
    ["confirmed", "pending"].includes(String(b?.status || "").toLowerCase())
  ).length;

  return (
    <div className="driver-content">
      <PageHeader
        eyebrow="DRIVER DASHBOARD"
        title={`Good day, ${getUserName(driver)}`}
        description={`${getCompanyName(driver)} · ${getVehicle(driver)}`}
        action={
          <button
            type="button"
            className="driver-primary-button"
            onClick={() => navigate("/driver/location")}
          >
            Open live location
          </button>
        }
      />

      <section className="driver-stat-grid">
        <StatCard label="Today's bookings" value={todayBookings.length} detail="Assigned to you" />
        <StatCard label="Passengers" value={bookings.reduce((n, b) => n + bookingSeats(b), 0)} detail="Across assignments" />
        <StatCard label="Boarded" value={boarded} detail="Verified passengers" />
        <StatCard label="Awaiting boarding" value={pending} detail="Need verification" />
      </section>

      <section className="driver-overview-grid">
        <div className="driver-panel">
          <div className="driver-panel-heading">
            <div>
              <span className="driver-eyebrow">ASSIGNMENTS</span>
              <h2>Today's passengers</h2>
            </div>
            <button type="button" className="driver-link-button" onClick={() => navigate("/driver/passengers")}>
              View all
            </button>
          </div>

          {todayBookings.length ? (
            <div className="driver-list">
              {todayBookings.slice(0, 5).map((booking) => (
                <BookingCard key={bookingId(booking)} booking={booking} onBoard={onBoard} />
              ))}
            </div>
          ) : (
            <div className="driver-empty">
              <div className="driver-empty-icon">✓</div>
              <h3>No passenger assignments yet</h3>
              <p>Your assigned bookings will appear here.</p>
            </div>
          )}
        </div>

        <div className="driver-panel driver-quick-panel">
          <span className="driver-eyebrow">QUICK ACTIONS</span>
          <h2>Driver tools</h2>

          <button type="button" onClick={() => navigate("/driver/trips")}>
            <span>▣</span>
            <div>
              <strong>Today's Trips</strong>
              <small>View assigned departures</small>
            </div>
          </button>

          <button type="button" onClick={() => navigate("/driver/passengers")}>
            <span>♟</span>
            <div>
              <strong>Passenger Manifest</strong>
              <small>Review pickup stages</small>
            </div>
          </button>

          <button type="button" onClick={() => navigate("/driver/boarding")}>
            <span>✓</span>
            <div>
              <strong>Verify Boarding</strong>
              <small>Enter passenger PIN</small>
            </div>
          </button>

          <button type="button" onClick={() => navigate("/driver/location")}>
            <span>⌖</span>
            <div>
              <strong>Live Location</strong>
              <small>Share your current position</small>
            </div>
          </button>
        </div>
      </section>
    </div>
  );
}

function TripsPage({ bookings, navigate }) {
  const trips = useMemo(() => {
    const map = new Map();

    bookings.forEach((booking) => {
      const id = tripId(booking) || `booking-${bookingId(booking)}`;

      if (!map.has(id)) {
        map.set(id, {
          id,
          route: bookingRoute(booking),
          departure:
            booking?.departure_at ||
            booking?.trip_departure_at ||
            booking?.trip?.departure_at,
          status: booking?.trip_status || booking?.trip?.status || "scheduled",
          bookings: [],
        });
      }

      map.get(id).bookings.push(booking);
    });

    return [...map.values()].sort((a, b) => {
      return new Date(a.departure || 0) - new Date(b.departure || 0);
    });
  }, [bookings]);

  return (
    <div className="driver-content">
      <PageHeader
        eyebrow="SCHEDULE"
        title="Today's Trips"
        description="Your assigned departures and passenger load."
      />

      {trips.length ? (
        <div className="driver-trip-list">
          {trips.map((trip) => (
            <article className="driver-trip-card" key={trip.id}>
              <div className="driver-trip-main">
                <span className="driver-eyebrow">{String(trip.status).toUpperCase()}</span>
                <h2>{trip.route}</h2>

                <div className="driver-trip-meta">
                  <span>📅 {formatDate(trip.departure)}</span>
                  <span>◷ {formatTime(trip.departure)}</span>
                  <span>♟ {trip.bookings.length} bookings</span>
                  <span>💺 {trip.bookings.reduce((n, b) => n + bookingSeats(b), 0)} seats</span>
                </div>
              </div>

              <button
                type="button"
                className="driver-primary-button"
                onClick={() => navigate("/driver/passengers")}
              >
                View passengers
              </button>
            </article>
          ))}
        </div>
      ) : (
        <div className="driver-empty driver-empty-large">
          <div className="driver-empty-icon">▣</div>
          <h2>No assigned trips</h2>
          <p>Trips assigned to your driver profile will appear here.</p>
        </div>
      )}
    </div>
  );
}

function PassengersPage({ bookings, onBoard }) {
  return (
    <div className="driver-content">
      <PageHeader
        eyebrow="MANIFEST"
        title="Passengers"
        description="Passengers assigned to your trips, including their pickup stages."
      />

      {bookings.length ? (
        <div className="driver-list">
          {bookings.map((booking) => (
            <BookingCard
              key={bookingId(booking)}
              booking={booking}
              onBoard={onBoard}
            />
          ))}
        </div>
      ) : (
        <div className="driver-empty driver-empty-large">
          <div className="driver-empty-icon">♟</div>
          <h2>No passengers assigned</h2>
          <p>Passenger bookings will appear here when assigned to your trips.</p>
        </div>
      )}
    </div>
  );
}

function BoardingPage({ bookings, onBoard }) {
  const active = bookings.filter((booking) =>
    ["confirmed", "pending"].includes(String(booking?.status || "").toLowerCase())
  );

  return (
    <div className="driver-content">
      <PageHeader
        eyebrow="BOARDING CONTROL"
        title="Verify Boarding"
        description="Select a confirmed passenger and verify the boarding PIN."
      />

      {active.length ? (
        <div className="driver-list">
          {active.map((booking) => (
            <article className="driver-boarding-card" key={bookingId(booking)}>
              <div>
                <span className="driver-card-label">PASSENGER</span>
                <h2>{bookingPassenger(booking)}</h2>
                <p>{bookingRoute(booking)}</p>
              </div>

              <div className="driver-boarding-details">
                <div>
                  <span>Pickup</span>
                  <strong>{bookingStage(booking)}</strong>
                </div>
                <div>
                  <span>Seats</span>
                  <strong>{bookingSeats(booking)}</strong>
                </div>
                <div>
                  <span>Booking</span>
                  <strong>#{bookingId(booking)}</strong>
                </div>
              </div>

              <button
                type="button"
                className="driver-primary-button driver-boarding-button"
                onClick={() => onBoard(booking)}
              >
                Verify PIN
              </button>
            </article>
          ))}
        </div>
      ) : (
        <div className="driver-empty driver-empty-large">
          <div className="driver-empty-icon">✓</div>
          <h2>Nothing waiting for boarding</h2>
          <p>Confirmed passenger bookings will appear here.</p>
        </div>
      )}
    </div>
  );
}

function ProfilePage({ driver }) {
  return (
    <div className="driver-content">
      <PageHeader
        eyebrow="ACCOUNT"
        title="Driver Profile"
        description="Your driver and company information."
      />

      <section className="driver-profile-grid">
        <div className="driver-profile-hero">
          <div className="driver-profile-avatar">
            {getUserName(driver).charAt(0).toUpperCase()}
          </div>
          <h2>{getUserName(driver)}</h2>
          <p>{getCompanyName(driver)}</p>
        </div>

        <div className="driver-panel">
          <div className="driver-panel-heading">
            <div>
              <span className="driver-eyebrow">DRIVER DETAILS</span>
              <h2>Profile information</h2>
            </div>
          </div>

          <div className="driver-detail-grid">
            <div>
              <span>Name</span>
              <strong>{getUserName(driver)}</strong>
            </div>
            <div>
              <span>Company</span>
              <strong>{getCompanyName(driver)}</strong>
            </div>
            <div>
              <span>Vehicle</span>
              <strong>{getVehicle(driver)}</strong>
            </div>
            <div>
              <span>Phone</span>
              <strong>{first(driver?.phone, first(driver?.user?.phone, "—"))}</strong>
            </div>
            <div>
              <span>Driver ID</span>
              <strong>{first(driver?.id, first(driver?.driver_id, "—"))}</strong>
            </div>
            <div>
              <span>Status</span>
              <strong>{first(driver?.status, "Active")}</strong>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

function LiveLocationPage({ driver, bookings }) {
  const [position, setPosition] = useState(null);
  const [mapData, setMapData] = useState(null);
  const [selectedBooking, setSelectedBooking] = useState(bookings[0] || null);
  const [locationStatus, setLocationStatus] = useState("Waiting for GPS");
  const [error, setError] = useState("");
  const watchRef = useRef(null);
  const lastSentRef = useRef(0);

  useEffect(() => {
    if (!selectedBooking && bookings.length) {
      setSelectedBooking(bookings[0]);
    }
  }, [bookings, selectedBooking]);

  useEffect(() => {
    if (!selectedBooking) {
      setMapData(null);
      return;
    }

    const rid = routeId(selectedBooking);
    const tid = tripId(selectedBooking);

    if (!rid) {
      setMapData(null);
      return;
    }

    let cancelled = false;

    api(`/companies/routes/${rid}/map/${tid ? `?trip_id=${encodeURIComponent(tid)}` : ""}`)
      .then((data) => {
        if (!cancelled) setMapData(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedBooking]);

  const sendLocation = useCallback(
    async (lat, lng) => {
      const id = driver?.id || driver?.driver_id;

      if (!id) return;

      try {
        await api(`/drivers/${id}/location/`, {
          method: "POST",
          body: JSON.stringify({
            latitude: lat,
            longitude: lng,
          }),
        });

        setLocationStatus("Location sharing active");
      } catch (err) {
        setLocationStatus(`Location update failed: ${err.message}`);
      }
    },
    [driver]
  );

  useEffect(() => {
    if (!navigator.geolocation) {
      setLocationStatus("GPS unavailable");
      return undefined;
    }

    watchRef.current = navigator.geolocation.watchPosition(
      async (geo) => {
        const lat = geo.coords.latitude;
        const lng = geo.coords.longitude;

        setPosition([lat, lng]);

        const now = Date.now();

        if (now - lastSentRef.current > 5000) {
          lastSentRef.current = now;
          await sendLocation(lat, lng);
        }
      },
      (geoError) => {
        setLocationStatus(`GPS: ${geoError.message}`);
      },
      {
        enableHighAccuracy: true,
        maximumAge: 5000,
        timeout: 15000,
      }
    );

    return () => {
      if (watchRef.current !== null) {
        navigator.geolocation.clearWatch(watchRef.current);
      }
    };
  }, [sendLocation]);

  const routePositions = useMemo(() => {
    const coords = mapData?.geometry?.coordinates || [];

    return coords
      .filter((point) => Array.isArray(point) && point.length >= 2)
      .map(([lng, lat]) => [Number(lat), Number(lng)]);
  }, [mapData]);

  const stagePositions = useMemo(() => {
    return (mapData?.stages || [])
      .filter((stage) => Number.isFinite(Number(stage.latitude)) && Number.isFinite(Number(stage.longitude)))
      .map((stage) => [Number(stage.latitude), Number(stage.longitude), stage]);
  }, [mapData]);

  const pickupPositions = useMemo(() => {
    return bookings
      .filter((booking) => {
        const lat = Number(
          booking?.pickup_latitude ??
          booking?.pickup_stage?.latitude
        );
        const lng = Number(
          booking?.pickup_longitude ??
          booking?.pickup_stage?.longitude
        );

        return Number.isFinite(lat) && Number.isFinite(lng);
      })
      .map((booking) => ({
        lat: Number(booking?.pickup_latitude ?? booking?.pickup_stage?.latitude),
        lng: Number(booking?.pickup_longitude ?? booking?.pickup_stage?.longitude),
        booking,
      }));
  }, [bookings]);

  const allPositions = [
    ...routePositions,
    ...stagePositions.map(([lat, lng]) => [lat, lng]),
    ...(position ? [position] : []),
    ...pickupPositions.map(({ lat, lng }) => [lat, lng]),
  ];

  const center =
    position ||
    routePositions[0] ||
    [-1.286389, 36.817223];

  return (
    <div className="driver-map-page">
      <div className="driver-map">
        <MapContainer
          center={center}
          zoom={13}
          zoomControl={true}
          scrollWheelZoom={true}
          dragging={true}
          doubleClickZoom={true}
          touchZoom={true}
          className="driver-full-map"
        >
          <TileLayer
            attribution='&copy; OpenStreetMap contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />

          <MapFit positions={allPositions} />

          {routePositions.length > 1 && (
            <>
              <Polyline
                positions={routePositions}
                pathOptions={{
                  color: "#2563eb",
                  weight: 10,
                  opacity: 0.18,
                }}
              />
              <Polyline
                positions={routePositions}
                pathOptions={{
                  color: "#2563eb",
                  weight: 5,
                  opacity: 0.95,
                }}
              />
              <Polyline
                positions={routePositions}
                pathOptions={{
                  color: "#ffffff",
                  weight: 2,
                  opacity: 0.9,
                }}
              />
            </>
          )}

          {stagePositions.map(([lat, lng, stage]) => (
            <Marker
              key={`stage-${stage.id}`}
              position={[lat, lng]}
              icon={stageIcon(stage)}
            >
              <Popup>
                <strong>Stage {stage.order}</strong>
                <br />
                {stage.name}
                {stage.passenger_count > 0 && (
                  <>
                    <br />
                    {stage.passenger_count} passenger
                    {stage.passenger_count === 1 ? "" : "s"}
                  </>
                )}
              </Popup>
            </Marker>
          ))}

          {pickupPositions.map(({ lat, lng, booking }) => (
            <Marker
              key={`pickup-${bookingId(booking)}`}
              position={[lat, lng]}
              icon={passengerIcon()}
            >
              <Popup>
                <strong>{bookingPassenger(booking)}</strong>
                <br />
                Pickup: {bookingStage(booking)}
              </Popup>
            </Marker>
          ))}

          {position && (
            <Marker position={position} icon={busIcon()}>
              <Popup>
                <strong>Your current location</strong>
                <br />
                {locationStatus}
              </Popup>
            </Marker>
          )}
        </MapContainer>
      </div>

      <div className="driver-map-topbar">
        <button
          type="button"
          className="driver-map-back"
          onClick={() => window.history.back()}
        >
          ←
        </button>

        <div>
          <strong>Live Location</strong>
          <span>{locationStatus}</span>
        </div>

        <div className="driver-map-live-dot" />
      </div>

      <div className="driver-map-sheet">
        <div className="driver-sheet-handle" />

        <div className="driver-sheet-heading">
          <div>
            <span className="driver-eyebrow">LIVE TRIP</span>
            <h2>{mapData?.route_name || bookingRoute(selectedBooking || {})}</h2>
          </div>

          <span className="driver-live-badge">LIVE</span>
        </div>

        <select
          className="driver-trip-select"
          value={bookingId(selectedBooking) || ""}
          onChange={(e) => {
            const found = bookings.find(
              (booking) => String(bookingId(booking)) === e.target.value
            );
            setSelectedBooking(found || null);
          }}
        >
          {bookings.length ? (
            bookings.map((booking) => (
              <option key={bookingId(booking)} value={bookingId(booking)}>
                {bookingPassenger(booking)} · {bookingStage(booking)}
              </option>
            ))
          ) : (
            <option value="">No assigned bookings</option>
          )}
        </select>

        <div className="driver-map-stats">
          <div>
            <span>Stages</span>
            <strong>{mapData?.stages?.length || 0}</strong>
          </div>
          <div>
            <span>Passengers</span>
            <strong>{bookings.reduce((n, b) => n + bookingSeats(b), 0)}</strong>
          </div>
          <div>
            <span>GPS</span>
            <strong>{position ? "ON" : "WAIT"}</strong>
          </div>
        </div>

        {error && <div className="driver-error">{error}</div>}
      </div>
    </div>
  );
}

function BoardingModal({ booking, onClose, onSuccess }) {
  const [pin, setPin] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const verify = async () => {
    if (!/^\d{4}$/.test(pin)) {
      setError("Enter the 4-digit boarding PIN.");
      return;
    }

    setLoading(true);
    setError("");

    try {
      await api(`/bookings/${bookingId(booking)}/verify-boarding/`, {
        method: "POST",
        body: JSON.stringify({
          boarding_pin: pin,
        }),
      });

      await onSuccess();
    } catch (err) {
      setError(err.message || "Boarding verification failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="driver-modal-backdrop" onMouseDown={onClose}>
      <div className="driver-modal" onMouseDown={(e) => e.stopPropagation()}>
        <div className="driver-modal-icon">✓</div>

        <span className="driver-eyebrow">BOARDING VERIFICATION</span>
        <h2>Verify passenger</h2>
        <p>
          Enter the passenger's 4-digit boarding PIN to confirm that they have
          boarded the vehicle.
        </p>

        <div className="driver-modal-passenger">
          <strong>{bookingPassenger(booking)}</strong>
          <span>{bookingStage(booking)}</span>
        </div>

        <input
          autoFocus
          inputMode="numeric"
          maxLength={4}
          value={pin}
          onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 4))}
          onKeyDown={(e) => {
            if (e.key === "Enter") verify();
          }}
          className="driver-pin-input"
          placeholder="••••"
        />

        {error && <div className="driver-error">{error}</div>}

        <div className="driver-modal-actions">
          <button
            type="button"
            className="driver-secondary-button"
            onClick={onClose}
            disabled={loading}
          >
            Cancel
          </button>

          <button
            type="button"
            className="driver-primary-button"
            onClick={verify}
            disabled={loading || pin.length !== 4}
          >
            {loading ? "Verifying…" : "Verify boarding"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function DriverPortal() {
  const location = useLocation();
  const navigate = useNavigate();
  const { driver, bookings, loading, error, reload } = useDriverData();
  const [boardingBooking, setBoardingBooking] = useState(null);

  const path = location.pathname.replace(/\/+$/, "");

  let page = "overview";

  if (path === "/driver/trips") page = "trips";
  else if (path === "/driver/passengers") page = "passengers";
  else if (path === "/driver/location") page = "location";
  else if (path === "/driver/boarding") page = "boarding";
  else if (path === "/driver/profile") page = "profile";

  const handleBoard = (booking) => {
    setBoardingBooking(booking);
  };

  const finishBoarding = async () => {
    setBoardingBooking(null);
    await reload();
  };

  if (page === "location") {
    if (loading) {
      return (
        <div className="driver-map-loading">
          <div className="driver-loading-spinner" />
          <span>Loading live location…</span>
        </div>
      );
    }

    return <LiveLocationPage driver={driver} bookings={bookings} />;
  }

  if (loading) {
    return (
      <div className="driver-app-loading">
        <div className="driver-loading-spinner" />
        <span>Loading driver portal…</span>
      </div>
    );
  }

  if (!driver) {
    return (
      <div className="driver-app-loading">
        <div className="driver-error driver-loading-error">
          {error || "Driver profile could not be loaded."}
          <button
            type="button"
            className="driver-primary-button"
            onClick={() => navigate("/login")}
          >
            Return to login
          </button>
        </div>
      </div>
    );
  }

  return (
    <>
      <DriverShell
        driver={driver}
        active={page}
        onRefresh={reload}
      >
        {error && (
          <div className="driver-error driver-global-error">
            {error}
          </div>
        )}

        {page === "overview" && (
          <OverviewPage
            driver={driver}
            bookings={bookings}
            navigate={navigate}
            onBoard={handleBoard}
          />
        )}

        {page === "trips" && (
          <TripsPage
            bookings={bookings}
            navigate={navigate}
          />
        )}

        {page === "passengers" && (
          <PassengersPage
            bookings={bookings}
            onBoard={handleBoard}
          />
        )}

        {page === "boarding" && (
          <BoardingPage
            bookings={bookings}
            onBoard={handleBoard}
          />
        )}

        {page === "profile" && (
          <ProfilePage driver={driver} />
        )}
      </DriverShell>

      {boardingBooking && (
        <BoardingModal
          booking={boardingBooking}
          onClose={() => setBoardingBooking(null)}
          onSuccess={finishBoarding}
        />
      )}
    </>
  );
}
