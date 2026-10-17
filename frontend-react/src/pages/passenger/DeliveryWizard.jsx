import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Check } from 'lucide-react';

import { apiRequest } from '../../api';
import AppShell from '../../components/layout/AppShell';
import { label, money, when } from '../shared/serviceUtils';
import '../shared/Services.css';

const STEPS = ['Company', 'Route', 'Bus', 'Stops', 'Parcel', 'Receiver'];
const SIZE_INFO = {
  small: ['Small', 'Fits in a bag'],
  medium: ['Medium', 'A box'],
  large: ['Large', 'Bulky item'],
};

function Pick({ selected, onClick, title, sub, meta }) {
  return (
    <button type="button" className={`svc-pick ${selected ? 'selected' : ''}`} onClick={onClick}>
      <span className="svc-pick-main">
        <strong>{title}</strong>
        {sub && <small>{sub}</small>}
      </span>
      {meta && <span className="svc-pick-meta">{meta}</span>}
      {selected && <Check size={18} />}
    </button>
  );
}

export function DeliveryNew() {
  const navigate = useNavigate();
  const [options, setOptions] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState(0);
  const [f, setF] = useState({
    company: '', route: '', trip: '', pickup: '', dropoff: '', size: '',
    description: '', receiverName: '', receiverPhone: '', ok: false,
  });

  useEffect(() => {
    apiRequest('/deliveries/options/')
      .then((d) => setOptions(Array.isArray(d) ? d : []))
      .catch((e) => { setError(e.message); setOptions([]); });
  }, []);

  useEffect(() => { window.scrollTo({ top: 0 }); }, [step]);

  const company = options?.find((c) => String(c.id) === f.company);
  const route = company?.routes.find((r) => String(r.id) === f.route);
  const trip = route?.trips.find((t) => String(t.id) === f.trip);
  const stages = route?.stages || [];
  const pickupStage = stages.find((s) => String(s.id) === f.pickup);
  const dropStage = stages.find((s) => String(s.id) === f.dropoff);
  const dropoffs = pickupStage ? stages.filter((s) => s.order > pickupStage.order) : [];
  const price = route && f.size ? route.rates[f.size] : null;

  const pick = (patch, next) => {
    setF((v) => ({ ...v, ...patch }));
    setError('');
    if (next !== undefined) setStep(next);
  };
  const back = () => (step > 0 ? setStep(step - 1) : navigate('/passenger/delivery'));

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
            <button type="button" className="btn btn-ghost" onClick={back}>
              <ArrowLeft size={16} /> {step === 0 ? 'Parcels' : 'Back'}
            </button>
            <h1>Send a parcel</h1>
            <p>Step {step + 1} of {STEPS.length}: {STEPS[step]}</p>
          </div>
        </div>

        <ol className="svc-steps">
          {STEPS.map((s, i) => (
            <li key={s} className={i < step ? 'done' : i === step ? 'active' : ''} title={s} />
          ))}
        </ol>

        {error && <div className="svc-error">{error}</div>}

        {options === null ? (
          <div className="glass-empty">Loading…</div>
        ) : !options.length ? (
          <div className="glass-empty"><strong>No company is carrying parcels right now.</strong></div>
        ) : (
          <div className="svc-card">
            {step === 0 && (
              <>
                <h2 className="svc-q">Which company will carry your parcel?</h2>
                <div className="svc-pick-grid">
                  {options.map((c) => (
                    <Pick key={c.id} title={c.name} sub={`${c.routes.length} route${c.routes.length === 1 ? '' : 's'}`}
                      selected={f.company === String(c.id)}
                      onClick={() => pick({ company: String(c.id), route: '', trip: '', pickup: '', dropoff: '', size: '' }, 1)} />
                  ))}
                </div>
              </>
            )}

            {step === 1 && company && (
              <>
                <h2 className="svc-q">Which route?</h2>
                <div className="svc-pick-grid">
                  {company.routes.map((r) => {
                    const prices = Object.values(r.rates).map(Number);
                    return (
                      <Pick key={r.id} title={r.name}
                        sub={`${r.trips.length} upcoming bus${r.trips.length === 1 ? '' : 'es'}`}
                        meta={prices.length ? `from ${money(Math.min(...prices))}` : ''}
                        selected={f.route === String(r.id)}
                        onClick={() => pick({ route: String(r.id), trip: '', pickup: '', dropoff: '', size: '' }, 2)} />
                    );
                  })}
                </div>
              </>
            )}

            {step === 2 && route && (
              <>
                <h2 className="svc-q">Which bus will take it?</h2>
                <div className="svc-pick-grid">
                  {route.trips.map((t) => (
                    <Pick key={t.id} title={when(t.departure_at)} sub={`Bus ${t.bus_number}`}
                      selected={f.trip === String(t.id)}
                      onClick={() => pick({ trip: String(t.id) }, 3)} />
                  ))}
                </div>
              </>
            )}

            {step === 3 && route && (
              <>
                <h2 className="svc-q">Where will you hand the parcel to the driver?</h2>
                <div className="svc-pick-grid">
                  {stages.slice(0, -1).map((s) => (
                    <Pick key={s.id} title={s.name} selected={f.pickup === String(s.id)}
                      onClick={() => pick({ pickup: String(s.id), dropoff: '' })} />
                  ))}
                </div>
                {pickupStage && (
                  <>
                    <h2 className="svc-q">Where will the receiver collect it?</h2>
                    <div className="svc-pick-grid">
                      {dropoffs.map((s) => (
                        <Pick key={s.id} title={s.name} selected={f.dropoff === String(s.id)}
                          onClick={() => pick({ dropoff: String(s.id) })} />
                      ))}
                    </div>
                  </>
                )}
                <div className="svc-actions">
                  <button type="button" className="btn btn-primary" disabled={!f.pickup || !f.dropoff} onClick={() => setStep(4)}>Next</button>
                </div>
              </>
            )}

            {step === 4 && route && (
              <>
                <h2 className="svc-q">How big is the parcel?</h2>
                <div className="svc-pick-grid">
                  {Object.keys(route.rates).map((k) => (
                    <Pick key={k} title={SIZE_INFO[k]?.[0] || label(k)} sub={SIZE_INFO[k]?.[1]}
                      meta={money(route.rates[k])} selected={f.size === k}
                      onClick={() => pick({ size: k })} />
                  ))}
                </div>
                <label className="svc-field">What is in the parcel?
                  <input className="input" maxLength={200} value={f.description}
                    onChange={(e) => pick({ description: e.target.value })} placeholder="e.g. Documents" />
                </label>
                <div className="svc-actions">
                  <button type="button" className="btn btn-primary" disabled={!f.size || !f.description.trim()} onClick={() => setStep(5)}>Next</button>
                </div>
              </>
            )}

            {step === 5 && route && (
              <form onSubmit={submit}>
                <h2 className="svc-q">Who is receiving it?</h2>
                <div className="svc-form">
                  <label className="svc-field">Receiver&apos;s name
                    <input className="input" maxLength={100} value={f.receiverName}
                      onChange={(e) => pick({ receiverName: e.target.value })} />
                  </label>
                  <label className="svc-field">Receiver&apos;s phone
                    <input className="input" type="tel" inputMode="tel" value={f.receiverPhone}
                      onChange={(e) => pick({ receiverPhone: e.target.value })} placeholder="07XX XXX XXX" />
                  </label>
                </div>

                <h3 style={{ margin: '22px 0 12px' }}>Summary</h3>
                <dl className="svc-dl">
                  <div><span>Company</span><strong>{company?.name}</strong></div>
                  <div><span>Route</span><strong>{route.name}</strong></div>
                  <div><span>Departure</span><strong>{trip ? when(trip.departure_at) : '—'}</strong></div>
                  <div><span>From</span><strong>{pickupStage?.name}</strong></div>
                  <div><span>To</span><strong>{dropStage?.name}</strong></div>
                  <div><span>Size</span><strong>{label(f.size)}</strong></div>
                  <div><span>Contents</span><strong>{f.description}</strong></div>
                  <div><span>Price</span><strong>{price ? money(price) : '—'}</strong></div>
                </dl>

                <label className="svc-check" style={{ marginTop: 18 }}>
                  <input type="checkbox" checked={f.ok} onChange={(e) => pick({ ok: e.target.checked })} />
                  <span>I confirm the parcel contains no prohibited items (weapons, drugs, flammables, live animals, cash). I have the receiver&apos;s permission to share their name and phone number with CONNECT and the transport company for this delivery.</span>
                </label>

                <div className="svc-actions">
                  <button className="btn btn-primary"
                    disabled={busy || !f.receiverName.trim() || !f.receiverPhone.trim() || !f.ok}>
                    {busy ? 'Creating…' : `Confirm and continue to payment${price ? ` · ${money(price)}` : ''}`}
                  </button>
                </div>
              </form>
            )}
          </div>
        )}
      </div>
    </AppShell>
  );
}
