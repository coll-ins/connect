import { useCallback, useEffect, useState } from 'react';

import { apiRequest } from '../../api';
import { label, when } from '../shared/serviceUtils';
import '../shared/Services.css';

const Badge = ({ status }) => (
  <span className={`svc-badge svc-st-${status}`}>{label(status)}</span>
);

function ParcelJob({ parcel, onChange }) {
  const [pin, setPin] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const act = async (path, body) => {
    setBusy(true); setError('');
    try { await apiRequest(`/deliveries/${parcel.id}/${path}/`, { method: 'POST', body }); setPin(''); onChange(); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  return (
    <div className="svc-card">
      <div className="svc-head">
        <div>
          <strong>{parcel.tracking_code} · {parcel.description}</strong>
          <div className="svc-muted">{parcel.pickup_stage.name} → {parcel.dropoff_stage.name} · {label(parcel.size)}</div>
        </div>
        <Badge status={parcel.status} />
      </div>
      <dl className="svc-dl" style={{ marginTop: 12 }}>
        <div><span>Departure</span><strong>{when(parcel.departure_at)}</strong></div>
        <div><span>Sender</span><strong>{parcel.sender_name} · <a href={`tel:${parcel.sender_phone}`}>{parcel.sender_phone}</a></strong></div>
        <div><span>Receiver</span><strong>{parcel.receiver_name} · <a href={`tel:${parcel.receiver_phone}`}>{parcel.receiver_phone}</a></strong></div>
      </dl>
      {error && <div className="svc-error" style={{ marginTop: 12 }}>{error}</div>}
      {parcel.status === 'paid' && (
        <div className="svc-actions">
          <button className="btn btn-primary" disabled={busy} onClick={() => act('pickup')}>{busy ? 'Saving…' : 'Mark as picked up'}</button>
        </div>
      )}
      {parcel.status === 'picked_up' && (
        <div className="svc-actions">
          <input className="input" style={{ maxWidth: 180 }} inputMode="numeric" maxLength={6} placeholder="Receiver's 6-digit PIN"
            value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))} />
          <button className="btn btn-primary" disabled={busy || pin.length !== 6} onClick={() => act('deliver', { pin })}>
            {busy ? 'Checking…' : 'Confirm delivery'}
          </button>
        </div>
      )}
    </div>
  );
}

function CharterJob({ charter, onChange }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const complete = async () => {
    setBusy(true); setError('');
    try { await apiRequest(`/charters/${charter.id}/complete/`, { method: 'POST' }); onChange(); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  return (
    <div className="svc-card">
      <div className="svc-head">
        <div>
          <strong>{charter.reference} · {charter.purpose}</strong>
          <div className="svc-muted">{charter.pickup_location} → {charter.destination}</div>
        </div>
        <Badge status={charter.status} />
      </div>
      <dl className="svc-dl" style={{ marginTop: 12 }}>
        <div><span>Departure</span><strong>{when(charter.depart_at)}</strong></div>
        <div><span>Return</span><strong>{charter.return_at ? when(charter.return_at) : '—'}</strong></div>
        <div><span>Passengers</span><strong>{charter.passenger_count}</strong></div>
        <div><span>Contact</span><strong>{charter.contact_name} · <a href={`tel:${charter.contact_phone}`}>{charter.contact_phone}</a></strong></div>
        {charter.notes && <div><span>Notes</span><strong>{charter.notes}</strong></div>}
      </dl>
      {error && <div className="svc-error" style={{ marginTop: 12 }}>{error}</div>}
      <div className="svc-actions">
        <button className="btn btn-primary" disabled={busy} onClick={complete}>{busy ? 'Saving…' : 'Mark hire completed'}</button>
      </div>
    </div>
  );
}

export default function DriverJobs() {
  const [parcels, setParcels] = useState(null);
  const [charters, setCharters] = useState(null);
  const [error, setError] = useState('');

  const load = useCallback(() => {
    apiRequest('/deliveries/driver/').then((d) => setParcels(Array.isArray(d) ? d : [])).catch((e) => { setError(e.message); setParcels([]); });
    apiRequest('/charters/driver/').then((d) => setCharters(Array.isArray(d) ? d : [])).catch((e) => { setError(e.message); setCharters([]); });
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="svc-page">
      {error && <div className="svc-error">{error}</div>}

      <div className="svc-head"><h2 style={{ margin: 0 }}>Parcels on your trips</h2></div>
      {parcels === null ? <div className="glass-empty">Loading…</div> : !parcels.length ? (
        <div className="glass-empty">No paid parcels waiting.</div>
      ) : parcels.map((p) => <ParcelJob key={p.id} parcel={p} onChange={load} />)}

      <div className="svc-head"><h2 style={{ margin: 0 }}>Bus hire jobs</h2></div>
      {charters === null ? <div className="glass-empty">Loading…</div> : !charters.length ? (
        <div className="glass-empty">No confirmed hires assigned to you.</div>
      ) : charters.map((c) => <CharterJob key={c.id} charter={c} onChange={load} />)}
    </div>
  );
}
