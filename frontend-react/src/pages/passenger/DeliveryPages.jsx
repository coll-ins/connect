import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Package, Plus } from 'lucide-react';

import { apiRequest } from '../../api';
import AppShell from '../../components/layout/AppShell';
import { label, money, when } from '../shared/serviceUtils';
import '../shared/Services.css';

const SIZE_LABELS = {
  small: 'Small (fits in a bag)',
  medium: 'Medium (a box)',
  large: 'Large (bulky)',
};

const Badge = ({ status }) => (
  <span className={`svc-badge svc-st-${status}`}>{label(status)}</span>
);

export function DeliveryList() {
  const [parcels, setParcels] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    apiRequest('/deliveries/')
      .then((d) => setParcels(Array.isArray(d) ? d : []))
      .catch((e) => { setError(e.message); setParcels([]); });
  }, []);

  return (
    <AppShell>
      <div className="svc-page">
        <div className="svc-head">
          <div>
            <span className="glass-eyebrow">DELIVERY</span>
            <h1>Your parcels</h1>
            <p>Send a parcel on a scheduled trip. You pay in the app, and the driver only hands it over against the receiver&apos;s PIN.</p>
          </div>
          <Link className="btn btn-primary" to="/passenger/delivery/new"><Plus size={16} /> Send a parcel</Link>
        </div>

        {error && <div className="svc-error">{error}</div>}

        {parcels === null ? (
          <div className="glass-empty">Loading…</div>
        ) : !parcels.length ? (
          <div className="glass-empty"><Package size={28} /><strong>No parcels yet.</strong></div>
        ) : (
          <div className="svc-list">
            {parcels.map((p) => (
              <Link key={p.id} to={`/passenger/delivery/${p.id}`} className="svc-card svc-item">
                <div>
                  <strong>{p.tracking_code}</strong>
                  <span>{p.description}</span>
                  <small>{p.company} · {p.pickup_stage.name} → {p.dropoff_stage.name}</small>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <Badge status={p.status} />
                  <strong style={{ marginTop: 6 }}>{money(p.price)}</strong>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}

export function DeliveryNew() {
  const navigate = useNavigate();
  const [options, setOptions] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [f, setF] = useState({
    company: '', route: '', trip: '', pickup: '', dropoff: '', size: '',
    description: '', receiverName: '', receiverPhone: '', ok: false,
  });
  const set = (patch) => setF((v) => ({ ...v, ...patch }));

  useEffect(() => {
    apiRequest('/deliveries/options/')
      .then((d) => setOptions(Array.isArray(d) ? d : []))
      .catch((e) => { setError(e.message); setOptions([]); });
  }, []);

  const company = options?.find((c) => String(c.id) === f.company);
  const route = company?.routes.find((r) => String(r.id) === f.route);
  const stages = route?.stages || [];
  const pickupStage = stages.find((s) => String(s.id) === f.pickup);
  const dropoffs = pickupStage ? stages.filter((s) => s.order > pickupStage.order) : [];
  const price = route && f.size ? route.rates[f.size] : null;
  const ready = f.company && f.route && f.trip && f.pickup && f.dropoff && f.size
    && f.description.trim() && f.receiverName.trim() && f.receiverPhone.trim() && f.ok;

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError('');
    try {
      const parcel = await apiRequest('/deliveries/', {
        method: 'POST',
        body: {
          trip_id: Number(f.trip),
          pickup_stage_id: Number(f.pickup),
          dropoff_stage_id: Number(f.dropoff),
          size: f.size,
          description: f.description.trim(),
          receiver_name: f.receiverName.trim(),
          receiver_phone: f.receiverPhone.trim(),
          no_prohibited_items: f.ok,
        },
      });
      navigate(`/passenger/delivery/${parcel.id}`);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return (
    <AppShell>
      <div className="svc-page">
        <div className="svc-head">
          <div>
            <Link to="/passenger/delivery" className="journey-back">← Parcels</Link>
            <h1>Send a parcel</h1>
            <p>Pick the company, route and the bus that will carry it. The price is set by the company.</p>
          </div>
        </div>

        {error && <div className="svc-error">{error}</div>}

        {options === null ? (
          <div className="glass-empty">Loading…</div>
        ) : !options.length ? (
          <div className="glass-empty"><strong>No company is carrying parcels right now.</strong></div>
        ) : (
          <form className="svc-card" onSubmit={submit}>
            <div className="svc-form">
              <label className="svc-field">Company
                <select className="input" value={f.company}
                  onChange={(e) => set({ company: e.target.value, route: '', trip: '', pickup: '', dropoff: '', size: '' })}>
                  <option value="">Choose…</option>
                  {options.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </label>

              <label className="svc-field">Route
                <select className="input" value={f.route} disabled={!company}
                  onChange={(e) => set({ route: e.target.value, trip: '', pickup: '', dropoff: '', size: '' })}>
                  <option value="">Choose…</option>
                  {company?.routes.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                </select>
              </label>

              <label className="svc-field wide">Trip
                <select className="input" value={f.trip} disabled={!route} onChange={(e) => set({ trip: e.target.value })}>
                  <option value="">Choose…</option>
                  {route?.trips.map((t) => (
                    <option key={t.id} value={t.id}>{when(t.departure_at)} · {t.bus_number}</option>
                  ))}
                </select>
              </label>

              <label className="svc-field">Drop the parcel at
                <select className="input" value={f.pickup} disabled={!route}
                  onChange={(e) => set({ pickup: e.target.value, dropoff: '' })}>
                  <option value="">Choose pickup stage…</option>
                  {stages.slice(0, -1).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              </label>

              <label className="svc-field">Receiver collects at
                <select className="input" value={f.dropoff} disabled={!pickupStage} onChange={(e) => set({ dropoff: e.target.value })}>
                  <option value="">Choose drop-off stage…</option>
                  {dropoffs.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              </label>

              <label className="svc-field">Size
                <select className="input" value={f.size} disabled={!route} onChange={(e) => set({ size: e.target.value })}>
                  <option value="">Choose…</option>
                  {route && Object.keys(route.rates).map((k) => (
                    <option key={k} value={k}>{SIZE_LABELS[k]} — {money(route.rates[k])}</option>
                  ))}
                </select>
              </label>

              <label className="svc-field">What is in the parcel?
                <input className="input" maxLength={200} value={f.description} onChange={(e) => set({ description: e.target.value })} placeholder="e.g. Documents" />
              </label>

              <label className="svc-field">Receiver&apos;s name
                <input className="input" maxLength={100} value={f.receiverName} onChange={(e) => set({ receiverName: e.target.value })} />
              </label>

              <label className="svc-field">Receiver&apos;s phone
                <input className="input" type="tel" inputMode="tel" value={f.receiverPhone} onChange={(e) => set({ receiverPhone: e.target.value })} placeholder="07XX XXX XXX" />
              </label>

              <label className="svc-check wide">
                <input type="checkbox" checked={f.ok} onChange={(e) => set({ ok: e.target.checked })} />
                <span>I confirm the parcel contains no prohibited items (weapons, drugs, flammables, live animals, cash). I have the receiver&apos;s permission to share their name and phone number with CONNECT and the transport company for this delivery.</span>
              </label>
            </div>

            <div className="svc-actions">
              <button className="btn btn-primary" disabled={!ready || busy}>
                {busy ? 'Creating…' : price ? `Continue · ${money(price)}` : 'Continue'}
              </button>
            </div>
          </form>
        )}
      </div>
    </AppShell>
  );
}

export function DeliveryDetail() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const [p, setP] = useState(null);
  const [error, setError] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setP(await apiRequest(`/deliveries/${id}/`)); } catch (e) { setError(e.message); }
  }, [id]);

  const verify = useCallback(async () => {
    setBusy(true); setError(''); setNote('');
    try {
      const data = await apiRequest(`/deliveries/${id}/verify/`, { method: 'POST' });
      if (data?.tracking_code) setP(data);
      else setNote(data?.message || 'Payment has not completed yet.');
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }, [id]);

  useEffect(() => {
    load();
    if (params.get('reference') || params.get('trxref')) {
      verify();
      setParams({}, { replace: true });
    }
  }, [id]);

  const pay = async () => {
    setBusy(true); setError('');
    try {
      const d = await apiRequest(`/deliveries/${id}/pay/`, { method: 'POST' });
      window.location.href = d.authorization_url;
    } catch (e) { setError(e.message); setBusy(false); }
  };

  const cancel = async () => {
    setBusy(true); setError('');
    try { setP(await apiRequest(`/deliveries/${id}/cancel/`, { method: 'POST' })); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  return (
    <AppShell>
      <div className="svc-page">
        <div className="svc-head">
          <div>
            <Link to="/passenger/delivery" className="journey-back">← Parcels</Link>
            <h1>{p ? p.tracking_code : 'Parcel'}</h1>
          </div>
          {p && <Badge status={p.status} />}
        </div>

        {error && <div className="svc-error">{error}</div>}
        {note && <div className="svc-note">{note}</div>}
        {!p && !error && <div className="glass-empty">Loading…</div>}

        {p && (
          <>
            {p.handover_pin && ['paid', 'picked_up'].includes(p.status) && (
              <div className="svc-card">
                <h3>Receiver&apos;s PIN</h3>
                <div className="svc-pin">{p.handover_pin}</div>
                <p className="svc-muted">Give this PIN to {p.receiver_name} only. The driver will ask for it at hand-over, and cannot complete the delivery without it.</p>
              </div>
            )}

            {p.status === 'pending_payment' && (
              <div className="svc-card">
                <h3>Pay {money(p.price)}</h3>
                <p className="svc-muted">Payment is made in the app. The parcel is only collected after it is paid.</p>
                <div className="svc-actions">
                  <button className="btn btn-primary" onClick={pay} disabled={busy}>{busy ? 'Please wait…' : `Pay ${money(p.price)}`}</button>
                  <button className="btn btn-secondary" onClick={verify} disabled={busy}>I&apos;ve paid — check status</button>
                  <button className="btn btn-ghost" onClick={cancel} disabled={busy}>Cancel parcel</button>
                </div>
              </div>
            )}

            <div className="svc-card">
              <h3>Details</h3>
              <dl className="svc-dl">
                <div><span>Contents</span><strong>{p.description}</strong></div>
                <div><span>Size</span><strong>{label(p.size)}</strong></div>
                <div><span>Price</span><strong>{money(p.price)}</strong></div>
                <div><span>Company</span><strong>{p.company}</strong></div>
                <div><span>Route</span><strong>{p.route}</strong></div>
                <div><span>Departure</span><strong>{when(p.departure_at)}</strong></div>
                <div><span>From</span><strong>{p.pickup_stage.name}</strong></div>
                <div><span>To</span><strong>{p.dropoff_stage.name}</strong></div>
                <div><span>Receiver</span><strong>{p.receiver_name} · {p.receiver_phone}</strong></div>
              </dl>
            </div>

            <div className="svc-card">
              <h3>Progress</h3>
              <dl className="svc-dl">
                <div><span>Created</span><strong>{when(p.created_at)}</strong></div>
                <div><span>Paid</span><strong>{when(p.paid_at)}</strong></div>
                <div><span>Picked up</span><strong>{when(p.picked_up_at)}</strong></div>
                <div><span>Delivered</span><strong>{when(p.delivered_at)}</strong></div>
              </dl>
              {p.status === 'paid' && <p className="svc-muted" style={{ marginTop: 14 }}>Paid parcels cannot be cancelled in the app yet. Contact support if you need a refund.</p>}
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
