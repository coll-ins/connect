import { useCallback, useEffect, useState } from 'react';
import { Bus as BusIcon, RefreshCw } from 'lucide-react';
import { apiRequest } from '../api';
import ValidatedInput from './ValidatedInput';
import './Fleet.css';

// Same rule as backend buses/serializers.validate_registration_number.
const PLATE = /^(K[A-Z]{2}|EV[A-Z])\d{3}[A-Z]$/;

// Same keys and seat counts as backend bookings/seats.py VEHICLES.
export const VEHICLE_TYPES = [
  { key: 'matatu_14', label: '14-seater matatu (Toyota HiAce Commuter)', seats: 14 },
  { key: 'minibus_27', label: '27-seater minibus (Isuzu NMR85)', seats: 27 },
  { key: 'minibus_33', label: '33-seater minibus (Isuzu NQR81M)', seats: 33 },
  { key: 'bus_51', label: '51-seater bus (Isuzu FTR90)', seats: 51 },
  { key: 'bus_67', label: '67-seater bus (Isuzu FVR34S)', seats: 67 },
  { key: 'other', label: 'Other (enter the seat count)', seats: null },
];

// Trip forms: most common first (33-seater default), matatus last.
const TRIP_ORDER = ['minibus_33', 'bus_51', 'bus_67', 'minibus_27', 'matatu_14'];
export const TRIP_VEHICLES = TRIP_ORDER.map((k) => VEHICLE_TYPES.find((v) => v.key === k));
export const DEFAULT_VEHICLE = TRIP_ORDER[0];

export function VehicleOptions() {
  return TRIP_VEHICLES.map((v) => <option key={v.key} value={v.key}>{v.label}</option>);
}

/* The vehicle type of the bus this driver already has on file, if any. */
export function driverVehicle(buses, driver) {
  const n = String(driver?.bus_number || '').toUpperCase().replace(/\s+/g, '');
  const bus = n && buses.find((b) =>
    [b.bus_number, b.registration_number].some((x) => String(x || '').toUpperCase().replace(/\s+/g, '') === n));
  return bus && TRIP_ORDER.includes(bus.vehicle_type) ? bus.vehicle_type : null;
}

export const busLabel = (bus) =>
  `${bus.bus_number} · ${bus.registration_number || 'no plate yet'} · ${bus.capacity} seats`;

export const inService = (bus) => bus.is_active && bus.maintenance_status === 'operational';

export function useCompanyBuses(companyId) {
  const [buses, setBuses] = useState([]);
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    if (!companyId) return;
    setError('');
    try {
      setBuses(await apiRequest(`/buses/?company_id=${companyId}`, { silent: true }) || []);
    } catch (e) {
      setError(e.message || 'Could not load buses.');
    }
  }, [companyId]);
  useEffect(() => { load(); }, [load]);
  return { buses, error, reload: load };
}

/* Options for a <select>: only buses that can run a trip. */
export function BusOptions({ buses, placeholder = 'Choose a bus' }) {
  const usable = buses.filter(inService);
  return (
    <>
      <option value="">{usable.length ? placeholder : 'No buses in service: add one under Buses & seats'}</option>
      {usable.map((b) => <option key={b.id} value={b.id}>{busLabel(b)}</option>)}
    </>
  );
}

/* Put a bus on a trip, or swap it. The server refuses a bus with fewer
   seats than are already booked. */
export function TripBusPicker({ trip, buses, onSaved }) {
  const [value, setValue] = useState(String(trip.bus || ''));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const st = String(trip.status || '').toLowerCase();
  if (!['scheduled', 'boarding'].includes(st)) return null;
  const dirty = value && Number(value) !== Number(trip.bus);

  const save = async () => {
    setBusy(true);
    setMsg('');
    try {
      const res = await apiRequest(`/companies/trips/${trip.id}/bus/`, {
        method: 'PATCH',
        body: { bus_id: Number(value) },
      });
      setMsg('Bus saved');
      onSaved?.(res?.trip);
    } catch (e) {
      setMsg(e?.message || 'Could not save');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fleet-trip-bus">
      {!trip.bus && <small className="fleet-warn">No bus assigned. Seats can't exceed the real bus: pick one.</small>}
      <div className="op-routes-capacity">
        <select value={value} onChange={(e) => setValue(e.target.value)} aria-label={`Bus for trip ${trip.id}`}>
          <BusOptions buses={buses} />
        </select>
        <button type="button" onClick={save} disabled={!dirty || busy}>
          {busy ? 'Saving…' : trip.bus ? 'Change bus' : 'Assign bus'}
        </button>
      </div>
      {msg && <small role="status">{msg}</small>}
    </div>
  );
}

const EMPTY = { registration_number: '', bus_number: '', vehicle_type: 'matatu_14', capacity: '' };

/* The company's buses: what each one is and how many seats it really has. */
export function FleetManager({ companyId, canEdit }) {
  const { buses, error, reload } = useCompanyBuses(companyId);
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const type = VEHICLE_TYPES.find((t) => t.key === form.vehicle_type);

  const add = async (e) => {
    e.preventDefault();
    setBusy(true);
    setMsg('');
    try {
      await apiRequest('/buses/', {
        method: 'POST',
        body: {
          registration_number: form.registration_number,
          bus_number: form.bus_number,
          vehicle_type: form.vehicle_type,
          ...(type.seats ? {} : { capacity: Number(form.capacity) }),
        },
      });
      setForm(EMPTY);
      setMsg('Bus added.');
      reload();
    } catch (err) {
      setMsg(err.message || 'Could not add the bus.');
    } finally {
      setBusy(false);
    }
  };

  const setStatus = async (bus, maintenance_status) => {
    try {
      await apiRequest(`/buses/${bus.id}/`, { method: 'PATCH', body: { maintenance_status } });
      reload();
    } catch (err) {
      setMsg(err.message);
    }
  };

  return (
    <section className="fleet" aria-labelledby="fleet-title">
      <div className="fleet-head">
        <h2 id="fleet-title">Buses</h2>
        <p>Every trip runs on one of these. Its seats are the bus's real seats, so a trip can't sell more. Need more seats at the same time? Add another trip with a second bus.</p>
      </div>

      {error && (
        <p className="fleet-warn" role="alert">
          {error} <button type="button" className="fleet-link" onClick={reload}><RefreshCw size={14} aria-hidden="true" /> Retry</button>
        </p>
      )}

      {buses.length === 0 && !error && <p className="fleet-empty">No buses yet. Add your first bus below, then pick it when you create a trip.</p>}

      <ul className="fleet-list">
        {buses.map((b) => (
          <li key={b.id} className="fleet-row">
            <BusIcon size={18} aria-hidden="true" />
            <div className="fleet-row-main">
              <strong>{b.bus_number} · {b.registration_number || 'no plate yet'}</strong>
              <span>{b.vehicle_label}{b.vehicle_type === 'other' ? `, ${b.capacity} seats` : ''}</span>
              {!b.plan_verified && (
                <small>
                  {b.vehicle_type === 'other'
                    ? 'No published seat plan for this bus: seat numbers are real, positions are a plain 2+2 plan.'
                    : 'Seat positions approximate: no published drawing for this body.'}
                </small>
              )}
            </div>
            {canEdit ? (
              <select
                value={b.maintenance_status}
                onChange={(e) => setStatus(b, e.target.value)}
                aria-label={`Status of bus ${b.bus_number}`}
              >
                <option value="operational">In service</option>
                <option value="maintenance">Under maintenance</option>
                <option value="out_of_service">Out of service</option>
              </select>
            ) : (
              <span className="fleet-status">{inService(b) ? 'In service' : 'Not in service'}</span>
            )}
          </li>
        ))}
      </ul>

      {canEdit && (
        <form className="company-form-grid fleet-form" onSubmit={add}>
          <label className="company-field">
            <span>Number plate</span>
            <ValidatedInput required value={form.registration_number} autoComplete="off" placeholder="KDK 404M"
              maxLength={9} autoCapitalize="characters"
              hint="Exactly as on the bus: 3 letters, 3 numbers, 1 letter, e.g. KDK 404M."
              error={PLATE.test(form.registration_number.replace(/\s+/g, '').toUpperCase()) ? '' : 'Enter the number plate exactly as on the bus, e.g. KDK 404M.'}
              onChange={(e) => setForm({ ...form, registration_number: e.target.value })} />
          </label>
          <label className="company-field">
            <span>Fleet number</span>
            <ValidatedInput required value={form.bus_number} autoComplete="off" placeholder="SM-12"
              maxLength={20} hint="Your company's own number for this bus, as painted on it, e.g. SM-12."
              onChange={(e) => setForm({ ...form, bus_number: e.target.value })} />
          </label>
          <label className="company-field">
            <span>Vehicle</span>
            <select value={form.vehicle_type} onChange={(e) => setForm({ ...form, vehicle_type: e.target.value })}>
              {VEHICLE_TYPES.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
            </select>
          </label>
          {type.seats ? (
            <p className="fleet-seats">{type.seats} passenger seats, from the maker's seat plan.</p>
          ) : (
            <label className="company-field">
              <span>Passenger seats (count them on the bus)</span>
              <input required type="number" inputMode="numeric" min="1" max="100" value={form.capacity}
                onChange={(e) => setForm({ ...form, capacity: e.target.value })} />
            </label>
          )}
          <button type="submit" className="fleet-add" disabled={busy}>{busy ? 'Adding…' : 'Add bus'}</button>
          {msg && <small role="status">{msg}</small>}
        </form>
      )}
    </section>
  );
}
