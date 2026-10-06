import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { apiRequest } from "../../api";

const pages = [
  { path: "/driver", label: "Overview", icon: "▦" },
  { path: "/driver/trips", label: "Today's Trips", icon: "▣" },
  { path: "/driver/passengers", label: "Passengers", icon: "♙" },
  { path: "/driver/location", label: "Live Location", icon: "⌖" },
  { path: "/driver/boarding", label: "Boarding", icon: "✓" },
  { path: "/driver/profile", label: "Profile", icon: "◉" },
];

function getPage(pathname) {
  if (pathname === "/driver") return "overview";
  if (pathname.startsWith("/driver/trips")) return "trips";
  if (pathname.startsWith("/driver/passengers")) return "passengers";
  if (pathname.startsWith("/driver/location")) return "location";
  if (pathname.startsWith("/driver/boarding")) return "boarding";
  if (pathname.startsWith("/driver/profile")) return "profile";
  return "overview";
}

function Card({ title, children }) {
  return (
    <div style={{
      background: "#fff",
      borderRadius: 18,
      padding: 22,
      boxShadow: "0 8px 30px rgba(15,23,42,.08)",
      border: "1px solid #e5e7eb"
    }}>
      <h2 style={{ margin: "0 0 14px", fontSize: 20, color: "#111827" }}>
        {title}
      </h2>
      {children}
    </div>
  );
}

function Overview({ driver, bookings }) {
  return (
    <>
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))",
        gap: 16,
        marginBottom: 22
      }}>
        <Card title="Today's Trips">
          <strong style={{ fontSize: 32 }}>{bookings.length}</strong>
        </Card>

        <Card title="Passengers">
          <strong style={{ fontSize: 32 }}>
            {bookings.reduce((sum, b) => sum + Number(b.seats || 1), 0)}
          </strong>
        </Card>

        <Card title="Driver Status">
          <strong style={{ color: "#16a34a" }}>Active</strong>
        </Card>
      </div>

      <Card title="Driver Dashboard">
        <p style={{ color: "#64748b", marginTop: 0 }}>
          Welcome back. Your assigned trips and passenger information appear here.
        </p>

        <div style={{
          background: "#f8fafc",
          padding: 18,
          borderRadius: 12,
          marginTop: 16
        }}>
          <div><b>Name:</b> {driver?.user?.username || driver?.username || "Driver"}</div>
          <div style={{ marginTop: 8 }}>
            <b>Company:</b> {driver?.company?.name || driver?.company_name || "Assigned company"}
          </div>
        </div>
      </Card>
    </>
  );
}

function Trips({ bookings, navigate }) {
  return (
    <Card title="Today's Trips">
      {bookings.length === 0 ? (
        <p style={{ color: "#64748b" }}>No assigned trips found.</p>
      ) : (
        <div style={{ display: "grid", gap: 12 }}>
          {bookings.map((booking) => (
            <div
              key={booking.id}
              style={{
                padding: 16,
                border: "1px solid #e5e7eb",
                borderRadius: 14,
                background: "#f8fafc"
              }}
            >
              <div style={{ fontWeight: 700, color: "#111827" }}>
                {booking.route_name ||
                  booking.route?.name ||
                  `Trip #${booking.trip_id || booking.id}`}
              </div>

              <div style={{ color: "#64748b", marginTop: 5 }}>
                Pickup: {booking.pickup_location || booking.pickup_stage_name || "Not specified"}
              </div>

              <div style={{ marginTop: 12 }}>
                <button
                  onClick={() => navigate("/driver/boarding")}
                  style={buttonStyle}
                >
                  Open Boarding
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function Passengers({ bookings }) {
  return (
    <Card title="Passengers">
      {bookings.length === 0 ? (
        <p style={{ color: "#64748b" }}>No passengers found.</p>
      ) : (
        <div style={{ display: "grid", gap: 10 }}>
          {bookings.map((booking) => (
            <div
              key={booking.id}
              style={{
                padding: 15,
                borderBottom: "1px solid #e5e7eb"
              }}
            >
              <b>{booking.passenger_name || booking.user_name || "Passenger"}</b>
              <div style={{ color: "#64748b", marginTop: 4 }}>
                Seats: {booking.seats || 1}
              </div>
              <div style={{ color: "#64748b" }}>
                Pickup: {booking.pickup_location || booking.pickup_stage_name || "Not specified"}
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function Boarding({ bookings }) {
  const [pin, setPin] = useState("");
  const [selected, setSelected] = useState("");
  const [message, setMessage] = useState("");

  async function verify() {
    if (!selected || !pin.trim()) {
      setMessage("Select a booking and enter the boarding PIN.");
      return;
    }

    setMessage("Verifying...");

    try {
      const result = await apiRequest(
        `/bookings/${selected}/verify-boarding/`,
        {
          method: "POST",
          body: JSON.stringify({ pin: pin.trim() }),
        }
      );

      setMessage(result?.message || "Boarding verified successfully.");
      setPin("");
    } catch (error) {
      setMessage(error?.message || "Boarding verification failed.");
    }
  }

  return (
    <Card title="Boarding Verification">
      {bookings.length === 0 ? (
        <p style={{ color: "#64748b" }}>No bookings available for boarding.</p>
      ) : (
        <>
          <label style={labelStyle}>Passenger booking</label>

          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            style={inputStyle}
          >
            <option value="">Select passenger</option>
            {bookings.map((booking) => (
              <option key={booking.id} value={booking.id}>
                {booking.passenger_name ||
                  booking.user_name ||
                  `Booking #${booking.id}`}
              </option>
            ))}
          </select>

          <label style={labelStyle}>Boarding PIN</label>

          <input
            value={pin}
            onChange={(e) => setPin(e.target.value)}
            placeholder="Enter PIN"
            inputMode="numeric"
            style={inputStyle}
          />

          <button onClick={verify} style={buttonStyle}>
            Verify Boarding
          </button>

          {message && (
            <div style={{
              marginTop: 15,
              padding: 12,
              borderRadius: 10,
              background: "#f1f5f9"
            }}>
              {message}
            </div>
          )}
        </>
      )}
    </Card>
  );
}

function LocationPage() {
  return (
    <Card title="Live Location">
      <p style={{ color: "#64748b" }}>
        Your live-location page is available here.
      </p>

      <Link
        to="/driver/location"
        style={{
          ...buttonStyle,
          display: "inline-block",
          textDecoration: "none"
        }}
      >
        Open Live Location
      </Link>
    </Card>
  );
}

function Profile({ driver }) {
  return (
    <Card title="Driver Profile">
      <div style={{ display: "grid", gap: 12 }}>
        <div><b>Username:</b> {driver?.user?.username || driver?.username || "—"}</div>
        <div><b>Phone:</b> {driver?.phone || driver?.user?.phone || "—"}</div>
        <div><b>Company:</b> {driver?.company?.name || driver?.company_name || "—"}</div>
        <div><b>Status:</b> {driver?.status || "Active"}</div>
      </div>
    </Card>
  );
}

const buttonStyle = {
  border: 0,
  borderRadius: 10,
  padding: "11px 17px",
  background: "#2563eb",
  color: "#fff",
  fontWeight: 700,
  cursor: "pointer"
};

const inputStyle = {
  width: "100%",
  boxSizing: "border-box",
  padding: "12px 14px",
  marginBottom: 15,
  border: "1px solid #cbd5e1",
  borderRadius: 10,
  fontSize: 15
};

const labelStyle = {
  display: "block",
  fontWeight: 700,
  marginBottom: 7,
  color: "#334155"
};

export default function DriverPortal() {
  const location = useLocation();
  const navigate = useNavigate();

  const [driver, setDriver] = useState(null);
  const [bookings, setBookings] = useState([]);
  const [error, setError] = useState("");

  const page = getPage(location.pathname);

  useEffect(() => {
    let alive = true;

    async function load() {
      try {
        const driverData = await apiRequest("/drivers/me/");

        if (!alive) return;
        setDriver(driverData);

        const driverId =
          driverData?.id ||
          driverData?.driver?.id ||
          driverData?.profile?.id;

        if (driverId) {
          const bookingData = await apiFetch(
            `/bookings/driver/${driverId}/`
          );

          if (!alive) return;

          const list = Array.isArray(bookingData)
            ? bookingData
            : bookingData?.results ||
              bookingData?.bookings ||
              [];

          setBookings(list);
        }
      } catch (e) {
        if (alive) {
          setError(e?.message || "Unable to load driver information.");
        }
      }
    }

    load();

    return () => {
      alive = false;
    };
  }, []);

  const content = {
    overview: <Overview driver={driver} bookings={bookings} />,
    trips: <Trips bookings={bookings} navigate={navigate} />,
    passengers: <Passengers bookings={bookings} />,
    location: <LocationPage />,
    boarding: <Boarding bookings={bookings} />,
    profile: <Profile driver={driver} />,
  }[page];

  return (
    <div style={{
      minHeight: "100vh",
      background: "#f1f5f9",
      color: "#0f172a",
      fontFamily: "Inter, system-ui, -apple-system, BlinkMacSystemFont, sans-serif"
    }}>
      <header style={{
        height: 70,
        background: "#0f172a",
        color: "#fff",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0 28px",
        boxSizing: "border-box"
      }}>
        <div>
          <div style={{ fontSize: 21, fontWeight: 800 }}>CONNECT</div>
          <div style={{ fontSize: 12, color: "#94a3b8" }}>Driver Portal</div>
        </div>

        <div style={{ fontWeight: 600 }}>
          {driver?.user?.username || driver?.username || "Driver"}
        </div>
      </header>

      <div style={{
        display: "flex",
        minHeight: "calc(100vh - 70px)"
      }}>
        <aside style={{
          width: 235,
          background: "#fff",
          borderRight: "1px solid #e2e8f0",
          padding: 16,
          boxSizing: "border-box"
        }}>
          {pages.map((item) => {
            const active =
              item.path === "/driver"
                ? location.pathname === "/driver"
                : location.pathname.startsWith(item.path);

            return (
              <Link
                key={item.path}
                to={item.path}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  padding: "13px 14px",
                  marginBottom: 6,
                  borderRadius: 10,
                  textDecoration: "none",
                  color: active ? "#fff" : "#334155",
                  background: active ? "#2563eb" : "transparent",
                  fontWeight: active ? 700 : 600
                }}
              >
                <span style={{ width: 22, textAlign: "center" }}>
                  {item.icon}
                </span>
                {item.label}
              </Link>
            );
          })}
        </aside>

        <main style={{
          flex: 1,
          padding: 28,
          boxSizing: "border-box",
          maxWidth: 1200
        }}>
          <div style={{ marginBottom: 24 }}>
            <h1 style={{
              margin: 0,
              fontSize: 30,
              fontWeight: 800,
              color: "#0f172a"
            }}>
              {pages.find((p) =>
                page === getPage(p.path)
              )?.label || "Driver Portal"}
            </h1>
            <p style={{
              margin: "7px 0 0",
              color: "#64748b"
            }}>
              Manage your trips, passengers and boarding.
            </p>
          </div>

          {error && (
            <div style={{
              marginBottom: 18,
              padding: 14,
              borderRadius: 12,
              background: "#fee2e2",
              color: "#991b1b"
            }}>
              {error}
            </div>
          )}

          {content}
        </main>
      </div>
    </div>
  );
}
