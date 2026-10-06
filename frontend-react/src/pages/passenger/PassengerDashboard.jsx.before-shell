import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiRequest } from '../../api';
import { useAuth } from '../../context/AuthContext';

const money = (v) => `KES ${Number(v || 0).toLocaleString('en-KE',{minimumFractionDigits:2,maximumFractionDigits:2})}`;
const date = (v) => v ? new Date(v).toLocaleString('en-KE',{dateStyle:'medium',timeStyle:'short'}) : 'Not scheduled';

function Shell({ user, logout, children }) {
  return <div className="page"><div className="shell"><header className="topbar"><div className="brand"><div className="brand-icon">C</div><div>CONNECT<small>Smart matatu travel</small></div></div><div className="top-actions"><span className="location-chip">● {user?.name || 'Passenger'}</span><button className="btn btn-ghost" onClick={logout}>Logout</button></div></header>{children}</div></div>;
}

function PaymentModal({ booking, onClose, onPaid }) {
  const [step, setStep] = useState('method');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const cash = async () => {
    setBusy(true); setError('');
    try { await apiRequest(`/bookings/payments/${booking.booking_id}/cash/`, { method:'POST' }); setStep('cash-success'); onPaid(); }
    catch(e){setError(e.message)} finally{setBusy(false)}
  };

  const mpesa = async () => {
    setBusy(true); setError('');
    try {
      const data = await apiRequest(`/bookings/payments/${booking.booking_id}/mpesa/`, {method:'POST'});
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
        if (status.payment_status === 'confirmed') { setStep('paid'); onPaid(); return; }
        if (status.payment_status === 'failed') { setError('The M-PESA payment failed. You can try again.'); setStep('method'); return; }
      } catch {
        // Keep polling while the gateway completes the transaction.
      }
      if (active && attempts < 60) window.setTimeout(poll, 3000);
      else if (active) setMessage('Still waiting for Paystack. You can refresh the status or close this window and check your bookings.');
    };
    poll();
    return () => { active = false; };
  }, [step, booking.booking_id, onPaid]);

  const verify = async () => {
    setBusy(true); setError('');
    try { const data = await apiRequest(`/bookings/payments/${booking.booking_id}/verify/`, {method:'POST'}); if(data.payment_status==='confirmed'){setStep('paid');onPaid();} else setMessage(data.message || 'Payment is still pending.'); }
    catch(e){setError(e.message)} finally{setBusy(false)}
  };

  return <div className="modal-backdrop"><div className="modal">
    <button className="btn btn-ghost modal-close" onClick={onClose}>Close</button>
    <p className="eyebrow">BOOKING {booking.booking_number}</p>
    <h2>{money(booking.total_amount)}</h2><p className="muted">Choose how you want to complete this trip.</p>
    {error && <div className="error">{error}</div>}
    {step==='method' && <div className="stack" style={{marginTop:18}}>
      <button className="pay-option" onClick={cash} disabled={busy}><div className="pay-icon">💵</div><div><strong>Pay with cash</strong><span>Pay the driver/conductor according to the trip rules.</span></div></button>
      <button className="pay-option" onClick={()=>setStep('online')} disabled={busy}><div className="pay-icon">💳</div><div><strong>Pay online</strong><span>Choose M-PESA or Card securely through Paystack.</span></div></button>
    </div>}
    {step==='online' && <div className="stack" style={{marginTop:18}}>
      <button className="pay-option" onClick={mpesa} disabled={busy}><div className="pay-icon">📱</div><div><strong>M-PESA</strong><span>Use your saved phone number and receive the STK push.</span></div></button>
      <button className="pay-option" onClick={card} disabled={busy}><div className="pay-icon">💳</div><div><strong>Card</strong><span>Secure Paystack checkout. Card authentication stays with Paystack.</span></div></button>
      <button className="btn btn-ghost" onClick={()=>setStep('method')}>← Back</button>
    </div>}
    {step==='mpesa-wait' && <div className="payment-status"><div className="payment-spinner"/><h3>Check your phone</h3><p className="muted">{message}</p><p className="mobile-note">The M-PESA prompt is sent to the number saved on your CONNECT account. Authorize it on your phone.</p><button className="btn btn-secondary" onClick={verify} disabled={busy}>{busy?'Checking…':'Check payment status'}</button></div>}
    {step==='cash-success' && <div className="success">Cash selected. Your booking is ready for the driver/conductor to confirm according to the cash-payment flow.</div>}
    {step==='paid' && <div className="payment-status"><div style={{fontSize:48}}>✓</div><h3>Payment confirmed</h3><p className="muted">Your booking is confirmed. Enjoy your trip.</p><button className="btn btn-primary" onClick={onClose}>Done</button></div>}
  </div></div>;
}

export default function PassengerDashboard() {
  const { user, logout } = useAuth();
  const [companies,setCompanies]=useState([]),[routes,setRoutes]=useState([]),[trips,setTrips]=useState([]),[bookings,setBookings]=useState([]),[wallet,setWallet]=useState(null);
  const [company,setCompany]=useState(''),[route,setRoute]=useState('');
  const [bookingTrip,setBookingTrip]=useState(null),[seats,setSeats]=useState(1),[pickup,setPickup]=useState(user?.location||'Main Stage');
  const [paymentBooking,setPaymentBooking]=useState(null),[loading,setLoading]=useState(false),[error,setError]=useState(''),[success,setSuccess]=useState('');

  const refresh = useCallback(async()=>{
    try { const [b,w]=await Promise.all([apiRequest('/bookings/my/'),apiRequest('/wallet/')]); setBookings(Array.isArray(b)?b:[]); setWallet(w); } catch(e){setError(e.message)}
  },[]);
  useEffect(()=>{apiRequest('/companies/').then(d=>setCompanies(Array.isArray(d)?d:[])).catch(e=>setError(e.message));refresh()},[refresh]);
  useEffect(()=>{if(!company){setRoutes([]);setTrips([]);return} apiRequest(`/companies/${company}/routes/`).then(d=>setRoutes(d||[])).catch(e=>setError(e.message))},[company]);
  useEffect(()=>{if(!company){setTrips([]);return} const q=route?`?route_id=${route}`:''; apiRequest(`/companies/${company}/trips/${q}`).then(d=>setTrips(Array.isArray(d)?d:[])).catch(e=>setError(e.message))},[company,route]);

  const selectedRoute=useMemo(()=>routes.find(r=>String(r.id)===String(route)),[routes,route]);
  const startBooking=(trip)=>{setError('');setBookingTrip(trip);setSeats(1);setPickup(user?.location||'Main Stage')};
  const createBooking=async()=>{
    if(!pickup.trim()) return setError('Enter a pickup location.');
    setLoading(true);setError('');
    try { const b=await apiRequest('/bookings/create/',{method:'POST',body:{trip_id:bookingTrip.id,seats:Number(seats),pickup_location:pickup.trim()}});setBookingTrip(null);await refresh();setPaymentBooking({booking_id:b.booking_id,booking_number:b.booking_number,total_amount:b.total_amount}); }
    catch(e){setError(e.message)}finally{setLoading(false)}
  };
  const cancel=async(id)=>{if(!confirm('Cancel this booking?'))return;try{await apiRequest(`/bookings/${id}/cancel/`,{method:'POST'});setSuccess('Booking cancelled.');refresh()}catch(e){setError(e.message)}};

  return <Shell user={user} logout={logout}>
    <section className="hero"><p className="eyebrow">PASSENGER DASHBOARD</p><h1>Move around Nairobi with less waiting.</h1><p className="muted">Choose a company, route and departure. Your payment options appear immediately after booking.</p></section>
    {error&&<div className="error">{error}</div>}{success&&<div className="success">{success}</div>}
    <div className="section-title"><h2>Your account</h2></div>
    <div className="kpi-row"><div className="card stat"><div className="stat-label">Wallet balance</div><div className="stat-value">{money(wallet?.available_balance)}</div></div><div className="card stat"><div className="stat-label">Held</div><div className="stat-value">{money(wallet?.held_balance)}</div></div><div className="card stat"><div className="stat-label">Integrity score</div><div className="stat-value">{user?.integrity_score == null ? 'New' : `${user.integrity_score}%`}</div></div><div className="card stat"><div className="stat-label">Bookings</div><div className="stat-value">{bookings.length}</div></div></div>

    <div className="section-title"><h2>Find a trip</h2></div>
    <div className="card toolbar"><label className="field">Company<select className="select" value={company} onChange={e=>{setCompany(e.target.value);setRoute('')}}><option value="">Choose a company</option>{companies.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label><label className="field">Route<select className="select" value={route} onChange={e=>setRoute(e.target.value)} disabled={!company}><option value="">All routes</option>{routes.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select></label></div>
    {selectedRoute&&<p className="muted">{selectedRoute.origin} → {selectedRoute.destination} • {money(selectedRoute.price)}</p>}
    <div className="section-title"><h2>Available departures</h2></div>
    {!trips.length?<div className="empty">Choose a company to see scheduled departures.</div>:<div className="grid trip-grid">{trips.map(t=><div className="card trip-card" key={t.id}><div className="trip-top"><div><div className="trip-route">{t.route_details?.name || 'Trip'}</div><div className="muted">{t.company_name}</div></div><span className={`badge ${t.status==='scheduled'?'badge-green':'badge-amber'}`}>{t.status}</span></div><div className="trip-meta"><span>🕒 {date(t.departure_at)}</span><span>🚌 {t.driver_name||'Driver pending'} • {t.driver_bus_number||'Bus pending'}</span><span>💺 Capacity {t.capacity}</span></div><div style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:12}}><div className="price">{money(t.route_details?.price)}</div><button className="btn btn-primary" disabled={t.status!=='scheduled'} onClick={()=>startBooking(t)}>Book trip</button></div></div>)}</div>}

    <div className="section-title"><h2>My bookings</h2><button className="btn btn-ghost" onClick={refresh}>Refresh</button></div>
    {!bookings.length?<div className="empty">Your bookings will appear here.</div>:<div className="grid booking-grid">{bookings.map(b=><div className="card" key={b.booking_id}><div className="trip-top"><strong>{b.booking_number}</strong><span className={`badge ${b.status==='confirmed'?'badge-green':b.status==='cancelled'?'badge-red':'badge-amber'}`}>{b.status}</span></div><p>{b.route_name}</p><p className="muted">{b.seats} seat(s) • {b.pickup_location}</p><p className="price">{money(b.total_amount)}</p><div className="nav-pills"><span className="nav-pill">Payment: {b.payment_status}</span>{b.payment_method&&<span className="nav-pill">{b.payment_method}</span>}</div><div style={{display:'flex',gap:8,marginTop:14}}>{b.payment_status!=='confirmed'&&b.status!=='cancelled'&&<button className="btn btn-primary" onClick={()=>setPaymentBooking(b)}>Pay now</button>}{!['cancelled','completed'].includes(b.status)&&<button className="btn btn-danger" onClick={()=>cancel(b.booking_id)}>Cancel</button>}</div></div>)}</div>}

    {bookingTrip&&<div className="modal-backdrop"><div className="modal"><button className="btn btn-ghost modal-close" onClick={()=>setBookingTrip(null)}>Close</button><p className="eyebrow">CONFIRM BOOKING</p><h2>{bookingTrip.route_details?.name}</h2><p className="muted">{date(bookingTrip.departure_at)} • {bookingTrip.driver_name||'Driver pending'}</p><div className="form-stack"><label className="field">Seats<input className="input" type="number" min="1" max="20" value={seats} onChange={e=>setSeats(Math.max(1,Math.min(20,Number(e.target.value)||1)))} /></label><label className="field">Pickup location<input className="input" value={pickup} onChange={e=>setPickup(e.target.value)} /></label><div className="card" style={{background:'#071522'}}><span className="muted">Total</span><div className="price">{money(Number(bookingTrip.route_details?.price||0)*Number(seats))}</div></div><button className="btn btn-primary btn-full" onClick={createBooking} disabled={loading}>{loading?'Creating booking…':'Confirm booking & continue to payment'}</button></div></div></div>}
    {paymentBooking&&<PaymentModal booking={paymentBooking} onClose={()=>{setPaymentBooking(null);refresh()}} onPaid={refresh}/>} 
  </Shell>;
}
