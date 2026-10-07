import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Check } from 'lucide-react';

import { apiRequest } from '../../api';
import AppShell from '../../components/layout/AppShell';
import { localInput, localToIso, when } from '../shared/serviceUtils';
import '../shared/Services.css';

const STEPS = ['Company', 'Trip', 'When', 'Contact', 'Review'];

export function CharterNew() {
  const navigate = useNavigate();
  const [companies, setCompanies] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState(0);
  const [f, setF] = useState({
    company: '', purpose: '', pickup: '', destination: '', depart: '', ret: '',
    count: '', contactName: '', contactPhone: '', notes: '',
  });
  const earliest = localInput(new Date(Date.now() + 25 * 3600 * 1000));

  useEffect(() => {
    apiRequest('/charters/companies/')
      .then((d) => setCompanies(Array.isArray(d) ? d : []))
      .catch((e) => { setError(e.message); setCompanies([]); });
  }, []);

  useEffect(() => { window.scrollTo({ top: 0 }); }, [step]);

  const set = (patch) => { setF((v) => ({ ...v, ...patch })); setError(''); };
  const company = companies?.find((c) => String(c.id) === f.company);
  const back = () => (step > 0 ? setStep(step - 1) : navigate('/passenger/charter'));

  const tripOk = f.purpose.trim() && f.pickup.trim() && f.destination.trim();
  const whenOk = f.depart && (!f.ret || f.ret > f.depart);
  const contactOk = Number(f.count) >= 1 && f.contactName.trim() && f.contactPhone.trim();

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

  const Next = ({ ok, to }) => (
    <div className="svc-actions">
      <button type="button" className="btn btn-primary" disabled={!ok} onClick={() => setStep(to)}>Next</button>
    </div>
  );

  return (
    <AppShell>
      <div className="svc-page">
        <div className="svc-head">
          <div>
            <button type="button" className="btn btn-ghost" onClick={back}>
              <ArrowLeft size={16} /> {step === 0 ? 'Bus hire' : 'Back'}
            </button>
            <h1>Request a bus</h1>
            <p>Step {step + 1} of {STEPS.length}: {STEPS[step]}. Nothing is charged until you accept the company&apos;s price and pay.</p>
          </div>
        </div>

        <ol className="svc-steps">
          {STEPS.map((s, i) => (
            <li key={s} className={i < step ? 'done' : i === step ? 'active' : ''} title={s} />
          ))}
        </ol>

        {error && <div className="svc-error">{error}</div>}

        {companies === null ? (
          <div className="glass-empty">Loading…</div>
        ) : !companies.length ? (
          <div className="glass-empty"><strong>No company is taking bus hire requests right now.</strong></div>
        ) : (
          <div className="svc-card">
            {step === 0 && (
              <>
                <h2 className="svc-q">Which company do you want to hire from?</h2>
                <div className="svc-pick-grid">
                  {companies.map((c) => (
                    <button key={c.id} type="button"
                      className={`svc-pick ${f.company === String(c.id) ? 'selected' : ''}`}
                      onClick={() => { set({ company: String(c.id) }); setStep(1); }}>
                      <span className="svc-pick-main"><strong>{c.name}</strong></span>
                      {f.company === String(c.id) && <Check size={18} />}
                    </button>
                  ))}
                </div>
              </>
            )}

            {step === 1 && (
              <>
                <h2 className="svc-q">Tell {company?.name} about the trip</h2>
                <div className="svc-form">
                  <label className="svc-field wide">What is the trip for?
                    <input className="input" maxLength={200} value={f.purpose}
                      onChange={(e) => set({ purpose: e.target.value })} placeholder="e.g. School trip to Nakuru" />
                  </label>
                  <label className="svc-field">Pickup location
                    <input className="input" maxLength={255} value={f.pickup}
                      onChange={(e) => set({ pickup: e.target.value })} />
                  </label>
                  <label className="svc-field">Destination
                    <input className="input" maxLength={255} value={f.destination}
                      onChange={(e) => set({ destination: e.target.value })} />
                  </label>
                </div>
                <Next ok={tripOk} to={2} />
              </>
            )}

            {step === 2 && (
              <>
                <h2 className="svc-q">When do you need the bus?</h2>
                <div className="svc-form">
                  <label className="svc-field">Departure
                    <input className="input" type="datetime-local" min={earliest} value={f.depart}
                      onChange={(e) => set({ depart: e.target.value })} />
                  </label>
                  <label className="svc-field">Return (optional)
                    <input className="input" type="datetime-local" min={f.depart || earliest} value={f.ret}
                      onChange={(e) => set({ ret: e.target.value })} />
                  </label>
                </div>
                {f.ret && f.depart && f.ret <= f.depart && (
                  <div className="svc-error" style={{ marginTop: 12 }}>The return must be after the departure.</div>
                )}
                <Next ok={whenOk} to={3} />
              </>
            )}

            {step === 3 && (
              <>
                <h2 className="svc-q">Who should the company contact?</h2>
                <div className="svc-form">
                  <label className="svc-field">Number of passengers
                    <input className="input" type="number" min="1" max="200" value={f.count}
                      onChange={(e) => set({ count: e.target.value })} />
                  </label>
                  <label className="svc-field">Contact name
                    <input className="input" maxLength={100} value={f.contactName}
                      onChange={(e) => set({ contactName: e.target.value })} />
                  </label>
                  <label className="svc-field">Contact phone
                    <input className="input" type="tel" inputMode="tel" value={f.contactPhone}
                      onChange={(e) => set({ contactPhone: e.target.value })} placeholder="07XX XXX XXX" />
                  </label>
                  <label className="svc-field wide">Notes (optional)
                    <textarea className="input" rows="3" maxLength={1000} value={f.notes}
                      onChange={(e) => set({ notes: e.target.value })}
                      placeholder="Stops along the way, luggage, special needs…" />
                  </label>
                </div>
                <Next ok={contactOk} to={4} />
              </>
            )}

            {step === 4 && (
              <form onSubmit={submit}>
                <h2 className="svc-q">Check your request</h2>
                <dl className="svc-dl">
                  <div><span>Company</span><strong>{company?.name}</strong></div>
                  <div><span>Purpose</span><strong>{f.purpose}</strong></div>
                  <div><span>Pickup</span><strong>{f.pickup}</strong></div>
                  <div><span>Destination</span><strong>{f.destination}</strong></div>
                  <div><span>Departure</span><strong>{when(localToIso(f.depart))}</strong></div>
                  <div><span>Return</span><strong>{f.ret ? when(localToIso(f.ret)) : '—'}</strong></div>
                  <div><span>Passengers</span><strong>{f.count}</strong></div>
                  <div><span>Contact</span><strong>{f.contactName} · {f.contactPhone}</strong></div>
                  {f.notes && <div><span>Notes</span><strong>{f.notes}</strong></div>}
                </dl>
                <p className="svc-muted" style={{ marginTop: 16 }}>
                  The company will reply with a price. You only pay if you accept it.
                </p>
                <div className="svc-actions">
                  <button className="btn btn-primary" disabled={busy}>{busy ? 'Sending…' : 'Send request'}</button>
                </div>
              </form>
            )}
          </div>
        )}
      </div>
    </AppShell>
  );
}
