import AppShell from '../../components/layout/AppShell';
import './PassengerRecords.css';
import { useAuth } from '../../context/AuthContext';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { apiRequest } from '../../api';
import { canOpenTripMap } from './liveMapUtils';
import { BUSINESS } from '../../legal/business';
import {
  Armchair,
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
      eyebrow={mode === 'history' ? 'Activity' : 'Receipts'}
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
          aria-label="Search booking number or payment reference"
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
                    Unique trip reference
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
                <h3>Driver</h3>
                {selected.driver ? (
                  <div className="record-info-grid">
                    <span>Name<strong>{selected.driver.name}</strong></span>
                    <span>Bus<strong>{selected.driver.bus_number || '—'}</strong></span>
                    <span>Phone
                      <strong>
                        {selected.driver.phone_number
                          ? <a href={`tel:${selected.driver.phone_number}`}>{selected.driver.phone_number}</a>
                          : 'Shared only on paid trips'}
                      </strong>
                    </span>
                  </div>
                ) : (
                  <p className="muted">No driver was assigned to this trip yet.</p>
                )}
                {selected.driver?.phone_number && (
                  <p className="muted">Left something on the bus? Call the driver with your trip reference.</p>
                )}
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
      eyebrow="Seats"
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
      eyebrow="Help & issues"
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

        <div className="help-glass-card">
          <ShieldCheck size={26} />
          <h3>Contact and policies</h3>
          {(BUSINESS.email || BUSINESS.phone) && (
            <p>
              {BUSINESS.email && <>Email <a className="help-link" href={`mailto:${BUSINESS.email}`}>{BUSINESS.email}</a>{BUSINESS.phone && ' or '}</>}
              {BUSINESS.phone && <>call <a className="help-link" href={`tel:${BUSINESS.phone.replace(/\s/g, '')}`}>{BUSINESS.phone}</a></>}
              {' '}with your reference.
            </p>
          )}
          <p>
            Read the <Link className="help-link" to="/legal/refunds">refund policy</Link>,{' '}
            <Link className="help-link" to="/legal/terms">terms</Link> and{' '}
            <Link className="help-link" to="/legal/privacy">privacy policy</Link>.
          </p>
        </div>
      </div>
    </PassengerPage>
  );
}

const lower = (v) => String(v || '').toLowerCase();
const timeOnly = (v) => (v ? new Date(v).toLocaleTimeString('en-KE', { hour: '2-digit', minute: '2-digit' }) : '');
const live = (b) => ['pending', 'confirmed'].includes(lower(b.status)) && lower(b.trip_status) === 'scheduled';

// What a passenger can still do with a booking. Mirrors the backend rules:
// passengers may cancel only before boarding starts, and may change bus only
// until the change cut-off (15 min before departure, from the server).
function bookingActions(b) {
  const status = lower(b.status);
  const trip = lower(b.trip_status);
  const pay = lower(b.payment_status);
  const live = ['pending', 'confirmed'].includes(status);
  return {
    pay: status === 'pending' && trip !== 'departed' && pay !== 'confirmed'
      && !(lower(b.payment_method) === 'cash' && pay === 'pending'),
    cancel: live && trip === 'scheduled',
    change: live && b.can_change === true,
    track: canOpenTripMap(b),
  };
}

function BookingsBody({ activeOnly = false }) {
  const navigate = useNavigate();
  const [bookings, setBookings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busyId, setBusyId] = useState(null);

  const load = useCallback(() => apiRequest('/bookings/my/')
    .then((data) => setBookings(Array.isArray(data) ? data : []))
    .catch((e) => setError(e.message))
    .finally(() => setLoading(false)), []);

  useEffect(() => { load(); }, [load]);

  const [changing, setChanging] = useState(null); // { booking, trips }

  const openChange = async (b) => {
    setError('');
    setBusyId(b.booking_id);
    try {
      const trips = await apiRequest(`/companies/${b.company_id}/trips/?route_id=${b.route_id}`);
      const options = (Array.isArray(trips) ? trips : [])
        .filter((t) => t.id !== b.trip_id
          && (Number(t.capacity) - Number(t.booked_seats || 0)) >= Number(b.seats || 1))
        .sort((x, y) => new Date(x.departure_at) - new Date(y.departure_at));
      setChanging({ booking: b, trips: options });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusyId(null);
    }
  };

  const moveTo = async (trip) => {
    const b = changing.booking;
    setBusyId(b.booking_id);
    setError('');
    try {
      await apiRequest(`/bookings/${b.booking_id}/move-trip/`, { method: 'POST', body: { trip_id: trip.id } });
      setNotice(`Moved to the ${timeOnly(trip.departure_at)} bus. Same seat count, same fare.`);
      setChanging(null);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusyId(null);
    }
  };

  const cancel = async (b) => {
    const paid = lower(b.payment_status) === 'confirmed' && lower(b.payment_method) !== 'cash';
    const warning = !paid
      ? 'Cancel this booking? Nothing has been charged.'
      : b.can_change
        ? `Cancel this booking? You get a full refund because the bus leaves after ${timeOnly(b.change_cutoff_at)}.`
        : 'Cancel this booking? The bus leaves in under 15 minutes, so you will be refunded 50% of the fare.';
    if (!window.confirm(warning)) return;
    setBusyId(b.booking_id);
    setError('');
    try {
      const res = await apiRequest(`/bookings/${b.booking_id}/cancel/`, { method: 'POST', body: {} });
      setNotice(res?.message || 'Booking cancelled.');
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusyId(null);
    }
  };

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
      {notice && <div className="connect-alert" role="status">{notice}</div>}

      {loading ? (
        <div className="glass-empty">Loading your bookings…</div>
      ) : !visible.length ? (
        <div className="glass-empty">
          <strong>No bookings yet.</strong>
          <span>Trips you book show up here, with live tracking once the bus is on the road.</span>
          <Link to="/passenger/schedules" className="glass-empty-action">Find a trip</Link>
        </div>
      ) : (
        <div className="passenger-data-grid">
          {visible.map((booking) => (
            <article className="passenger-data-card" key={booking.booking_id}>
              <div className="data-card-top">
                <div>
                  <span className="data-card-label">Booking</span>
                  <strong>{booking.booking_number}</strong>
                </div>

                <span className="passenger-status">
                  {booking.status}
                </span>
              </div>

              <h2>{booking.route_name || 'CONNECT Journey'}</h2>

              <div className="data-card-details">
                <span><Armchair size={14} aria-hidden="true" /> {booking.seat_numbers?.length
                  ? `Seat${booking.seat_numbers.length === 1 ? '' : 's'} ${booking.seat_numbers.join(', ')}`
                  : `${booking.seats} seat${booking.seats === 1 ? '' : 's'}`}</span>
                <span><MapPin size={14} aria-hidden="true" /> {booking.pickup_location}</span>
                <span><CreditCard size={14} aria-hidden="true" /> {booking.payment_status}</span>
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

              {(() => {
                const can = bookingActions(booking);
                if (!can.pay && !can.cancel && !can.track) return null;
                const picking = changing?.booking.booking_id === booking.booking_id;
                const busy = busyId === booking.booking_id;
                return (
                  <div className="data-card-actions">
                    {can.pay && (
                      <button type="button" className="btn btn-primary"
                        onClick={() => navigate(`/passenger?pay=${booking.booking_id}`)}>
                        Pay now
                      </button>
                    )}
                    {can.track && (
                      <button type="button" className="btn btn-primary"
                        onClick={() => navigate(`/passenger/map?booking=${booking.booking_id}`)}>
                        Open map
                      </button>
                    )}
                    {can.change && !picking && (
                      <button type="button" className="btn btn-ghost" disabled={busy}
                        onClick={() => openChange(booking)}>
                        Change bus
                      </button>
                    )}
                    {can.cancel && (
                      <button type="button" className="btn btn-ghost" disabled={busy}
                        onClick={() => cancel(booking)}>
                        {busy ? 'Working…' : 'Cancel booking'}
                      </button>
                    )}
                    {live(booking) && (
                      <p className="change-note">
                        {booking.can_change
                          ? `Free to cancel or change bus until ${timeOnly(booking.change_cutoff_at)}.`
                          : 'Your seat is locked to this bus. Cancelling now refunds 50%.'}
                      </p>
                    )}
                    {picking && (
                      <div className="change-picker">
                        <strong>Pick another bus on {booking.route_name}</strong>
                        {changing.trips.length === 0 ? (
                          <span>No other bus on this route has {booking.seats} free seat{booking.seats === 1 ? '' : 's'} right now.</span>
                        ) : changing.trips.map((t) => (
                          <button type="button" key={t.id} className="btn btn-secondary" disabled={busy}
                            onClick={() => moveTo(t)}>
                            {date(t.departure_at)} · {Number(t.capacity) - Number(t.booked_seats || 0)} free
                          </button>
                        ))}
                        <button type="button" className="btn btn-ghost" onClick={() => setChanging(null)}>Keep my bus</button>
                      </div>
                    )}
                  </div>
                );
              })()}
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
      eyebrow="My bookings"
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
      eyebrow="Wallet"
      title="Your CONNECT wallet"
      description="Manage the balance used for your protected journey payments."
    >
      {error && <div className="connect-alert connect-alert-error">{error}</div>}

      <div className="wallet-overview-grid">
        <div className="wallet-glass-card wallet-main">
          <WalletCards size={26} />
          <span>Available balance</span>
          <strong>{money(wallet?.available_balance)}</strong>
          <p>Available for new bookings.</p>
        </div>

        <div className="wallet-glass-card">
          <ShieldCheck size={24} />
          <span>Held balance</span>
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
      eyebrow="Payments"
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

function CloseAccount() {
  const { closeAccount } = useAuth();
  const navigate = useNavigate();
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    if (!window.confirm('Delete your CONNECT account? You will be signed out and cannot undo this.')) return;
    setError('');
    setBusy(true);
    try {
      await closeAccount(password);
      navigate('/', { replace: true });
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return (
    <section className="close-account" aria-labelledby="close-account-title">
      <h2 id="close-account-title">Close account</h2>
      <p>
        Removes your name, phone number and password. Booking and payment records are kept without them, as the law
        requires. <Link to="/legal/delete-account">What is kept and why</Link>
      </p>
      {error && <div className="error" role="alert">{error}</div>}
      <form onSubmit={submit} className="form-stack">
        <label>
          Your password, to confirm it is you
          <input type="password" className="input" autoComplete="current-password" value={password}
            onChange={(e) => setPassword(e.target.value)} required />
        </label>
        <button className="btn btn-danger" disabled={busy || !password}>
          {busy ? 'Deleting account…' : 'Delete my account'}
        </button>
      </form>
    </section>
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
      eyebrow="Profile"
      title="Your passenger profile"
      description="Your CONNECT account information and passenger identity."
    >
      <div className="profile-glass-card">
        <div className="profile-avatar-large">
          {displayName.charAt(0).toUpperCase()}
        </div>

        <div className="profile-main">
          <span className="glass-eyebrow">Passenger account</span>
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

      <CloseAccount />
    </PassengerPage>
  );
}
