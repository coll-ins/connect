import { useCallback, useEffect, useState } from 'react';
import { Check, Lock, RefreshCw } from 'lucide-react';
import { apiRequest } from '../api';
import './SeatMap.css';

const LABEL = {
  free: 'free', held: 'held, awaiting payment', booked: 'booked',
  boarded: 'boarded', blocked: 'blocked by the operator',
};

/*
  The bus seen from above, front at the top. Kenya drives on the left, so the
  driver sits front right. Layout and seat states come from the server.
  mode: 'pick'   passenger chooses up to `max` free seats (selected/onChange)
        'view'   driver: read-only, with names
        'manage' operator: tap a free seat to block it, a blocked one to free it
*/
export default function SeatMap({ tripId, mode = 'view', selected = [], onChange, max = 1, refreshKey = 0 }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [busySeat, setBusySeat] = useState(null);

  const load = useCallback(async () => {
    setError('');
    try {
      setData(await apiRequest(`/bookings/trips/${tripId}/seat-map/`, { silent: true }));
    } catch (e) {
      setError(e.message || 'Could not load the seats.');
    }
  }, [tripId]);

  useEffect(() => { load(); }, [load, refreshKey]);

  if (error) {
    return (
      <div className="seatmap-msg" role="alert">
        {error} <button type="button" className="seatmap-retry" onClick={load}><RefreshCw size={16} aria-hidden="true" /> Retry</button>
      </div>
    );
  }
  if (!data) return <div className="seatmap-msg">Loading seats…</div>;

  const byNo = Object.fromEntries(data.seats.map((s) => [s.no, s]));
  const picked = new Set(selected);
  const cols = data.layout[0]?.length || 1;

  const tap = async (seat) => {
    if (mode === 'pick') {
      if (seat.state !== 'free') return;
      const next = picked.has(seat.no)
        ? selected.filter((n) => n !== seat.no)
        : max === 1 ? [seat.no] : selected.length < max ? [...selected, seat.no] : selected;
      onChange?.(next);
      return;
    }
    if (mode !== 'manage' || !data.can_block) return;
    if (!['free', 'blocked'].includes(seat.state)) return;
    setBusySeat(seat.no);
    try {
      const next = await apiRequest(`/bookings/trips/${tripId}/seats/${seat.no}/block/`, {
        method: seat.state === 'free' ? 'POST' : 'DELETE', body: {},
      });
      setData(next);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusySeat(null);
    }
  };

  const tile = (no) => {
    const seat = byNo[no];
    const isPicked = picked.has(no);
    // Passengers don't need other riders' payment or boarding status.
    const shown = mode === 'pick' && ['held', 'boarded'].includes(seat.state) ? 'booked' : seat.state;
    const state = isPicked ? 'picked' : seat.mine ? 'mine' : shown;
    const clickable = (mode === 'pick' && seat.state === 'free')
      || (mode === 'manage' && data.can_block && ['free', 'blocked'].includes(seat.state));
    const who = seat.passenger ? `, ${seat.passenger}` : '';
    const label = `Seat ${no}, ${isPicked ? 'your pick' : seat.mine ? 'yours' : LABEL[shown]}${who}`;
    return (
      <button
        key={no}
        type="button"
        className={`seat seat-${state}`}
        aria-label={label}
        aria-pressed={mode === 'pick' ? isPicked : undefined}
        title={seat.note || seat.passenger || undefined}
        disabled={!clickable || busySeat === no}
        onClick={() => tap(seat)}
      >
        {state === 'blocked' ? <Lock size={14} aria-hidden="true" />
          : state === 'boarded' ? <Check size={14} aria-hidden="true" /> : null}
        <span>{no}</span>
      </button>
    );
  };

  return (
    <div className="seatmap">
      <dl className="seatmap-ticket">
        <div><dt>Bus</dt><dd>{data.bus?.fleet_number || 'Not assigned yet'}</dd></div>
        <div><dt>Plate</dt><dd>{data.bus?.plate || '—'}</dd></div>
        <div><dt>Driver</dt><dd>{data.driver_name || '—'}</dd></div>
        <div className="seatmap-ticket-wide"><dt>Vehicle</dt><dd>{data.vehicle_label}</dd></div>
      </dl>
      {!data.plan_verified && (
        <p className="seatmap-note">
          No published seat plan for this bus: seat numbers are real, their positions may differ slightly.
        </p>
      )}
      <div className="seatmap-bus" style={{ '--cols': cols }} role="group"
        aria-label={`Seat map of the ${data.vehicle_label}, front at the top. Driver front right, door on the left.`}>
        <div className="seatmap-windscreen" aria-hidden="true">Front</div>
        <div className="seatmap-grid">
          {data.layout.map((row, i) => row.map((cell, j) => {
            const key = `${i}-${j}`;
            if (cell === 'D') return <div key={key} className="seat-driver" title="Driver" aria-hidden="true"><i /></div>;
            if (cell === 'door') return <div key={key} className={j === 0 ? 'seat-door' : 'seat-door-step'} aria-hidden="true" />;
            if (cell == null) return <div key={key} className="seat-gap" aria-hidden="true" />;
            return tile(cell);
          }))}
        </div>
        <div className="seatmap-rear" aria-hidden="true">Back</div>
      </div>
      <ul className="seatmap-legend">
        <li><i className="seat-free" />Free</li>
        {mode === 'pick' && <li><i className="seat-picked" />Your pick</li>}
        {data.seats.some((x) => x.mine) && <li><i className="seat-mine" />Already yours</li>}
        <li><i className="seat-booked" />Taken</li>
        {mode !== 'pick' && <li><i className="seat-held" />Unpaid</li>}
        {mode !== 'pick' && <li><i className="seat-boarded" />Boarded</li>}
        <li><i className="seat-blocked" />Blocked</li>
      </ul>
      {data.unassigned > 0 && (
        <p className="seatmap-note">{data.unassigned} seat{data.unassigned === 1 ? '' : 's'} booked before seat numbers existed (no fixed seat).</p>
      )}
      {mode === 'manage' && data.can_block && (
        <p className="seatmap-note">Tap a free seat to block it (walk-in or staff). Tap a blocked seat to release it.</p>
      )}
    </div>
  );
}
