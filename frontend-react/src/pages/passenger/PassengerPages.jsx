import AppShell from '../../components/layout/AppShell';
import './PassengerRecords.css';
import { useAuth } from '../../context/AuthContext';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { apiRequest } from '../../api';
import AsyncPanel from '../../components/ui/AsyncPanel';
import PayCountdown from '../../components/ui/PayCountdown';
import useAsyncData from '../../hooks/useAsyncData';
import { formatMoney as money } from '../../utils/money';
import { deriveStatus } from '../../utils/loadStatus';
import { canOpenTripMap } from './liveMapUtils';
import { TopUpForm, TopUpReturn, WalletHistory } from './WalletPanels';
import WithdrawPanel from './WithdrawPanel';
import { cancelWarning } from '../../utils/wallet';
import { statusGroup } from '../../utils/statusChip';
import StatusIcon from '../../components/ui/StatusIcon';
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
  const [records, setRecords] = useState(null);
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState(null);

  const load = async (value = '') => {
    setLoading(true);
    setError('');
    setRecords(null);
    try {
      const suffix = value
        ? `?search=${encodeURIComponent(value)}`
        : '';
      const data = await apiRequest(`/bookings/records/${suffix}`, { silent: true });
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
    if (!records) return [];
    if (mode === 'history') return records;
    return records.filter((r) => r.payment?.exists);
  }, [records, mode]);
  const status = deriveStatus({ loading, error, hasData: records !== null });

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

      <AsyncPanel status={status} title="your records" loadingText="Loading your records…" onRetry={() => load(query)}>
      {!visible.length ? (
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
      </AsyncPanel>
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
      </div>
    </PassengerPage>
  );
}

const lower = (v) => String(v || '').toLowerCase();

// What a passenger can still do with a booking. Mirrors the backend rules:
// passengers may cancel only before boarding starts; a cash booking waits
// for the driver to confirm payment.
function bookingActions(b) {
  const status = lower(b.status);
  const trip = lower(b.trip_status);
  const pay = lower(b.payment_status);
  const live = ['pending', 'confirmed'].includes(status);
  return {
    pay: status === 'pending' && trip !== 'departed' && pay !== 'confirmed'
      && !(lower(b.payment_method) === 'cash' && pay === 'pending'),
    cancel: live && trip === 'scheduled',
    track: canOpenTripMap(b),
  };
}

function BookingsBody({ activeOnly = false }) {
  const navigate = useNavigate();
  const { status, data, reload: load } = useAsyncData(
    () => apiRequest('/bookings/my/', { silent: true }).then((d) => (Array.isArray(d) ? d : [])),
  );
  const bookings = data || [];
  // Cancel failures are action errors; they never replace the loaded list.
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busyId, setBusyId] = useState(null);

  const cancel = async (b) => {
    const warning = cancelWarning(b);
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
      {error && <div className="connect-alert connect-alert-error" role="alert">{error}</div>}
      {notice && <div className="connect-alert" role="status">{notice}</div>}

      <AsyncPanel status={status} title="your bookings" loadingText="Loading your bookings…" onRetry={load}>
      {!visible.length ? (
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

                <span className="passenger-status" data-status={statusGroup(booking.status)}>
                  <StatusIcon group={statusGroup(booking.status)} />
                  {booking.status}
                </span>
              </div>

              <h2>{booking.route_name || 'CONNECT Journey'}</h2>

              <div className="data-card-details">
                <span><Armchair size={14} aria-hidden="true" /> {booking.seats} seat{booking.seats === 1 ? '' : 's'}</span>
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

              {lower(booking.status) === 'pending' && <PayCountdown payBefore={booking.pay_before} />}

              {(() => {
                const can = bookingActions(booking);
                if (!can.pay && !can.cancel && !can.track) return null;
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
                    {can.cancel && (
                      <button type="button" className="btn btn-ghost" disabled={busy}
                        onClick={() => cancel(booking)}>
                        {busy ? 'Cancelling…' : 'Cancel booking'}
                      </button>
                    )}
                  </div>
                );
              })()}
            </article>
          ))}
        </div>
      )}
      </AsyncPanel>
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
  const [params, setParams] = useSearchParams();
  const reference = params.get('reference');
  const { status, data: wallet, reload } = useAsyncData(
    () => apiRequest('/wallet/', { silent: true }),
  );
  const history = useAsyncData(
    () => apiRequest('/wallet/transactions/', { silent: true }).then((d) => (Array.isArray(d) ? d : [])),
  );
  // Until the wallet loaded no number is shown, never a made-up KES 0.00.
  const ready = status === 'ready';
  const reloadHistory = history.reload;
  const onCredited = useCallback(() => { reload(); reloadHistory(); }, [reload, reloadHistory]);

  return (
    <PassengerPage
      eyebrow="Wallet"
      title="Your CONNECT wallet"
      description="Top up with M-PESA and pay for bookings from your balance."
    >
      {reference && (
        <TopUpReturn
          reference={reference}
          onCredited={onCredited}
          onDone={() => setParams({}, { replace: true })}
        />
      )}

      {status === 'error' ? (
        <AsyncPanel status="error" title="your wallet" onRetry={reload} />
      ) : (
      <div className="wallet-overview-grid" aria-busy={!ready}>
        <div className="wallet-glass-card wallet-main">
          <WalletCards size={26} />
          <span>Available balance</span>
          <strong>{money(ready ? wallet?.available_balance : undefined)}</strong>
          <p>Use it to pay for a booking. Refunds for bookings paid from the wallet come back here.</p>
        </div>
      </div>
      )}

      <TopUpForm />

      <WithdrawPanel balance={ready ? wallet?.available_balance : undefined} onChanged={onCredited} />

      <WalletHistory status={history.status} rows={history.data} onRetry={history.reload} />
    </PassengerPage>
  );
}

export function PassengerPayments() {
  const { status, data, reload } = useAsyncData(
    () => apiRequest('/bookings/my/', { silent: true }).then((d) => (Array.isArray(d) ? d : [])),
  );
  const bookings = data || [];

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
      <AsyncPanel status={status} title="your payments" loadingText="Loading your payments…" onRetry={reload}>
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
      </AsyncPanel>
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
    </PassengerPage>
  );
}
