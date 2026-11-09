import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Armchair, ArrowUpRight, Banknote, Bus, Check, CreditCard, MapPin, Package, Smartphone } from 'lucide-react';

import { apiRequest } from '../../api';
import { useAuth } from '../../context/AuthContext';
import { canOpenTripMap, isActiveBooking } from './liveMapUtils';
import AppShell from '../../components/layout/AppShell';
import Notice, { NoticeStack } from '../../components/ui/Notice';
import './PassengerHomeRedesign.css';
import PassengerLiveMap from './PassengerLiveMap';
import bookSeatImage from '../../assets/journeys/bookaseat.jpeg';
import deliveryImage from '../../assets/journeys/orderdelivery.jpeg';
import bookBusImage from '../../assets/journeys/bookabus.jpeg';
import supermetroImage from '../../assets/companies/supermetro.jpeg';
import cityshuttleImage from '../../assets/companies/cityshuttle.jpeg';
import latemaImage from '../../assets/companies/latema.jpeg';

const money = (v) => `KES ${Number(v || 0).toLocaleString('en-KE',{minimumFractionDigits:2,maximumFractionDigits:2})}`;
const date = (v) => v ? new Date(v).toLocaleString('en-KE',{dateStyle:'medium',timeStyle:'short'}) : 'Not scheduled';

function Shell({ children }) {
  return <AppShell>{children}</AppShell>;
}

function PaymentModal({
  booking,
  onClose,
  onPaid,
  onPaymentConfirmed,
  onCashReserved,
}) {
  const [step, setStep] = useState('method');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [mpesaPhone, setMpesaPhone] = useState('');
  const { user } = useAuth();
  // Cash is off at launch (backend CASH_ENABLED); later only for proven riders.
  // The server enforces both, this only decides what to show.
  const cashEnabled = Boolean(user?.cash_enabled);
  const cashLocked = !user?.can_pay_cash;
  const cashLockedReason = 'For regular riders only: 30 trips, an integrity score of 95% or more and an account at least 60 days old.';

  const cash = async () => {
    setBusy(true);
    setError('');
    try {
      await apiRequest(`/bookings/payments/${booking.booking_id}/cash/`, {
        method: 'POST',
      });
      setStep('cash-success');
      onPaid();
      onCashReserved({
        ...booking,
        status: 'pending',
        payment_method: 'cash',
        payment_status: 'pending',
      });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const mpesa = async (phoneNumber) => {
    setBusy(true); setError('');
    try {
      const data = await apiRequest(`/bookings/payments/${booking.booking_id}/mpesa/`, {
        method:'POST',
        body:{phone_number:phoneNumber}
      });
      setMessage(data.display_text || 'Check your phone and complete the M-PESA prompt.');
      setStep('mpesa-wait');
    } catch(e){setError(e.message)} finally{setBusy(false)}
  };

  const card = async () => {
    setBusy(true); setError('');
    try {
      const data = await apiRequest(`/bookings/payments/${booking.booking_id}/paystack/`, {
        method:'POST', body:{callback_url:`${window.location.origin}/passenger/payment/${booking.booking_id}`}
      });
      window.location.href = data.authorization_url;
    } catch(e){setError(e.message);setBusy(false)}
  };

  useEffect(() => {
    if (step !== 'mpesa-wait') return undefined;
    let active = true; let attempts = 0;
    const poll = async () => {
      attempts += 1;
      try {
        const status = await apiRequest(`/bookings/payments/${booking.booking_id}/status/`);
        if (!active) return;
        setError('');
        if (status.payment_status === 'confirmed') { onPaymentConfirmed(booking); return; }
        if (status.payment_status === 'failed') { setError('The M-PESA payment failed. You can try again.'); setStep('method'); return; }
      } catch (error) {
        if (!active) return;
        setError(error.message || 'We could not check your M-PESA payment. Try again.');
      }
      if (active && attempts < 60) window.setTimeout(poll, 3000);
      else if (active) setMessage('Still waiting for Paystack. You can refresh the status or close this window and check your bookings.');
    };
    poll();
    return () => { active = false; };
  }, [step, booking.booking_id, onPaid, onPaymentConfirmed]);

  const verify = async () => {
    setBusy(true); setError('');
    try { const data = await apiRequest(`/bookings/payments/${booking.booking_id}/verify/`, {method:'POST'}); if(data.payment_status==='confirmed'){onPaymentConfirmed(booking);} else setMessage(data.message || 'Payment is still pending.'); }
    catch(e){setError(e.message)} finally{setBusy(false)}
  };

  // Rendered on the body: an animated page section would otherwise anchor this
  // "fixed" window to itself, leaving it down the page instead of on screen.
  return createPortal(<div className="modal-backdrop"><div className="modal">
    <button className="btn btn-ghost modal-close" onClick={onClose}>Close</button>
    <p className="eyebrow">Booking {booking.booking_number}</p>
    <h2>{money(booking.total_amount)}</h2>{step!=='mpesa-number' && <p className="muted">Choose how you want to complete this trip.</p>}
    {error && (
      <NoticeStack>
        <Notice title="Payment issue" onClose={() => setError('')}>
          {error}
        </Notice>
      </NoticeStack>
    )}
    {step==='method' && <div className="stack" style={{marginTop:18}}>
      <button className="pay-option" onClick={()=>setStep('online')} disabled={busy}><div className="pay-icon"><CreditCard size={20} aria-hidden="true" /></div><div><strong>Pay online</strong><span>Choose M-PESA or Card securely through Paystack.</span></div></button>
      {cashEnabled && <button className="pay-option" onClick={cash} disabled={busy || cashLocked} aria-describedby="cash-note"><div className="pay-icon"><Banknote size={20} aria-hidden="true" /></div><div><strong>Pay cash on board</strong><span id="cash-note">{cashLocked ? cashLockedReason : 'Get your PIN now, track the bus, and pay the driver when you board.'}</span></div></button>}
    </div>}
    {step==='online' && <div className="stack" style={{marginTop:18}}>
      <button className="pay-option" onClick={()=>setStep('mpesa-number')} disabled={busy}><div className="pay-icon"><Smartphone size={20} aria-hidden="true" /></div><div><strong>M-PESA</strong><span>Choose which phone number will receive the payment prompt.</span></div></button>
      <button className="pay-option" onClick={card} disabled={busy}><div className="pay-icon"><CreditCard size={20} aria-hidden="true" /></div><div><strong>Card</strong><span>Secure Paystack checkout. Card authentication stays with Paystack.</span></div></button>
      <button className="btn btn-ghost" onClick={()=>setStep('method')}>← Back</button>
    </div>}
    {step==='mpesa-number' && <div style={{marginTop:10}}>
      <button
        className="pay-option"
        onClick={()=>mpesa('')}
        disabled={busy}
        type="button"
      >
        <div className="pay-icon"><Smartphone size={20} aria-hidden="true" /></div>
        <div>
          <strong>Pay with my number</strong>
          <span>Use the phone number saved on your CONNECT account.</span>
        </div>
      </button>

      <div style={{marginTop:10,padding:12,border:'1px solid #ddd',borderRadius:12}}>
        <strong>Pay with another number</strong>
        <p className="muted" style={{marginTop:6}}>
          Enter the M-PESA number you want to use.
        </p>

        <input
          type="tel"
          value={mpesaPhone}
          onChange={(e)=>setMpesaPhone(e.target.value)}
          placeholder="+254710000000"
          autoComplete="tel"
          inputMode="tel"
          style={{
            display:'block',
            width:'100%',
            boxSizing:'border-box',
            padding:'12px',
            marginTop:10,
            border:'1px solid #aaa',
            borderRadius:8,
            background:'#fff',
            color:'#111',
            pointerEvents:'auto'
          }}
        />

        <button
          className="btn btn-primary"
          type="button"
          style={{width:'100%',marginTop:12}}
          disabled={busy || !mpesaPhone.trim()}
          onClick={()=>mpesa(mpesaPhone.trim())}
        >
          {busy ? 'Starting…' : 'Proceed'}
        </button>
      </div>

      <button
        className="btn btn-ghost"
        type="button"
        onClick={()=>setStep('online')}
        disabled={busy}
        style={{marginTop:12}}
      >
        ← Back
      </button>
    </div>}

    {step==='mpesa-wait' && <div className="payment-status"><div className="payment-spinner"/><h3>Check your phone</h3><p className="muted">{message}</p><p className="mobile-note">Authorize the M-PESA prompt on the phone that received it.</p><button className="btn btn-secondary" onClick={verify} disabled={busy}>{busy?'Checking…':'Check payment status'}</button></div>}
    {step==='cash-success' && <div className="success">Seat held. Your boarding PIN is on your trip card now. Track the bus, then pay the driver in cash and show your PIN when you board.</div>}
  </div></div>, document.body);
}


function LiveTripModal({ booking, onClose }) {
  return (
    <PassengerLiveMap
      bookingId={booking.booking_id || booking.id}
      bookingDetails={booking}
      routeGeometry={booking.route_geometry}
      pickup={{
        latitude: booking.pickup_latitude,
        longitude: booking.pickup_longitude,
        name:
          booking.pickup_stage_name ||
          booking.pickup_location ||
          'Pickup stage',
      }}
      onBack={onClose}
    />
  );
}

const JOURNEY_MODES = ['seat'];

const toSearch = (j, initialStep) => {
  const p = new URLSearchParams();
  if (j.step && j.step !== initialStep) p.set('step', j.step);
  if (j.mode) p.set('mode', j.mode);
  if (j.company) p.set('company', j.company);
  if (j.route) p.set('route', j.route);
  const q = p.toString();
  return q ? `?${q}` : '';
};

const fromSearch = (search, initialStep) => {
  const p = new URLSearchParams(search);
  const digits = (v) => (/^\d+$/.test(v || '') ? v : '');
  const mode = p.get('mode');
  return {
    step: p.get('step') || initialStep,
    mode: JOURNEY_MODES.includes(mode) ? mode : '',
    company: digits(p.get('company')),
    route: digits(p.get('route')),
  };
};

const dayLabel = (key) =>
  new Date(`${key}T00:00:00`).toLocaleDateString('en-KE', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  });

export default function PassengerDashboard({ initialJourneyStep = 'home' }) {
  const navigate = useNavigate();
  const location = useLocation();
  const urlJourney = fromSearch(location.search, initialJourneyStep);
  const [companies,setCompanies]=useState([]),[routes,setRoutes]=useState([]),[trips,setTrips]=useState([]);
  const [selectedDate, setSelectedDate] = useState(() => {
    const now = new Date();
    return new Date(now.getTime() - now.getTimezoneOffset() * 60000)
      .toISOString()
      .slice(0, 10);
  });
  const [nextTripDate,setNextTripDate]=useState(null),[tripsLoading,setTripsLoading]=useState(false);
  const [bookings,setBookings]=useState([]);
  const [trackingBooking,setTrackingBooking]=useState(null);
  const [company,setCompany]=useState(urlJourney.company),[route,setRoute]=useState(urlJourney.route);
  const [bookingTrip,setBookingTrip]=useState(null),[seats,setSeats]=useState(1);
  const [selectedStage,setSelectedStage]=useState(null);
  const [otherPickup,setOtherPickup]=useState('');
  const [paymentBooking,setPaymentBooking]=useState(null),[loading,setLoading]=useState(false),[error,setError]=useState(''),[success,setSuccess]=useState('');

  const refresh = useCallback(async()=>{
    try {
      const [bookingData] = await Promise.all([
        apiRequest("/bookings/my/"),
        apiRequest("/wallet/")
      ]);

      setBookings(Array.isArray(bookingData) ? bookingData : []);
    } catch(e) {
      setError(e.message);
    }
  },[]);
  const handleBookingMapEntry = useCallback((booking = paymentBooking) => {
    const bookingId = booking?.booking_id ?? booking?.id;

    if (!bookingId) {
      setError('Your booking was saved, but its trip link is unavailable. Open My Trips to find it.');
      setPaymentBooking(null);
      return;
    }

    setPaymentBooking(null);
    // Leaving the map (back arrow or phone back) should land on the overview
    // with My trips, not on the booking step this payment came from.
    navigate('/passenger', { replace: true });
    navigate(`/passenger/map?booking=${encodeURIComponent(bookingId)}`, {
      state: { booking, backToOverview: true },
    });
  }, [navigate, paymentBooking]);

  useEffect(()=>{apiRequest('/companies/').then(d=>setCompanies(Array.isArray(d)?d:[])).catch(e=>setError(e.message));refresh()},[refresh]);
  useEffect(()=>{if(!company){setRoutes([]);setTrips([]);return} apiRequest(`/companies/${company}/routes/`).then(d=>setRoutes(d||[])).catch(e=>setError(e.message))},[company]);
  useEffect(() => {
    if (!company) {
      setTrips([]);
      return;
    }

    let active = true;
    setTrips([]);
    setNextTripDate(null);
    setTripsLoading(true);
    setError('');

    const params = new URLSearchParams();
    if (route) params.set('route_id', route);
    if (selectedDate) params.set('date', selectedDate);
    const query = params.toString();
    apiRequest(`/companies/${company}/trips/${query ? `?${query}` : ''}`)
      .then(async (data) => {
        const list = Array.isArray(data) ? data : [];
        if (!active) return;
        setTrips(list);
        if (list.length || !route) return;
        // Nothing on this date: find the route's next departure so the
        // passenger has somewhere to go instead of a dead end.
        const all = await apiRequest(`/companies/${company}/trips/?route_id=${route}`);
        const now = Date.now();
        const next = (Array.isArray(all) ? all : [])
          .filter((t) => ['scheduled', 'boarding'].includes(String(t.status).toLowerCase())
            && new Date(t.departure_at).getTime() > now)
          .sort((a, b) => new Date(a.departure_at) - new Date(b.departure_at))[0];
        if (active && next) {
          const d = new Date(next.departure_at);
          setNextTripDate(new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10));
        }
      })
      .catch((error) => {
        if (active) setError(error.message);
      })
      .finally(() => {
        if (active) setTripsLoading(false);
      });

    return () => {
      active = false;
    };
  }, [company, route, selectedDate]);

  // Cash bookings stay pending until the driver checks the PIN on board. Poll
  // so the trip card flips to boarded without a manual reload.
  const awaitingCash = bookings.some((b) => (
    b.payment_method === 'cash'
    && b.payment_status === 'pending'
    && !['cancelled', 'completed', 'no_show'].includes(String(b.status || '').toLowerCase())
  ));
  useEffect(() => {
    if (!awaitingCash) return undefined;
    const id = window.setInterval(() => {
      if (!document.hidden) refresh();
    }, 5000);
    return () => window.clearInterval(id);
  }, [awaitingCash, refresh]);

  const selectedRoute=useMemo(()=>routes.find(r=>String(r.id)===String(route)),[routes,route]);
  const firstStageId=(selectedRoute?.pickup_stages||[]).filter(st=>st.is_active!==false)[0]?.id;
  const seatsLeft=(t)=>Math.max(0,(t.capacity||0)-(t.booked_seats||0));
  const canBookTrip=(t)=>seatsLeft(t)>0&&(t.status==='scheduled'||(t.status==='boarding'&&selectedStage&&String(selectedStage.id)===String(firstStageId)));
  const tripButtonLabel=(t)=>{
    if(seatsLeft(t)<=0) return 'Fully booked';
    if(canBookTrip(t)) return 'Select trip';
    if(t.status==='boarding') return 'Boarding at first stage only';
    return 'Unavailable';
  };
  const startBooking=(trip)=>{setError('');setBookingTrip(trip);setSeats(1)};
  const createBooking=async()=>{
    const manualPickup = otherPickup.trim();

    if (!selectedStage && !manualPickup) {
      setError('Select a pickup stage or choose Other and enter your pickup location.');
      return;
    }

    setLoading(true);
    setError('');

    try {
      const body = {
        trip_id: bookingTrip.id,
        seats: Number(seats),
      };

      if (selectedStage) {
        body.pickup_stage_id = Number(selectedStage.id);
      } else {
        body.pickup_location = manualPickup;
      }

      const b = await apiRequest('/bookings/create/', {
        method: 'POST',
        body
      });

      setBookingTrip(null);
      setSelectedStage(null);
      setOtherPickup('');
      await refresh();

      setPaymentBooking({
        ...b,
        booking_id: b.booking_id ?? b.id,
        booking_number: b.booking_number,
        total_amount: b.total_amount
      });
    } catch(e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const [journeyStep, setJourneyStep] = useState(urlJourney.step);

  // "Pay now" from My bookings lands here as ?pay=<booking id>. Read it once:
  // the journey URL sync below rewrites the query string.
  const payRequest = useRef(new URLSearchParams(location.search).get('pay'));
  useEffect(() => {
    const id = payRequest.current;
    if (!id) return;
    const b = bookings.find((x) => String(x.booking_id) === id);
    if (!b) return;
    payRequest.current = null;
    setPaymentBooking({ ...b, booking_id: b.booking_id });
  }, [bookings]);
  const [journeyMode, setJourneyMode] = useState(urlJourney.mode);

  const locationRef = useRef(location);
  const baseIdx = useRef(window.history.state?.idx ?? 0);
  useEffect(() => { locationRef.current = location; });

  // Browser back/forward: restore the journey from the URL.
  useEffect(() => {
    const j = fromSearch(location.search, initialJourneyStep);
    setJourneyStep(j.step);
    setJourneyMode(j.mode);
    setCompany(j.company);
    setRoute(j.route);
  }, [location.pathname, location.search]);

  // Each journey step becomes a history entry.
  useEffect(() => {
    const target = toSearch(
      { step: journeyStep, mode: journeyMode, company, route },
      initialJourneyStep
    );
    const current = locationRef.current;
    if (target !== current.search) {
      navigate({ pathname: current.pathname, search: target });
    }
  }, [journeyStep, journeyMode, company, route]);

  const selectedCompany = useMemo(
    () => companies.find((c) => String(c.id) === String(company)),
    [companies, company]
  );

  const chooseJourney = (mode) => {
    setError('');
    setSuccess('');
    setJourneyMode(mode);
    setCompany('');
    setRoute('');
    setRoutes([]);
    setTrips([]);
    setSelectedStage(null);
    setOtherPickup('');
    setJourneyStep('companies');
  };

  const chooseCompany = (id) => {
    setError('');
    setCompany(String(id));
    setRoute('');
    setJourneyStep('routes');
  };

  const chooseRoute = (id) => {
    setError('');
    setRoute(String(id));
    setSelectedStage(null);
    setOtherPickup('');
    setTrips([]);
    setJourneyStep('stages');
  };

  const chooseStage = (stage) => {
    setError('');
    setSelectedStage(stage);
    setOtherPickup('');
    setJourneyStep('trips');
  };

  // The pickup stage lives only in memory: after a reload on the trips step
  // it is gone and booking would fail, so send the passenger to pick it again.
  useEffect(() => {
    if (journeyStep === 'trips' && route && !selectedStage && !otherPickup.trim()) {
      setJourneyStep('stages');
    }
  }, [journeyStep, route, selectedStage, otherPickup]);

  const goBack = () => {
    setError('');

    // A real history entry exists for the previous step: use it.
    if ((window.history.state?.idx ?? 0) > baseIdx.current) {
      navigate(-1);
      return;
    }

    if (journeyStep === 'companies') {
      setJourneyMode('');
      setCompany('');
      setRoute('');
      setRoutes([]);
      setTrips([]);
      setJourneyStep('home');
      return;
    }

    if (journeyStep === 'routes') {
      setCompany('');
      setRoute('');
      setRoutes([]);
      setTrips([]);
      setJourneyStep('companies');
      return;
    }

    if (journeyStep === 'trips') {
      setRoute('');
      setTrips([]);
      setJourneyStep('routes');
    }
  };

  return <Shell>
    <div className="passenger-experience">

      <NoticeStack>
        {error && (
          <Notice title="Something went wrong" onClose={() => setError('')}>
            {error}
          </Notice>
        )}

        {success && (
          <Notice kind="success" title="Done" autoHideMs={8000} onClose={() => setSuccess('')}>
            {success}
          </Notice>
        )}
      </NoticeStack>

      {/* =====================================================
          STEP 1 — PASSENGER HOME
          ===================================================== */}

      {journeyStep === 'home' && (
        <section className="passenger-home">
          <div className="passenger-welcome">
            <div>
              <span className="glass-eyebrow">CONNECT matatu booking</span>
              <h1>Where are you<br />going today?</h1>
              <p>
                Choose how you want to travel and we'll guide you
                through the journey.
              </p>
            </div>

          </div>

          <div className="journey-choice-grid">

            <button
              type="button"
              className="journey-choice"
              onClick={() => chooseJourney('seat')}
            >
              <div className="journey-choice-image journey-seat-image" style={{ backgroundImage: `url(${bookSeatImage})` }}>
                <div className="journey-image-overlay" />
                <span className="journey-icon"><Armchair size={18} aria-hidden="true" /></span>
              </div>

              <div className="journey-choice-content">
                <h2>Book a seat</h2>
                <p>
                  Find an available departure and reserve your seat
                  quickly.
                </p>
                <span className="journey-arrow">Find a trip</span>
              </div>
            </button>

            <button
              type="button"
              className="journey-choice"
              onClick={() => navigate('/passenger/delivery')}
            >
              <div className="journey-choice-image journey-travel-image" style={{ backgroundImage: `url(${deliveryImage})` }}>
                <div className="journey-image-overlay" />
                <span className="journey-icon"><Package size={18} aria-hidden="true" /></span>
              </div>

              <div className="journey-choice-content">
                <h2>Send a parcel</h2>
                <p>
                  Send a parcel safely through the CONNECT transport network.
                </p>
                <span className="journey-arrow">Send a parcel</span>
              </div>
            </button>

            <button
              type="button"
              className="journey-choice"
              onClick={() => navigate('/passenger/charter')}
            >
              <div className="journey-choice-image journey-bus-image" style={{ backgroundImage: `url(${bookBusImage})` }}>
                <div className="journey-image-overlay" />
                <span className="journey-icon"><Bus size={18} aria-hidden="true" /></span>
              </div>

              <div className="journey-choice-content">
                <h2>Hire a bus</h2>
                <p>
                  Reserve a whole bus for groups, events and private travel.
                </p>
                <span className="journey-arrow">Request a bus</span>
              </div>
            </button>

          </div>

          <section
            className="journey-section"
            style={{ marginTop: 28 }}
          >
            <div className="journey-heading">
              <span className="glass-eyebrow">My trips</span>
              <h2>Upcoming and active bookings</h2>
              <p>
                View your confirmed trips and track an assigned bus when live
                location is available.
              </p>
            </div>

            {!bookings.some(isActiveBooking) ? (
              <div className="glass-empty">
                <span>No upcoming trips. Choose Book a seat above to find one.</span>
              </div>
                ) : (
                  <div className="modern-trip-list">
                {bookings
                  .filter(isActiveBooking)
                  .slice(0, 5)
                  .map((b) => (
                    <article
                      className="modern-trip-card"
                      key={b.booking_id}
                    >
                      <div className="trip-time-block">
                        <span>Trip</span>
                        <strong>{b.booking_number}</strong>
                        <small>{date(b.departure_at)}</small>
                        {b.verification_pin && (
                          <small>
                            Boarding PIN{' '}
                            <strong style={{ letterSpacing: '0.2em', fontSize: '1.4em' }}>
                              {b.verification_pin}
                            </strong>
                          </small>
                        )}
                      </div>

                      <div className="trip-route-visual">
                        <div className="trip-route-line">
                          <span />
                          <i />
                          <span />
                        </div>

                        <div>
                          <strong>
                            {b.route_name || 'Transport route'}
                          </strong>
                          <p>
                            {b.company_name || 'Transport company'}
                          </p>
                        </div>
                      </div>

                      <div className="trip-info">
                        <span>
                          <Bus size={14} aria-hidden="true" /> {b.driver_bus_number || 'Bus pending'}
                        </span>
                        <span>
                          <MapPin size={14} aria-hidden="true" /> {b.pickup_stage_name || b.pickup_location || 'Pickup pending'}
                        </span>
                        <span>
                          {b.status}
                        </span>
                      </div>

                      <div className="trip-action">
                        <strong>{money(b.total_amount)}</strong>

                        {canOpenTripMap(b) ? (
                          <button
                            type="button"
                            className="glass-primary-button"
                            onClick={() =>
                              navigate(
                                `/passenger/map?booking=${encodeURIComponent(
                                  b.booking_id || b.id
                                )}`,
                                { state: { backToOverview: true } }
                              )
                            }
                          >
                            Open map
                          </button>
                        ) : (
                          <span className="trip-status-label">
                            {['cancelled', 'completed', 'no_show'].includes(
                              String(b.status || '').toLowerCase()
                            )
                              ? ({
                                  cancelled: 'Booking cancelled',
                                  completed: 'Booking completed',
                                  no_show: 'No-show',
                                }[String(b.status).toLowerCase()])
                              : ['completed', 'cancelled'].includes(
                                  String(b.trip_status || '').toLowerCase()
                                )
                                ? ({
                                    completed: 'Trip completed',
                                    cancelled: 'Trip cancelled',
                                  }[String(b.trip_status).toLowerCase()])
                                : String(b.status || '').toLowerCase() !== 'confirmed'
                                  ? 'Waiting for payment'
                                  : !b.trip_status
                                    ? 'Trip status unavailable'
                                    : ['boarding', 'departed'].includes(
                                        String(b.trip_status).toLowerCase()
                                      ) && !b.driver_id
                                      ? 'Driver pending'
                                      : 'Trip scheduled'}
                          </span>
                        )}
                      </div>
                    </article>
                  ))}
              </div>
            )}
          </section>

        </section>
      )}

      {/* =====================================================
          STEP 2 — TRANSPORT COMPANIES
          ===================================================== */}

      {journeyStep === 'companies' && (
        <section className="journey-section">

          <div className="journey-heading">
            <button type="button" className="journey-back" onClick={goBack}>
              ← Back
            </button>

            <span className="glass-eyebrow">
              Book a seat
            </span>

            <h1>Choose your transport company</h1>

            <p>
              Select a company to explore its available routes and
              scheduled departures.
            </p>
          </div>

          <div className="company-card-grid">
            {companies.map((c, index) => (
              <button
                type="button"
                className="company-glass-card"
                key={c.id}
                onClick={() => chooseCompany(c.id)}
              >
                <div
                  className={`company-image company-image-${index % 3}`}
                  style={{
                    backgroundImage: `url(${
                      c.name?.toLowerCase().includes('supermetro')
                        ? supermetroImage
                        : c.name?.toLowerCase().includes('city')
                          ? cityshuttleImage
                          : c.name?.toLowerCase().includes('latema')
                            ? latemaImage
                            : supermetroImage
                    })`,
                  }}
                >
                  <div className="company-image-shade" />
                  <div className="company-bus-mark"><Bus size={18} aria-hidden="true" /></div>
                                  </div>

                <div className="company-card-content">
                  <div>
                    <span className="company-kicker">Transport company</span>
                    <h2>{c.name}</h2>
                  </div>

                  <span className="company-card-arrow"><ArrowUpRight size={16} aria-hidden="true" /></span>
                </div>

                <div className="company-card-footer">
                  <span>View routes</span>
                </div>
              </button>
            ))}
          </div>

          {!companies.length && (
            <div className="glass-empty">
              <span>Loading transport companies…</span>
            </div>
          )}
        </section>
      )}

      {/* =====================================================
          STEP 3 — ROUTES
          ===================================================== */}

      {journeyStep === 'routes' && (
        <section className="journey-section">

          <div className="journey-heading">
            <button type="button" className="journey-back" onClick={goBack}>
              ← Companies
            </button>

            <span className="glass-eyebrow">
              {selectedCompany?.name || 'Transport company'}
            </span>

            <h1>Where would you like to go?</h1>

            <p>
              Choose a route to see its available departures.
            </p>
          </div>

          <div className="selected-company-strip">
            <div className="selected-company-icon"><Bus size={20} aria-hidden="true" /></div>
            <div>
              <span>Selected company</span>
              <strong>{selectedCompany?.name || 'Transport company'}</strong>
            </div>
          </div>

          <div className="route-list">
            {routes.map((r) => (
              <button
                type="button"
                className="route-glass-card"
                key={r.id}
                onClick={() => chooseRoute(r.id)}
              >
                <div className="route-point">
                  <span className="route-dot" />
                  <strong>{r.origin || 'Origin'}</strong>
                </div>

                <div className="route-line">
                  <span />
                  <span />
                  <span />
                </div>

                <div className="route-point route-destination">
                  <span className="route-dot" />
                  <strong>{r.destination || r.name || 'Destination'}</strong>
                </div>

                <div className="route-price">
                  <span>From</span>
                  <strong>{money(r.price)}</strong>
                </div>

                <span className="route-arrow">→</span>
              </button>
            ))}
          </div>

          {!routes.length && (
            <div className="glass-empty">
              <span>No routes are currently available for this company.</span>
            </div>
          )}
        </section>
      )}

      {/* =====================================================
          STEP 4 — AVAILABLE TRIPS
          ===================================================== */}

      {journeyStep === 'stages' && (
  <section className="journey-section pickup-stage-page">

    <div className="pickup-stage-topbar">
      <button
        type="button"
        className="journey-back"
        onClick={() => setJourneyStep('routes')}
      >
        ← Back to routes
      </button>

      <span className="glass-eyebrow">Step 3 of 4</span>
    </div>

    <div className="pickup-stage-heading">
      <div>
        <span className="pickup-stage-kicker">Pickup location</span>
        <h1>Where will you board?</h1>
        <p>
          Choose a pickup stage along your journey. We'll use this location
          to help you board the right vehicle.
        </p>
      </div>

      <div className="pickup-route-pill">
        <span>Route</span>
        <strong>
          {selectedRoute?.start_point || selectedRoute?.origin || 'Origin'}
          <b>→</b>
          {selectedRoute?.end_point || selectedRoute?.destination || 'Destination'}
        </strong>
      </div>
    </div>

    <div className="pickup-stage-card">
      <div className="pickup-stage-card-header">
        <div>
          <span className="pickup-stage-label">Available stages</span>
          <h2>Select your boarding point</h2>
        </div>

        <span className="pickup-stage-count">
          {(selectedRoute?.pickup_stages || [])
            .filter(stage => stage.is_active !== false).length} stages
        </span>
      </div>

      <div className="pickup-stage-grid">
        {(selectedRoute?.pickup_stages || [])
          .filter(stage => stage.is_active !== false)
          .map((stage, index) => (
            <button
              key={stage.id}
              type="button"
              className={`pickup-stage-option ${
                selectedStage?.id === stage.id ? 'selected' : ''
              }`}
              onClick={() => chooseStage(stage)}
            >
              <span className="pickup-stage-number">
                {String(index + 1).padStart(2, '0')}
              </span>

              <span className="pickup-stage-icon"><MapPin size={18} aria-hidden="true" /></span>

              <span className="pickup-stage-info">
                <strong>{stage.name}</strong>
                <small>{index === 0 ? 'Boarding point · book at the stage' : 'Pickup stage'}</small>
              </span>

              <span className="pickup-stage-arrow">→</span>
            </button>
          ))}
      </div>

      {(selectedRoute?.pickup_stages || []).length === 0 && (
        <div className="pickup-stage-empty">
          <span className="pickup-stage-empty-icon"><MapPin size={22} aria-hidden="true" /></span>
          <strong>No mapped pickup stages yet</strong>
          <p>
            You can enter another pickup location below.
          </p>
        </div>
      )}
    </div>

    <div className={`pickup-other-card ${otherPickup ? 'active' : ''}`}>
      <div className="pickup-other-icon">＋</div>

      <div className="pickup-other-content">
        <span className="pickup-stage-label">Custom pickup</span>
        <h2>Can't find your stage?</h2>
        <p>Enter another pickup location along the route.</p>

        <div className="pickup-other-form">
          <input
            id="other-pickup"
            type="text"
            value={otherPickup}
            onChange={(e) => {
              setOtherPickup(e.target.value);
              setSelectedStage(null);
            }}
            placeholder="e.g. Shell Rongai"
          />

          <button
            type="button"
            className="primary-button"
            disabled={!otherPickup.trim()}
            onClick={() => setJourneyStep('trips')}
          >
            Continue
          </button>
        </div>
      </div>
    </div>

    <div className="pickup-stage-help">
      <span><Check size={16} aria-hidden="true" /></span>
      <p>
        Select a recognized stage whenever possible for a smoother boarding
        experience.
      </p>
    </div>

  </section>
)}

{journeyStep === 'trips' && (
        <section className="journey-section">

          <div className="journey-heading">
            <button type="button" className="journey-back" onClick={goBack}>
              ← Routes
            </button>

            <span className="glass-eyebrow">
              Available departures
            </span>

            <h1>{selectedRoute?.name || 'Available trips'}</h1>

            <p>
              Select a scheduled departure that works for you.
            </p>
          </div>

          <div className="trip-summary-glass">
            <div>
              <span>{selectedCompany?.name || 'Transport company'}</span>
              <strong>
                {selectedRoute?.origin || 'Origin'}
                <b>→</b>
                {selectedRoute?.destination || 'Destination'}
              </strong>
            </div>

            <div className="trip-summary-price">
              <span>Fare</span>
              <strong>{money(selectedRoute?.price)}</strong>
            </div>
          </div>

          <label className="field">
            Departure date
            <input
              type="date"
              value={selectedDate}
              onChange={(event) => {
                if (event.target.value) setSelectedDate(event.target.value);
              }}
            />
          </label>

          <div className="modern-trip-list">
            {tripsLoading && !trips.length ? (
              <div className="glass-empty" role="status">Loading departures…</div>
            ) : !trips.length ? (
              <div className="glass-empty">
                <strong>No departures on {dayLabel(selectedDate)}</strong>
                {nextTripDate ? (
                  <>
                    <span>The next departure on this route is on {dayLabel(nextTripDate)}.</span>
                    <button type="button" className="glass-empty-action" onClick={() => setSelectedDate(nextTripDate)}>
                      Show {dayLabel(nextTripDate)}
                    </button>
                  </>
                ) : (
                  <>
                    <span>This route has no upcoming departures yet. Another route or company may have one.</span>
                    <button type="button" className="glass-empty-action" onClick={() => setJourneyStep('routes')}>
                      Choose another route
                    </button>
                  </>
                )}
              </div>
            ) : (
              trips.map((t) => (
                <article className="modern-trip-card" key={t.id}>

                  <div className="trip-time-block">
                    <span>Departure</span>
                    <strong>
                      {new Date(t.departure_at).toLocaleTimeString(
                        'en-KE',
                        { hour: '2-digit', minute: '2-digit' }
                      )}
                    </strong>
                    <small>
                      {new Date(t.departure_at).toLocaleDateString(
                        'en-KE',
                        { day: 'numeric', month: 'short' }
                      )}
                    </small>
                  </div>

                  <div className="trip-route-visual">
                    <div className="trip-route-line">
                      <span />
                      <i />
                      <span />
                    </div>

                    <div>
                      <strong>{t.route_details?.name || selectedRoute?.name}</strong>
                      <p>{t.company_name || selectedCompany?.name}</p>
                    </div>
                  </div>

                  <div className="trip-info">
                    <span>
                      <Bus size={14} aria-hidden="true" /> {t.driver_bus_number || 'Bus pending'}
                    </span>
                    <span>
                      <Armchair size={14} aria-hidden="true" /> {seatsLeft(t)} of {t.capacity || 0} seats left
                    </span>
                    <span>
                      {t.status}
                    </span>
                  </div>

                  <div className="trip-action">
                    <strong>{money(t.route_details?.price)}</strong>
                    <button
                      type="button"
                      className="glass-primary-button"
                      disabled={!canBookTrip(t)}
                      title={t.status === 'boarding' && !canBookTrip(t) ? 'Boarding has started: only the first stage can be booked' : undefined}
                      onClick={() => startBooking(t)}
                    >
                      {tripButtonLabel(t)}
                    </button>
                  </div>

                </article>
              ))
            )}
          </div>
        </section>
      )}

      {/* =====================================================
          BOOKING MODAL
          ===================================================== */}

      {bookingTrip && createPortal(
        <div className="modal-backdrop">
          <div className="modal modern-booking-modal">
            <div className="booking-modal-scroll">
            <button
              type="button"
              className="btn btn-ghost modal-close"
              onClick={() => setBookingTrip(null)}
            >
              Close
            </button>

            <span className="glass-eyebrow">Confirm your journey</span>

            <h2>{bookingTrip.route_details?.name}</h2>

            <p className="muted">
              {date(bookingTrip.departure_at)}
              {' • '}
              {bookingTrip.driver_name || 'Driver pending'}
            </p>

            <div className="booking-modal-glass-summary">
              <div>
                <span>Fare</span>
                <strong>
                  {money(bookingTrip.route_details?.price)}
                </strong>
              </div>

              <div>
                <span>Bus</span>
                <strong>
                  {bookingTrip.driver_bus_number || 'Pending'}
                </strong>
              </div>
            </div>

            <div className="booking-modal-rows">
              <div className="booking-seat-row">
                <span>Boarding at</span>
                <strong>{selectedStage?.name || otherPickup.trim() || 'Choose a pickup stage'}</strong>
              </div>
            </div>
            </div>

            <div className="booking-modal-footer">
              <div className="booking-seat-row">
                <span>Seats</span>
                <div className="booking-seat-stepper">
                  <button
                    type="button"
                    aria-label="Remove a seat"
                    onClick={() => setSeats(Math.max(1, Number(seats) - 1))}
                    disabled={Number(seats) <= 1}
                  >
                    −
                  </button>
                  <strong aria-live="polite">{seats}</strong>
                  <button
                    type="button"
                    aria-label="Add a seat"
                    onClick={() =>
                      setSeats(Math.min(20, seatsLeft(bookingTrip), Number(seats) + 1))
                    }
                    disabled={Number(seats) >= Math.min(20, seatsLeft(bookingTrip))}
                  >
                    +
                  </button>
                </div>
              </div>

              <div className="booking-total-glass">
                <span>Total journey cost</span>
                <strong>
                  {money(
                    Number(bookingTrip.route_details?.price || 0) *
                    Number(seats)
                  )}
                </strong>
              </div>

              <button
                type="button"
                className="glass-primary-button glass-primary-button-large"
                onClick={createBooking}
                disabled={loading}
              >
                {loading
                  ? 'Creating booking…'
                  : 'Confirm booking'}
              </button>
            </div>
          </div>
        </div>
        , document.body)}

      {/* =====================================================
          EXISTING PAYMENT FLOW
          ===================================================== */}

      {paymentBooking && (
        <PaymentModal
          booking={paymentBooking}
          onClose={() => {
            setPaymentBooking(null);
            refresh();
          }}
          onPaid={refresh}
          onPaymentConfirmed={handleBookingMapEntry}
          onCashReserved={handleBookingMapEntry}
        />
      )}

      {trackingBooking && (
        <LiveTripModal
          booking={trackingBooking}
          onClose={() => setTrackingBooking(null)}
        />
      )}

    </div>
  </Shell>;
}
import { createPortal } from 'react-dom';
