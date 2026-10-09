import AppShell from '../../components/layout/AppShell';
import './PassengerRecords.css';
import { useAuth } from '../../context/AuthContext';
import { useEffect, useMemo, useState } from 'react';
import { apiRequest } from '../../api';
import {
  CreditCard,
  MapPin,
  ShieldCheck,
  UserRound,
  WalletCards,
  Search,
  Receipt,
  History,
  CircleHelp,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  XCircle,
} from 'lucide-react';

const money = (v) =>
  `KES ${Number(v || 0).toLocaleString('en-KE', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

const date = (v) =>
  v
    ? new Date(v).toLocaleString('en-KE', {
        dateStyle: 'medium',
        timeStyle: 'short',
      })
    : 'Not scheduled';

function PassengerPage({ eyebrow, title, description, children }) {
  return (
    <AppShell>
      <div className="passenger-page">
        <div className="passenger-page-heading">
          <span className="glass-eyebrow">{eyebrow}</span>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>

        {children}
      </div>
    </AppShell>
  );
}


export function PassengerRecords({ mode = 'receipts' }) {
  const [records, setRecords] = useState([]);
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState(null);

  const load = async (value = '') => {
    setLoading(true);
    setError('');
    try {
      const suffix = value
        ? `?search=${encodeURIComponent(value)}`
        : '';
      const data = await apiRequest(`/bookings/records/${suffix}`);
      setRecords(Array.isArray(data) ? data : []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const visible = useMemo(() => {
    if (mode === 'history') return records;
    return records.filter((r) => r.payment?.exists);
  }, [records, mode]);

  const statusIcon = (status) => {
    if (status === 'confirmed' || status === 'completed') {
      return <CheckCircle2 size={18} />;
    }
    if (status === 'failed' || status === 'cancelled') {
      return <XCircle size={18} />;
    }
    return <Clock3 size={18} />;
  };

  return (
    <PassengerPage
      eyebrow={mode === 'history' ? 'ACTIVITY / HISTORY' : 'RECEIPTS'}
      title={mode === 'history' ? 'Your activity history' : 'Your receipts'}
      description={
        mode === 'history'
          ? 'A complete record of bookings, payments, boarding and refunds.'
          : 'Search and open your personal CONNECT payment records.'
      }
    >
      <div className="records-search">
        <Search size={19} />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              setQuery(search);
              load(search);
            }
          }}
          placeholder="Search booking number or payment reference..."
        />
        <button
          className="btn btn-primary"
          onClick={() => {
            setQuery(search);
            load(search);
          }}
        >
          Search
        </button>
      </div>

      {query && (
        <div className="records-search-note">
          Results for <strong>{query}</strong>
          <button
            className="btn btn-ghost"
            onClick={() => {
              setSearch('');
              setQuery('');
              load();
            }}
          >
            Clear
          </button>
        </div>
      )}

      {error && (
        <div className="connect-alert connect-alert-error">
          {error}
        </div>
      )}

      {loading ? (
        <div className="glass-empty">Loading your records…</div>
      ) : !visible.length ? (
        <div className="glass-empty">
          {mode === 'history' ? (
            <History size={30} />
          ) : (
            <Receipt size={30} />
          )}
          <strong>No records found.</strong>
          <span>
            {query
              ? 'No CONNECT record matches that reference.'
              : 'Your CONNECT records will appear here after you make a booking.'}
          </span>
        </div>
      ) : (
        <div className="records-layout">
          <div className="records-list">
            {visible.map((record) => (
              <button
                type="button"
                className={`record-card ${
                  selected?.booking_id === record.booking_id
                    ? 'record-card-active'
                    : ''
                }`}
                key={record.booking_id}
                onClick={() => setSelected(record)}
              >
                <div className="record-card-icon">
                  {mode === 'history'
                    ? <History size={20} />
                    : <Receipt size={20} />}
                </div>

                <div className="record-card-main">
                  <strong>{record.booking_number}</strong>
                  <span>
                    {record.trip?.route || 'CONNECT Journey'}
                  </span>
                  <small>
                    {record.trip?.company || 'CONNECT'}
                  </small>
                </div>

                <div className="record-card-status">
                  {statusIcon(record.payment?.status || record.booking?.status)}
                  <span>
                    {record.payment?.status ||
                      record.booking?.status ||
                      'pending'}
                  </span>
                  <strong>
                    {money(record.payment?.amount)}
                  </strong>
                </div>
              </button>
            ))}
          </div>

          {selected && (
            <article className="record-detail-panel">
              <div className="record-detail-header">
                <div>
                  <span className="glass-eyebrow">
                    UNIQUE TRIP REFERENCE
                  </span>
                  <h2>{selected.booking_number}</h2>
                </div>
                <button
                  className="btn btn-ghost"
                  onClick={() => setSelected(null)}
                >
                  Close
                </button>
              </div>

              <div className="record-section">
                <h3>Passenger</h3>
                <div className="record-info-grid">
                  <span>Name<strong>{selected.passenger?.name}</strong></span>
                  <span>Username<strong>{selected.passenger?.username}</strong></span>
                  <span>Phone<strong>{selected.passenger?.phone_number}</strong></span>
                </div>
              </div>

              <div className="record-section">
                <h3>Trip</h3>
                <div className="record-info-grid">
                  <span>Company<strong>{selected.trip?.company || '—'}</strong></span>
                  <span>Route<strong>{selected.trip?.route || '—'}</strong></span>
                  <span>Pickup<strong>{selected.trip?.pickup_location || '—'}</strong></span>
                  <span>Seats<strong>{selected.trip?.seats || '—'}</strong></span>
                  <span>Departure<strong>{date(selected.trip?.departure_at)}</strong></span>
                </div>
              </div>

              <div className="record-section">
                <h3>Booking</h3>
                <div className="record-info-grid">
                  <span>Status<strong>{selected.booking?.status}</strong></span>
                  <span>Created<strong>{date(selected.booking?.created_at)}</strong></span>
                  <span>Updated<strong>{date(selected.booking?.updated_at)}</strong></span>
                  {selected.booking?.verification_pin && (
                    <span>Boarding PIN (show only to the driver)
                      <strong style={{ letterSpacing: '0.25em', fontSize: '1.5em' }}>
                        {selected.booking.verification_pin}
                      </strong>
                    </span>
                  )}
                </div>
              </div>

              <div className="record-section">
                <h3>Payment</h3>
                <div className="record-info-grid">
                  <span>Amount<strong>{money(selected.payment?.amount)}</strong></span>
                  <span>Method<strong>{selected.payment?.method || '—'}</strong></span>
                  <span>Status<strong>{selected.payment?.status || 'unpaid'}</strong></span>
                  <span>Provider reference<strong>{selected.payment?.provider_reference || '—'}</strong></span>
                  <span>Started<strong>{date(selected.payment?.created_at)}</strong></span>
                  <span>Confirmed<strong>{date(selected.payment?.confirmed_at)}</strong></span>
                  <span>Refund<strong>{selected.payment?.refund_status || '—'}</strong></span>
                  <span>Refund reference<strong>{selected.payment?.refund_reference || '—'}</strong></span>
                </div>
              </div>

              {selected.incident && (
                <div className="record-section record-issue">
                  <h3>
                    <AlertTriangle size={18} />
                    Issue
                  </h3>
                  <p>{selected.incident.description}</p>
                  <div className="record-info-grid">
                    <span>Type<strong>{selected.incident.incident_type}</strong></span>
                    <span>Status<strong>{selected.incident.incident_status}</strong></span>
                    <span>Resolution<strong>{selected.incident.resolution}</strong></span>
                  </div>
                </div>
              )}

              <div className="record-section">
                <h3>Activity</h3>
                <div className="record-timeline">
                  {selected.activity?.map((event, index) => (
                    <div className="record-timeline-item" key={`${event.type}-${index}`}>
                      <div className="timeline-dot">
                        {statusIcon(event.status)}
                      </div>
                      <div>
                        <strong>{event.label}</strong>
                        <span>{date(event.timestamp)}</span>
                        {event.reference && (
                          <small>Reference: {event.reference}</small>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </article>
          )}
        </div>
      )}
    </PassengerPage>
  );
}

export function PassengerSeats() {
  return (
    <PassengerPage
      eyebrow="SEATS"
      title="Your reserved seats"
      description="See the seats attached to your active CONNECT bookings."
    >
      <BookingsBody activeOnly />
    </PassengerPage>
  );
}

export function PassengerHelp() {
  return (
    <PassengerPage
      eyebrow="HELP & ISSUES"
      title="Need help with a journey?"
      description="Use your unique booking reference when reporting a payment, booking or trip issue."
    >
      <div className="help-glass-grid">
        <div className="help-glass-card">
          <CircleHelp size={26} />
          <h3>Booking issue</h3>
          <p>
            Keep your booking number ready so CONNECT support can trace the
            exact passenger, trip and booking record.
          </p>
        </div>

        <div className="help-glass-card">
          <CreditCard size={26} />
          <h3>Payment issue</h3>
          <p>
            Search your payment reference in Receipts to see its current
            status and confirmation information.
          </p>
        </div>

        <div className="help-glass-card">
          <AlertTriangle size={26} />
          <h3>Trip issue</h3>
          <p>
            For incidents affecting a trip, your booking record can show the
            related incident and resolution when one exists.
          </p>
        </div>
      </div>
    </PassengerPage>
  );
}

function BookingsBody({ activeOnly = false }) {
  const [bookings, setBookings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    apiRequest('/bookings/my/')
      .then((data) => setBookings(Array.isArray(data) ? data : []))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const visible = activeOnly
    ? bookings.filter(
        (b) =>
          ['pending', 'confirmed'].includes(
            String(b.status || '').toLowerCase()
          ) &&
          !['completed', 'cancelled'].includes(
            String(b.trip_status || '').toLowerCase()
          )
      )
    : bookings;

  return (
    <>
      {error && <div className="connect-alert connect-alert-error">{error}</div>}

      {loading ? (
        <div className="glass-empty">Loading your bookings…</div>
      ) : !visible.length ? (
        <div className="glass-empty">
          <strong>No bookings yet.</strong>
          <span>Book a seat from Find a Trip to see your journeys here.</span>
        </div>
      ) : (
        <div className="passenger-data-grid">
          {visible.map((booking) => (
            <article className="passenger-data-card" key={booking.booking_id}>
              <div className="data-card-top">
                <div>
                  <span className="data-card-label">BOOKING</span>
                  <strong>{booking.booking_number}</strong>
                </div>

                <span className="passenger-status">
                  {booking.status}
                </span>
              </div>

              <h2>{booking.route_name || 'CONNECT Journey'}</h2>

              <div className="data-card-details">
                <span>💺 {booking.seats} seat(s)</span>
                <span>📍 {booking.pickup_location}</span>
                <span>💳 {booking.payment_status}</span>
              </div>

              {booking.verification_pin && (
                <div className="data-card-details" style={{ marginTop: 8 }}>
                  <span>
                    Boarding PIN (show only to the driver){' '}
                    <strong style={{ letterSpacing: '0.25em', fontSize: '1.5em' }}>
                      {booking.verification_pin}
                    </strong>
                  </span>
                </div>
              )}

              <div className="data-card-bottom">
                <strong>{money(booking.total_amount)}</strong>
                <span>{booking.payment_method || 'Payment pending'}</span>
              </div>
            </article>
          ))}
        </div>
      )}
    </>
  );
}

export function PassengerBookings() {
  return (
    <PassengerPage
      eyebrow="MY BOOKINGS"
      title="Your journeys"
      description="View your upcoming, completed and cancelled CONNECT bookings."
    >
      <BookingsBody />
    </PassengerPage>
  );
}

export function PassengerWallet() {
  const [wallet, setWallet] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    apiRequest('/wallet/')
      .then(setWallet)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <PassengerPage
      eyebrow="WALLET"
      title="Your CONNECT wallet"
      description="Manage the balance used for your protected journey payments."
    >
      {error && <div className="connect-alert connect-alert-error">{error}</div>}

      <div className="wallet-overview-grid">
        <div className="wallet-glass-card wallet-main">
          <WalletCards size={26} />
          <span>AVAILABLE BALANCE</span>
          <strong>{money(wallet?.available_balance)}</strong>
          <p>Available for new bookings.</p>
        </div>

        <div className="wallet-glass-card">
          <ShieldCheck size={24} />
          <span>HELD BALANCE</span>
          <strong>{money(wallet?.held_balance)}</strong>
          <p>Protected while a booking is awaiting boarding.</p>
        </div>
      </div>

      <div className="passenger-info-panel">
        <WalletCards size={21} />
        <div>
          <strong>Protected payments</strong>
          <p>
            CONNECT holds eligible booking payments until the journey's
            boarding process confirms the trip.
          </p>
        </div>
      </div>
    </PassengerPage>
  );
}

export function PassengerPayments() {
  const [bookings, setBookings] = useState([]);
  const [error, setError] = useState('');

  useEffect(() => {
    apiRequest('/bookings/my/')
      .then((data) => setBookings(Array.isArray(data) ? data : []))
      .catch((e) => setError(e.message));
  }, []);

  const payments = bookings.filter(
    (booking) =>
      booking.payment_status ||
      booking.payment_method ||
      booking.total_amount
  );

  return (
    <PassengerPage
      eyebrow="PAYMENTS"
      title="Payment history"
      description="Review the payment status attached to your CONNECT journeys."
    >
      {error && <div className="connect-alert connect-alert-error">{error}</div>}

      {!payments.length ? (
        <div className="glass-empty">
          <CreditCard size={28} />
          <strong>No payment history yet.</strong>
          <span>Your completed booking payments will appear here.</span>
        </div>
      ) : (
        <div className="passenger-payment-list">
          {payments.map((payment) => (
            <article
              className="passenger-payment-row"
              key={payment.booking_id}
            >
              <div className="payment-row-icon">
                <CreditCard size={20} />
              </div>

              <div className="payment-row-main">
                <strong>{payment.booking_number}</strong>
                <span>{payment.route_name || 'CONNECT Journey'}</span>
                <small>{payment.payment_method || 'Payment'}</small>
              </div>

              <div className="payment-row-status">
                <span>{payment.payment_status || 'pending'}</span>
                <strong>{money(payment.total_amount)}</strong>
              </div>

              <span className="payment-row-date">
                {date(payment.departure_at)}
              </span>
            </article>
          ))}
        </div>
      )}
    </PassengerPage>
  );
}

export function PassengerProfile() {
  const { user } = useAuth();
  const looksLikePhone = (v) => /^\+?[0-9\s-]{7,}$/.test(String(v || ''));
  const phoneText =
    user?.phone_number ||
    user?.phone ||
    (looksLikePhone(user?.name) ? user.name : null);
  const realName =
    user?.name && !looksLikePhone(user.name) ? user.name : null;
  const displayName = realName || user?.username || 'Passenger';

  return (
    <PassengerPage
      eyebrow="PROFILE"
      title="Your passenger profile"
      description="Your CONNECT account information and passenger identity."
    >
      <div className="profile-glass-card">
        <div className="profile-avatar-large">
          {displayName.charAt(0).toUpperCase()}
        </div>

        <div className="profile-main">
          <span className="glass-eyebrow">PASSENGER ACCOUNT</span>
          <h2>{displayName}</h2>
          <p>{phoneText || 'Phone number not available'}</p>
        </div>
      </div>

      <div className="profile-details-grid">
        <div className="profile-detail">
          <UserRound size={20} />
          <span>Full name</span>
          <strong>{realName || 'Not provided'}</strong>
        </div>

        <div className="profile-detail">
          <UserRound size={20} />
          <span>Username</span>
          <strong>{user?.username || 'Not available'}</strong>
        </div>

        <div className="profile-detail">
          <MapPin size={20} />
          <span>Location</span>
          <strong>{user?.location || 'Not provided'}</strong>
        </div>

        <div className="profile-detail">
          <ShieldCheck size={20} />
          <span>Integrity score</span>
          <strong>
            {user?.integrity_score == null
              ? 'New'
              : `${user.integrity_score}%`}
          </strong>
        </div>
      </div>
    </PassengerPage>
  );
}
