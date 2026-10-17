import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Bus, Plus } from 'lucide-react';

import { apiRequest } from '../../api';
import AppShell from '../../components/layout/AppShell';
import { label, localInput, localToIso, money, when } from '../shared/serviceUtils';
import '../shared/Services.css';

const Badge = ({ status }) => (
  <span className={`svc-badge svc-st-${status}`}>{label(status)}</span>
);

export function CharterList() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    apiRequest('/charters/')
      .then((d) => setRows(Array.isArray(d) ? d : []))
      .catch((e) => { setError(e.message); setRows([]); });
  }, []);

  return (
    <AppShell>
      <div className="svc-page">
        <div className="svc-head">
          <div>
            <span className="glass-eyebrow">BUS HIRE</span>
            <h1>Your bus hire requests</h1>
            <p>Hire a whole bus for a school trip, wedding, tour or event. Tell the company what you need, they send you a price, and you pay in the app to confirm.</p>
          </div>
          <Link className="btn btn-primary" to="/passenger/charter/new"><Plus size={16} /> Request a bus</Link>
        </div>

        {error && <div className="svc-error">{error}</div>}

        {rows === null ? (
          <div className="glass-empty">Loading…</div>
        ) : !rows.length ? (
          <div className="glass-empty"><Bus size={28} /><strong>No requests yet.</strong></div>
        ) : (
          <div className="svc-list">
            {rows.map((c) => (
              <Link key={c.id} to={`/passenger/charter/${c.id}`} className="svc-card svc-item">
                <div>
                  <strong>{c.reference} · {c.purpose}</strong>
                  <span>{c.pickup_location} → {c.destination}</span>
                  <small>{c.company} · {when(c.depart_at)} · {c.passenger_count} passengers</small>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <Badge status={c.status} />
                  {c.quote_price && <strong style={{ marginTop: 6 }}>{money(c.quote_price)}</strong>}
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}

export function CharterNew() {
  const navigate = useNavigate();
  const [companies, setCompanies] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [f, setF] = useState({
    company: '', purpose: '', pickup: '', destination: '', depart: '', ret: '',
    count: '', contactName: '', contactPhone: '', notes: '',
  });
  const set = (patch) => setF((v) => ({ ...v, ...patch }));
  const [earliest] = useState(() => localInput(new Date(Date.now() + 25 * 3600 * 1000)));

  useEffect(() => {
    apiRequest('/charters/companies/')
      .then((d) => setCompanies(Array.isArray(d) ? d : []))
      .catch((e) => { setError(e.message); setCompanies([]); });
  }, []);

  const ready = f.company && f.purpose.trim() && f.pickup.trim() && f.destination.trim()
    && f.depart && Number(f.count) >= 1 && f.contactName.trim() && f.contactPhone.trim();

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError('');
    try {
      const c = await apiRequest('/charters/', {
        method: 'POST',
        body: {
          company_id: Number(f.company),
          purpose: f.purpose.trim(),
          pickup_location: f.pickup.trim(),
          destination: f.destination.trim(),
          depart_at: localToIso(f.depart),
          return_at: localToIso(f.ret),
          passenger_count: Number(f.count),
          contact_name: f.contactName.trim(),
          contact_phone: f.contactPhone.trim(),
          notes: f.notes.trim(),
        },
      });
      navigate(`/passenger/charter/${c.id}`);
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
            <Link to="/passenger/charter" className="journey-back">← Bus hire</Link>
            <h1>Request a bus</h1>
            <p>The trip can be anywhere. The company reviews your request and replies with a price, usually within a day. Nothing is charged until you accept and pay.</p>
          </div>
        </div>

        {error && <div className="svc-error">{error}</div>}

        {companies === null ? (
          <div className="glass-empty">Loading…</div>
        ) : !companies.length ? (
          <div className="glass-empty"><strong>No company is taking bus hire requests right now.</strong></div>
        ) : (
          <form className="svc-card" onSubmit={submit}>
            <div className="svc-form">
              <label className="svc-field wide">Company
                <select className="input" value={f.company} onChange={(e) => set({ company: e.target.value })}>
                  <option value="">Choose…</option>
                  {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </label>
              <label className="svc-field wide">What is the trip for?
                <input className="input" maxLength={200} value={f.purpose} onChange={(e) => set({ purpose: e.target.value })} placeholder="e.g. School trip to Nakuru" />
              </label>
              <label className="svc-field">Pickup location
                <input className="input" maxLength={255} value={f.pickup} onChange={(e) => set({ pickup: e.target.value })} />
              </label>
              <label className="svc-field">Destination
                <input className="input" maxLength={255} value={f.destination} onChange={(e) => set({ destination: e.target.value })} />
              </label>
              <label className="svc-field">Departure
                <input className="input" type="datetime-local" min={earliest} value={f.depart} onChange={(e) => set({ depart: e.target.value })} />
              </label>
              <label className="svc-field">Return (optional)
                <input className="input" type="datetime-local" min={f.depart || earliest} value={f.ret} onChange={(e) => set({ ret: e.target.value })} />
              </label>
              <label className="svc-field">Number of passengers
                <input className="input" type="number" min="1" max="200" value={f.count} onChange={(e) => set({ count: e.target.value })} />
              </label>
              <label className="svc-field">Contact name
                <input className="input" maxLength={100} value={f.contactName} onChange={(e) => set({ contactName: e.target.value })} />
              </label>
              <label className="svc-field">Contact phone
                <input className="input" type="tel" inputMode="tel" value={f.contactPhone} onChange={(e) => set({ contactPhone: e.target.value })} placeholder="07XX XXX XXX" />
              </label>
              <label className="svc-field wide">Notes (optional)
                <textarea className="input" rows="3" maxLength={1000} value={f.notes} onChange={(e) => set({ notes: e.target.value })} placeholder="Stops along the way, luggage, special needs…" />
              </label>
            </div>
            <div className="svc-actions">
              <button className="btn btn-primary" disabled={!ready || busy}>{busy ? 'Sending…' : 'Send request'}</button>
            </div>
          </form>
        )}
      </div>
    </AppShell>
  );
}

export function CharterDetail() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const [c, setC] = useState(null);
  const [error, setError] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setC(await apiRequest(`/charters/${id}/`)); } catch (e) { setError(e.message); }
  }, [id]);

  const verify = useCallback(async () => {
    setBusy(true); setError(''); setNote('');
    try {
      const data = await apiRequest(`/charters/${id}/verify/`, { method: 'POST' });
      if (data?.reference) setC(data);
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
      const d = await apiRequest(`/charters/${id}/pay/`, { method: 'POST' });
      window.location.href = d.authorization_url;
    } catch (e) { setError(e.message); setBusy(false); }
  };

  const cancel = async () => {
    setBusy(true); setError('');
    try { setC(await apiRequest(`/charters/${id}/cancel/`, { method: 'POST' })); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  return (
    <AppShell>
      <div className="svc-page">
        <div className="svc-head">
          <div>
            <Link to="/passenger/charter" className="journey-back">← Bus hire</Link>
            <h1>{c ? c.reference : 'Bus hire'}</h1>
          </div>
          {c && <Badge status={c.status} />}
        </div>

        {error && <div className="svc-error">{error}</div>}
        {note && <div className="svc-note">{note}</div>}
        {!c && !error && <div className="glass-empty">Loading…</div>}

        {c && (
          <>
            {c.status === 'requested' && (
              <div className="svc-card">
                <h3>Waiting for {c.company}</h3>
                <p className="svc-muted">The company will reply with a price. You can cancel until you pay.</p>
                <div className="svc-actions"><button className="btn btn-ghost" onClick={cancel} disabled={busy}>Cancel request</button></div>
              </div>
            )}

            {c.status === 'quoted' && (
              <div className="svc-card">
                <h3>Quote: {money(c.quote_price)}</h3>
                <p className="svc-muted">Valid until {when(c.quote_valid_until)}. Paying confirms the hire.</p>
                <div className="svc-actions">
                  <button className="btn btn-primary" onClick={pay} disabled={busy}>{busy ? 'Please wait…' : `Accept and pay ${money(c.quote_price)}`}</button>
                  <button className="btn btn-secondary" onClick={verify} disabled={busy}>I&apos;ve paid — check status</button>
                  <button className="btn btn-ghost" onClick={cancel} disabled={busy}>Cancel request</button>
                </div>
              </div>
            )}

            {c.status === 'expired' && (
              <div className="svc-card"><h3>This quote has expired</h3><p className="svc-muted">Ask {c.company} for a new one by sending another request.</p></div>
            )}

            {c.status === 'declined' && (
              <div className="svc-card"><h3>Declined</h3><p className="svc-muted">{c.decline_reason || 'The company could not take this trip.'}</p></div>
            )}

            {['confirmed', 'completed'].includes(c.status) && c.driver && (
              <div className="svc-card">
                <h3>Your bus</h3>
                <dl className="svc-dl">
                  <div><span>Driver</span><strong>{c.driver.name}</strong></div>
                  <div><span>Driver phone</span><strong>{c.driver.phone_number}</strong></div>
                  <div><span>Bus</span><strong>{c.driver.bus_number}</strong></div>
                </dl>
                {c.status === 'confirmed' && <p className="svc-muted" style={{ marginTop: 14 }}>Paid hires cannot be cancelled in the app yet. Contact support if you need a refund.</p>}
              </div>
            )}

            <div className="svc-card">
              <h3>Trip</h3>
              <dl className="svc-dl">
                <div><span>Company</span><strong>{c.company}</strong></div>
                <div><span>Purpose</span><strong>{c.purpose}</strong></div>
                <div><span>Pickup</span><strong>{c.pickup_location}</strong></div>
                <div><span>Destination</span><strong>{c.destination}</strong></div>
                <div><span>Departure</span><strong>{when(c.depart_at)}</strong></div>
                <div><span>Return</span><strong>{c.return_at ? when(c.return_at) : '—'}</strong></div>
                <div><span>Passengers</span><strong>{c.passenger_count}</strong></div>
                <div><span>Contact</span><strong>{c.contact_name} · {c.contact_phone}</strong></div>
                {c.notes && <div><span>Notes</span><strong>{c.notes}</strong></div>}
              </dl>
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
