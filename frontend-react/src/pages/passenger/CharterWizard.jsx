import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowLeft, Bus, Check } from 'lucide-react';

import { apiRequest } from '../../api';
import AppShell from '../../components/layout/AppShell';
import { localInput, localToIso, when } from '../shared/serviceUtils';
import FieldNote from '../../components/FieldNote';
import { checkName, checkPhone, checkPlace, checkText, NAME_HINT, PHONE_HINT } from '../../utils/inputRules';
import '../shared/Services.css';

const STEPS = ['Company', 'Trip', 'When', 'Contact', 'Review'];

function Next({ ok, onNext }) {
  return (
    <div className="svc-actions">
      <button
        type="button"
        className="btn btn-primary"
        disabled={!ok}
        onClick={onNext}
      >
        Next
      </button>
    </div>
  );
}

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
  const [earliest] = useState(() => localInput(new Date(Date.now() + 25 * 3600 * 1000)));

  useEffect(() => {
    apiRequest('/charters/companies/')
      .then((d) => setCompanies(Array.isArray(d) ? d : []))
      .catch((e) => { setError(e.message); setCompanies([]); });
  }, []);

  useEffect(() => { window.scrollTo({ top: 0 }); }, [step]);

  const set = (patch) => { setF((v) => ({ ...v, ...patch })); setError(''); };
  const company = companies?.find((c) => String(c.id) === f.company);
  const back = () => (step > 0 ? setStep(step - 1) : navigate('/passenger/charter'));

  const err = {
    purpose: checkText(f.purpose, 'the purpose of the hire', { maxLength: 200 }),
    pickup: checkPlace(f.pickup, 'the pickup location', { maxLength: 255 }),
    destination: checkPlace(f.destination, 'the destination', { maxLength: 255, example: 'e.g. Naivasha or Mombasa' }),
    contactName: checkName(f.contactName, 'the contact name'),
    contactPhone: checkPhone(f.contactPhone),
    notes: checkText(f.notes, 'the notes', { required: false }),
  };
  const tripOk = !err.purpose && !err.pickup && !err.destination;
  const whenOk = f.depart && (!f.ret || f.ret > f.depart);
  const contactOk = Number(f.count) >= 1 && Number(f.count) <= 200
    && !err.contactName && !err.contactPhone && !err.notes;

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
          <div className="glass-empty"><Bus size={28} /><strong>No company is taking bus hire requests right now.</strong><span>Companies switch bus hire on from their dashboard. Your past requests stay under Bus hire.</span><Link to="/passenger/charter" className="glass-empty-action">Back to bus hire</Link></div>
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
                {!companies.length && <p className="muted">No company takes bus hire requests right now. Check back later.</p>}
              </>
            )}

            {step === 1 && (
              <>
                <h2 className="svc-q">Tell {company?.name} about the trip</h2>
                <div className="svc-form">
                  <label className="svc-field wide">What is the trip for?
                    <input className="input" maxLength={200} value={f.purpose}
                      aria-describedby="ch-purpose" aria-invalid={Boolean(f.purpose.trim() && err.purpose)}
                      onChange={(e) => set({ purpose: e.target.value })} placeholder="e.g. School trip to Nakuru" />
                    <FieldNote id="ch-purpose" value={f.purpose} error={err.purpose}
                      hint="Say what the trip is, in plain words. The company reads this to quote you." />
                  </label>
                  <label className="svc-field">Pickup location
                    <input className="input" maxLength={255} value={f.pickup} placeholder="e.g. Kencom, Moi Avenue"
                      aria-describedby="ch-pickup" aria-invalid={Boolean(f.pickup.trim() && err.pickup)}
                      onChange={(e) => set({ pickup: e.target.value })} />
                    <FieldNote id="ch-pickup" value={f.pickup} error={err.pickup}
                      hint="Where the bus should collect you: a stage, building or road the driver can find." />
                  </label>
                  <label className="svc-field">Destination
                    <input className="input" maxLength={255} value={f.destination} placeholder="e.g. Naivasha"
                      aria-describedby="ch-dest" aria-invalid={Boolean(f.destination.trim() && err.destination)}
                      onChange={(e) => set({ destination: e.target.value })} />
                    <FieldNote id="ch-dest" value={f.destination} error={err.destination}
                      hint="The town or place you are going to." />
                  </label>
                </div>
                <Next ok={tripOk} onNext={() => setStep(2)} />
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
                <Next ok={whenOk} onNext={() => setStep(3)} />
              </>
            )}

            {step === 3 && (
              <>
                <h2 className="svc-q">Who should the company contact?</h2>
                <div className="svc-form">
                  <label className="svc-field">Number of passengers
                    <input className="input" type="number" inputMode="numeric" min="1" max="200" step="1" value={f.count}
                      aria-describedby="ch-count" onChange={(e) => set({ count: e.target.value })} />
                    <FieldNote id="ch-count" value={f.count}
                      error={Number(f.count) >= 1 && Number(f.count) <= 200 ? '' : 'Enter a whole number from 1 to 200.'}
                      hint="Everyone travelling, adults and children, from 1 to 200." />
                  </label>
                  <label className="svc-field">Contact name
                    <input className="input" maxLength={100} value={f.contactName} placeholder="e.g. Collins Otieno"
                      autoComplete="name" aria-describedby="ch-name" aria-invalid={Boolean(f.contactName.trim() && err.contactName)}
                      onChange={(e) => set({ contactName: e.target.value })} />
                    <FieldNote id="ch-name" value={f.contactName} error={err.contactName}
                      hint={`The person the company should talk to. ${NAME_HINT}`} />
                  </label>
                  <label className="svc-field">Contact phone
                    <input className="input" type="tel" inputMode="tel" autoComplete="tel" maxLength={16} value={f.contactPhone}
                      aria-describedby="ch-phone" aria-invalid={Boolean(f.contactPhone.trim() && err.contactPhone)}
                      onChange={(e) => set({ contactPhone: e.target.value })} placeholder="07XX XXX XXX" />
                    <FieldNote id="ch-phone" value={f.contactPhone} error={err.contactPhone}
                      hint={`The company calls this number about the hire. ${PHONE_HINT}`} />
                  </label>
                  <label className="svc-field wide">Notes (optional)
                    <textarea className="input" rows="3" maxLength={1000} value={f.notes}
                      aria-describedby="ch-notes" aria-invalid={Boolean(f.notes.trim() && err.notes)}
                      onChange={(e) => set({ notes: e.target.value })}
                      placeholder="Stops along the way, luggage, special needs…" />
                    <FieldNote id="ch-notes" value={f.notes} error={err.notes}
                      hint="Anything the company needs to know to plan the trip. Up to 1000 characters." />
                  </label>
                </div>
                <Next ok={contactOk} onNext={() => setStep(4)} />
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
