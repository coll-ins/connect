import { useCallback, useEffect, useState } from 'react';

import { apiRequest } from '../../api';
import { useAuth } from '../../context/AuthContext';
import { label, money, when } from '../shared/serviceUtils';
import '../shared/Services.css';

const Badge = ({ status }) => (
  <span className={`svc-badge svc-st-${status}`}>{label(status)}</span>
);

const SIZES = ['small', 'medium', 'large'];
const toValue = (v) => (v === '' || v == null ? null : String(v).trim());

export function ManagerParcels() {
  const [rates, setRates] = useState(null);
  const [edits, setEdits] = useState({});
  const [parcels, setParcels] = useState(null);
  const [filter, setFilter] = useState('');
  const [error, setError] = useState('');
  const [note, setNote] = useState('');

  const loadRates = useCallback(() => {
    apiRequest('/deliveries/rates/').then(setRates).catch((e) => setError(e.message));
  }, []);
  const loadParcels = useCallback(() => {
    apiRequest(`/deliveries/company/${filter ? `?status=${filter}` : ''}`)
      .then((d) => setParcels(Array.isArray(d) ? d : []))
      .catch((e) => { setError(e.message); setParcels([]); });
  }, [filter]);

  useEffect(() => { loadRates(); }, [loadRates]);
  useEffect(() => { loadParcels(); }, [loadParcels]);

  const edit = (routeId, size, value) =>
    setEdits((prev) => ({ ...prev, [routeId]: { ...(prev[routeId] || {}), [size]: value } }));

  const save = async (route) => {
    setError(''); setNote('');
    const body = {};
    SIZES.forEach((s) => { body[s] = toValue(edits[route.id]?.[s] ?? route[s]); });
    try {
      await apiRequest(`/deliveries/rates/${route.id}/`, { method: 'PATCH', body });
      setEdits((prev) => ({ ...prev, [route.id]: undefined }));
      setNote(`Saved rates for ${route.name}.`);
      loadRates();
    } catch (e) { setError(e.message); }
  };

  return (
    <div className="svc-page">
      <div className="svc-head">
        <div>
          <span className="glass-eyebrow">DELIVERY</span>
          <h1>Parcels</h1>
          <p>Set what you charge to carry parcels on each route. Leave a size blank and that size is not carried. A route with no prices carries no parcels.</p>
        </div>
      </div>

      {error && <div className="svc-error">{error}</div>}
      {note && <div className="svc-note">{note}</div>}

      <div className="svc-card">
        <h3>Parcel rates (KES)</h3>
        {rates === null ? 'Loading…' : !rates.length ? 'You have no routes yet.' : (
          <div className="svc-table-wrap">
            <table className="svc-table">
              <thead><tr><th>Route</th><th>Small</th><th>Medium</th><th>Large</th><th /></tr></thead>
              <tbody>
                {rates.map((r) => (
                  <tr key={r.id}>
                    <td>{r.name}</td>
                    {SIZES.map((s) => (
                      <td key={s}>
                        <input className="input svc-rate-input" type="number" min="1" step="1"
                          value={edits[r.id]?.[s] ?? r[s] ?? ''}
                          onChange={(e) => edit(r.id, s, e.target.value)} />
                      </td>
                    ))}
                    <td><button className="btn btn-primary" onClick={() => save(r)}>Save</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="svc-card">
        <div className="svc-head">
          <h3>Parcels on your trips</h3>
          <select className="input" style={{ width: 200 }} value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">All statuses</option>
            {['pending_payment', 'paid', 'picked_up', 'delivered', 'cancelled'].map((s) => (
              <option key={s} value={s}>{label(s)}</option>
            ))}
          </select>
        </div>
        {parcels === null ? 'Loading…' : !parcels.length ? 'No parcels.' : (
          <div className="svc-table-wrap">
            <table className="svc-table">
              <thead><tr><th>Code</th><th>Status</th><th>Trip</th><th>Sender</th><th>Receiver</th><th>Price</th></tr></thead>
              <tbody>
                {parcels.map((p) => (
                  <tr key={p.id}>
                    <td>{p.tracking_code}<br /><small className="svc-muted">{p.description}</small></td>
                    <td><Badge status={p.status} /></td>
                    <td>{p.route}<br /><small className="svc-muted">{when(p.departure_at)}</small></td>
                    <td>{p.sender_name}<br /><small className="svc-muted">{p.sender_phone}</small></td>
                    <td>{p.receiver_name}<br /><small className="svc-muted">{p.receiver_phone}</small></td>
                    <td>{money(p.price)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function QuoteForm({ charter, drivers, onDone }) {
  const [price, setPrice] = useState(charter.quote_price || '');
  const [driver, setDriver] = useState('');
  const [hours, setHours] = useState(48);
  const [reason, setReason] = useState('');
  const [mode, setMode] = useState('quote');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const run = async (path, body) => {
    setBusy(true); setError('');
    try { await apiRequest(`/charters/${charter.id}/${path}/`, { method: 'POST', body }); onDone(); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  return (
    <div style={{ marginTop: 14 }}>
      {error && <div className="svc-error" style={{ marginBottom: 10 }}>{error}</div>}
      <div className="svc-actions" style={{ marginTop: 0, marginBottom: 12 }}>
        <button className={`btn ${mode === 'quote' ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setMode('quote')}>Send a quote</button>
        <button className={`btn ${mode === 'decline' ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setMode('decline')}>Decline</button>
      </div>

      {mode === 'quote' ? (
        <div className="svc-form">
          <label className="svc-field">Price (KES)
            <input className="input" type="number" min="1" value={price} onChange={(e) => setPrice(e.target.value)} />
          </label>
          <label className="svc-field">Bus and driver
            <select className="input" value={driver} onChange={(e) => setDriver(e.target.value)}>
              <option value="">Choose…</option>
              {drivers.map((d) => <option key={d.id} value={d.id}>{d.name} · {d.bus_number}</option>)}
            </select>
          </label>
          <label className="svc-field">Quote valid for (hours)
            <input className="input" type="number" min="1" max="168" value={hours} onChange={(e) => setHours(e.target.value)} />
          </label>
          <div className="svc-actions wide" style={{ gridColumn: '1 / -1', marginTop: 0 }}>
            <button className="btn btn-primary" disabled={busy || !price || !driver}
              onClick={() => run('quote', { price: String(price), driver_id: Number(driver), valid_hours: Number(hours) })}>
              {busy ? 'Sending…' : 'Send quote'}
            </button>
          </div>
        </div>
      ) : (
        <div className="svc-form">
          <label className="svc-field wide">Reason (the passenger will see this)
            <input className="input" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <div style={{ gridColumn: '1 / -1' }}>
            <button className="btn btn-primary" disabled={busy || !reason.trim()} onClick={() => run('decline', { reason: reason.trim() })}>
              {busy ? 'Declining…' : 'Decline request'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function ManagerCharters() {
  const { user } = useAuth();
  const [accepts, setAccepts] = useState(null);
  const [rows, setRows] = useState(null);
  const [drivers, setDrivers] = useState([]);
  const [filter, setFilter] = useState('');
  const [error, setError] = useState('');

  const loadRows = useCallback(() => {
    apiRequest(`/charters/company/${filter ? `?status=${filter}` : ''}`)
      .then((d) => setRows(Array.isArray(d) ? d : []))
      .catch((e) => { setError(e.message); setRows([]); });
  }, [filter]);

  useEffect(() => {
    apiRequest('/charters/settings/').then((d) => setAccepts(Boolean(d.accepts_charters))).catch((e) => setError(e.message));
  }, []);
  useEffect(() => { loadRows(); }, [loadRows]);
  useEffect(() => {
    if (!user?.company_id) return;
    apiRequest(`/drivers/?company_id=${user.company_id}`)
      .then((d) => setDrivers(Array.isArray(d) ? d : []))
      .catch((e) => setError(e.message));
  }, [user?.company_id]);

  const toggle = async () => {
    setError('');
    try {
      const d = await apiRequest('/charters/settings/', { method: 'PATCH', body: { accepts_charters: !accepts } });
      setAccepts(Boolean(d.accepts_charters));
    } catch (e) { setError(e.message); }
  };

  return (
    <div className="svc-page">
      <div className="svc-head">
        <div>
          <span className="glass-eyebrow">BUS HIRE</span>
          <h1>Bus hire requests</h1>
          <p>Passengers ask to hire a whole bus. You send a price and a driver, they accept and pay in the app, and the booking is confirmed. A bus cannot be double-booked.</p>
        </div>
      </div>

      {error && <div className="svc-error">{error}</div>}

      <div className="svc-card">
        <h3>Accepting bus hire requests</h3>
        <p className="svc-muted">When this is off, your company is not shown to passengers for bus hire. Make sure you are licensed and insured to hire out buses before turning it on.</p>
        <div className="svc-actions">
          <button className="btn btn-primary" onClick={toggle} disabled={accepts === null}>
            {accepts ? 'Turn off' : 'Turn on'}
          </button>
          <span className="svc-badge">{accepts === null ? '…' : accepts ? 'On' : 'Off'}</span>
        </div>
      </div>

      <div className="svc-head">
        <h3 style={{ margin: 0 }}>Requests</h3>
        <select className="input" style={{ width: 200 }} value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">All statuses</option>
          {['requested', 'quoted', 'confirmed', 'completed', 'declined', 'cancelled'].map((s) => (
            <option key={s} value={s}>{label(s)}</option>
          ))}
        </select>
      </div>

      {rows === null ? <div className="glass-empty">Loading…</div> : !rows.length ? (
        <div className="glass-empty">No requests.</div>
      ) : (
        <div className="svc-list">
          {rows.map((c) => (
            <div key={c.id} className="svc-card">
              <div className="svc-head">
                <div>
                  <strong>{c.reference} · {c.purpose}</strong>
                  <div className="svc-muted">{c.pickup_location} → {c.destination}</div>
                </div>
                <Badge status={c.status} />
              </div>
              <dl className="svc-dl" style={{ marginTop: 12 }}>
                <div><span>Departure</span><strong>{when(c.depart_at)}</strong></div>
                <div><span>Return</span><strong>{c.return_at ? when(c.return_at) : '—'}</strong></div>
                <div><span>Passengers</span><strong>{c.passenger_count}</strong></div>
                <div><span>Contact</span><strong>{c.contact_name} · {c.contact_phone}</strong></div>
                {c.quote_price && <div><span>Quote</span><strong>{money(c.quote_price)}</strong></div>}
                {c.driver && <div><span>Driver</span><strong>{c.driver.name} · {c.driver.bus_number}</strong></div>}
                {c.notes && <div><span>Notes</span><strong>{c.notes}</strong></div>}
              </dl>
              {['requested', 'quoted'].includes(c.status) && (
                <QuoteForm charter={c} drivers={drivers} onDone={loadRows} />
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
