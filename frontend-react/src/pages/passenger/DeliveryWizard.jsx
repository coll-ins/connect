import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowLeft, Check, Package } from 'lucide-react';

import { apiRequest } from '../../api';
import AppShell from '../../components/layout/AppShell';
import { label, money, when } from '../shared/serviceUtils';
import FieldNote from '../../components/FieldNote';
import { checkName, checkPhone, checkText, NAME_HINT, PHONE_HINT } from '../../utils/inputRules';
import useHistoryStep from '../../hooks/useHistoryStep';
import '../shared/Services.css';

const STEPS = ['Places', 'Bus', 'Parcel', 'Receiver'];
const key = (name) => name.trim().toLowerCase();
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
  const [step, setStep, stepBack] = useHistoryStep();
  const [f, setF] = useState({
    from: '', to: '', query: '', company: '', route: '', trip: '', pickup: '', dropoff: '', size: '',
    description: '', receiverName: '', receiverPhone: '', ok: false,
  });
  const errDesc = checkText(f.description, 'what is in the parcel', { maxLength: 200 });
  const errName = checkName(f.receiverName, "the receiver's name");
  const errPhone = checkPhone(f.receiverPhone);

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
  const price = route && f.size ? route.rates[f.size] : null;

  // Senders know where the parcel goes, not which company or route serves
  // it: every route that passes "from" and later "to" is a match, across all
  // companies, and its buses are offered soonest first.
  const legs = useMemo(() => {
    const out = [];
    (options || []).forEach((c) => c.routes.forEach((r) => {
      r.stages.forEach((a, i) => r.stages.slice(i + 1).forEach((b) => {
        out.push({ company: c, route: r, pickup: a, dropoff: b });
      }));
    }));
    return out;
  }, [options]);
  const names = (list) => [...new Map(list.map((n) => [key(n), n])).values()]
    .sort((a, b) => a.localeCompare(b));
  const q = key(f.query);
  const froms = names(legs.map((l) => l.pickup.name)).filter((n) => !q || key(n).includes(q));
  const tos = f.from ? names(legs.filter((l) => key(l.pickup.name) === key(f.from)).map((l) => l.dropoff.name)) : [];
  const departures = (f.from && f.to ? legs.filter(
    (l) => key(l.pickup.name) === key(f.from) && key(l.dropoff.name) === key(f.to),
  ) : []).flatMap((l) => l.route.trips.map((t) => ({ ...l, trip: t })))
    .sort((a, b) => new Date(a.trip.departure_at) - new Date(b.trip.departure_at));

  const pick = (patch, next) => {
    setF((v) => ({ ...v, ...patch }));
    setError('');
    if (next !== undefined) setStep(next);
  };
  const back = () => (step > 0 ? stepBack() : navigate('/passenger/delivery'));

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
            <button type="button" className="journey-back" onClick={back}>
              <ArrowLeft size={18} aria-hidden="true" /> {step === 0 ? 'Parcels' : 'Back'}
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
          <div className="glass-empty"><Package size={28} /><strong>No company is carrying parcels right now.</strong><span>Parcels open on a route once a company sets its parcel rates.</span><Link to="/passenger/delivery" className="glass-empty-action">Back to parcels</Link></div>
        ) : (
          <div className="svc-card">
            {step === 0 && (
              <>
                <h2 className="svc-q">Where will you hand the parcel to the bus?</h2>
                <label className="svc-field">Find a stage
                  <input className="input" maxLength={60} value={f.query} placeholder="e.g. Kencom or Rongai"
                    onChange={(e) => pick({ query: e.target.value })} />
                </label>
                <div className="svc-pick-grid">
                  {froms.map((n) => (
                    <Pick key={n} title={n} selected={key(f.from) === key(n)}
                      onClick={() => pick({ from: n, to: '', trip: '', size: '' })} />
                  ))}
                </div>
                {!froms.length && <p className="muted">No stage matches “{f.query}”. Try a shorter name.</p>}
                {f.from && (
                  <>
                    <h2 className="svc-q">Where will the receiver collect it?</h2>
                    <div className="svc-pick-grid">
                      {tos.map((n) => (
                        <Pick key={n} title={n} selected={key(f.to) === key(n)}
                          onClick={() => pick({ to: n, trip: '', size: '' }, 1)} />
                      ))}
                    </div>
                  </>
                )}
              </>
            )}

            {step === 1 && f.from && f.to && (
              <>
                <h2 className="svc-q">Which bus will take it?</h2>
                <p className="muted">{f.from} to {f.to}. The soonest bus is first.</p>
                <div className="svc-pick-grid">
                  {departures.map((d) => (
                    <Pick key={`${d.route.id}-${d.trip.id}`} title={when(d.trip.departure_at)}
                      sub={`${d.company.name} · ${d.route.name} · Bus ${d.trip.bus_number}`}
                      selected={f.trip === String(d.trip.id)}
                      onClick={() => pick({
                        company: String(d.company.id), route: String(d.route.id), trip: String(d.trip.id),
                        pickup: String(d.pickup.id), dropoff: String(d.dropoff.id), size: '',
                      }, 2)} />
                  ))}
                </div>
                {!departures.length && <p className="muted">No bus is scheduled between these stages yet. Go back and pick other stages.</p>}
              </>
            )}

            {step === 2 && route && (
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
                    aria-describedby="pc-desc" aria-invalid={Boolean(f.description.trim() && errDesc)}
                    onChange={(e) => pick({ description: e.target.value })} placeholder="e.g. Documents in an envelope" />
                  <FieldNote id="pc-desc" value={f.description} error={errDesc}
                    hint="Say what is inside in plain words. The driver checks it matches when collecting." />
                </label>
                <div className="svc-actions">
                  <button type="button" className="btn btn-primary" disabled={!f.size || Boolean(errDesc)} onClick={() => setStep(3)}>Next</button>
                </div>
              </>
            )}

            {step === 3 && route && (
              <form onSubmit={submit}>
                <h2 className="svc-q">Who is receiving it?</h2>
                <div className="svc-form">
                  <label className="svc-field">Receiver&apos;s name
                    <input className="input" maxLength={100} value={f.receiverName} placeholder="e.g. Collins Otieno"
                      aria-describedby="pc-name" aria-invalid={Boolean(f.receiverName.trim() && errName)}
                      onChange={(e) => pick({ receiverName: e.target.value })} />
                    <FieldNote id="pc-name" value={f.receiverName} error={errName}
                      hint={`As on their ID: the driver checks it at handover. ${NAME_HINT}`} />
                  </label>
                  <label className="svc-field">Receiver&apos;s phone
                    <input className="input" type="tel" inputMode="tel" autoComplete="off" maxLength={16} value={f.receiverPhone}
                      aria-describedby="pc-phone" aria-invalid={Boolean(f.receiverPhone.trim() && errPhone)}
                      onChange={(e) => pick({ receiverPhone: e.target.value })} placeholder="07XX XXX XXX" />
                    <FieldNote id="pc-phone" value={f.receiverPhone} error={errPhone}
                      hint={`The driver calls this number on arrival. ${PHONE_HINT}`} />
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
                    disabled={busy || Boolean(errName) || Boolean(errPhone) || !f.ok}>
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
