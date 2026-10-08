import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  MapContainer, TileLayer, CircleMarker, Polyline, Tooltip, useMap, useMapEvents,
} from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import { Eye, Plus, Save } from 'lucide-react';

import { apiRequest } from '../../api';
import { useAuth } from '../../context/AuthContext';
import '../shared/Services.css';

const NAIROBI = [-1.286389, 36.817223];
const MODES = [
  ['start', 'Set start'],
  ['end', 'Set end'],
  ['stage', 'Add stage'],
  ['via', 'Add road point'],
];
const HINTS = {
  start: 'Tap the map where the route starts, for example the bus station in the CBD.',
  end: 'Tap the map where the route ends.',
  stage: 'Tap the road where passengers board, then name the stage on the right.',
  via: 'Tap a road you want the bus to use. Road points steer the line, for example around a jam. Up to 10.',
};
const toLatLng = (c) => [c[1], c[0]];
const num = (v) => (v === null || v === undefined || v === '' ? null : Number(v));

function Clicks({ onPick }) {
  useMapEvents({ click: (e) => onPick(e.latlng) });
  return null;
}

function Fit({ points, tick }) {
  const map = useMap();
  useEffect(() => {
    if (points.length > 1) map.fitBounds(points, { padding: [30, 30], maxZoom: 15 });
    else if (points.length === 1) map.setView(points[0], 14);
  }, [tick, map]);
  return null;
}

export default function RoutePlanner() {
  const { user } = useAuth();
  const companyId = user?.company_id;

  const [routes, setRoutes] = useState(null);
  const [routeId, setRouteId] = useState('');
  const [stages, setStages] = useState([]);
  const [start, setStart] = useState(null);
  const [end, setEnd] = useState(null);
  const [via, setVia] = useState([]);
  const [draft, setDraft] = useState(null);
  const [offRoute, setOffRoute] = useState([]);
  const [mode, setMode] = useState('stage');
  const [pending, setPending] = useState(null);
  const [stageName, setStageName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [note, setNote] = useState('');
  const [tick, setTick] = useState(0);

  const route = routes?.find((r) => String(r.id) === routeId);

  const loadRoutes = useCallback(async () => {
    if (!companyId) return;
    try {
      const d = await apiRequest(`/companies/${companyId}/routes/`);
      setRoutes(Array.isArray(d) ? d : d?.results || []);
    } catch (e) { setError(e.message); setRoutes([]); }
  }, [companyId]);

  const loadStages = useCallback(async (fit = false) => {
    if (!routeId) return;
    try {
      const d = await apiRequest(`/companies/routes/${routeId}/pickup-stages/`);
      setStages(Array.isArray(d) ? d : d?.stages || d?.results || []);
      if (fit) setTick((t) => t + 1);
    } catch (e) { setError(e.message); }
  }, [routeId]);

  const choose = (r) => {
    setRouteId(String(r.id));
    setDraft(null); setOffRoute([]); setVia([]); setPending(null);
    setError(''); setNote(''); setMode('stage');
    const sl = num(r.start_latitude); const sg = num(r.start_longitude);
    const el = num(r.end_latitude); const eg = num(r.end_longitude);
    setStart(sl !== null && sg !== null ? { name: r.start_point || '', latitude: sl, longitude: sg } : null);
    setEnd(el !== null && eg !== null ? { name: r.end_point || '', latitude: el, longitude: eg } : null);
    setTick((t) => t + 1);
  };

  useEffect(() => { loadRoutes(); }, [loadRoutes]);

  useEffect(() => {
    if (!routes?.length || routeId) return;
    choose(routes[0]);
  }, [routes, routeId]);

  useEffect(() => {
    if (!routeId) { setStages([]); return; }
    loadStages(true);
  }, [routeId, loadStages]);


  const onPick = (ll) => {
    setError(''); setNote('');
    const p = { latitude: Number(ll.lat.toFixed(6)), longitude: Number(ll.lng.toFixed(6)) };
    if (mode === 'start') { setStart((s) => ({ name: s?.name || '', ...p })); setDraft(null); }
    else if (mode === 'end') { setEnd((s) => ({ name: s?.name || '', ...p })); setDraft(null); }
    else if (mode === 'via') { setVia((v) => (v.length >= 10 ? v : [...v, p])); setDraft(null); }
    else setPending(p);
  };

  const plan = async (apply) => {
    setBusy(true); setError(''); setNote('');
    try {
      const d = await apiRequest(`/companies/routes/${routeId}/plan/`, {
        method: 'POST',
        body: { start, end, via, apply },
      });
      setOffRoute(d.off_route_stages || []);
      if (apply) {
        setDraft(null); setVia([]);
        setNote('Road line saved. Passengers and drivers now see this route.');
        await loadRoutes();
      } else {
        setDraft(d);
      }
      setTick((t) => t + 1);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  const nextOrder = useMemo(
    () => stages.reduce((m, s) => Math.max(m, Number(s.order) || 0), 0) + 1,
    [stages],
  );

  const addStage = async () => {
    if (!pending || !stageName.trim()) return;
    setBusy(true); setError(''); setNote('');
    try {
      await apiRequest(`/companies/routes/${routeId}/pickup-stages/create/`, {
        method: 'POST',
        body: {
          name: stageName.trim(),
          latitude: pending.latitude.toFixed(6),
          longitude: pending.longitude.toFixed(6),
          order: nextOrder,
        },
      });
      setPending(null); setStageName('');
      setNote('Stage added.');
      await loadStages();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  const toggleStage = async (s) => {
    setBusy(true); setError(''); setNote('');
    try {
      await apiRequest(`/companies/pickup-stages/${s.id}/`, {
        method: 'PATCH', body: { is_active: !s.is_active },
      });
      await loadStages();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  const savedLine = route?.geometry?.coordinates?.length > 1 ? route.geometry.coordinates.map(toLatLng) : null;
  const draftLine = draft?.geometry?.coordinates?.length > 1 ? draft.geometry.coordinates.map(toLatLng) : null;
  let fitPoints = draftLine || savedLine;
  if (!fitPoints) {
    fitPoints = stages.map((s) => [Number(s.latitude), Number(s.longitude)]);
    if (start) fitPoints.push([start.latitude, start.longitude]);
    if (end) fitPoints.push([end.latitude, end.longitude]);
    fitPoints = fitPoints.filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]));
  }
  const ready = Boolean(start && end);

  return (
    <div className="svc-page">
      <div className="svc-head">
        <div>
          <span className="glass-eyebrow">ROUTES</span>
          <h1>Route planner</h1>
          <p>Set where a route starts and ends, place its stages, and draw the road the bus follows. Nothing changes for passengers until you save.</p>
        </div>
      </div>

      {error && <div className="svc-error">{error}</div>}
      {note && <div className="svc-note">{note}</div>}

      {routes === null ? (
        <div className="glass-empty">Loading…</div>
      ) : !routes.length ? (
        <div className="glass-empty"><strong>You have no routes yet.</strong></div>
      ) : (
        <>
          <div className="svc-pick-grid rp-routes">
            {routes.map((r) => (
              <button key={r.id} type="button"
                className={`svc-pick ${routeId === String(r.id) ? 'selected' : ''}`}
                onClick={() => choose(r)}>
                <span className="svc-pick-main">
                  <strong>{r.name}</strong>
                  <small>{r.start_point} → {r.end_point}</small>
                </span>
              </button>
            ))}
          </div>

          {route && (
            <div className="rp-grid">
              <div className="svc-card">
                <div className="rp-modes">
                  {MODES.map(([k, t]) => (
                    <button key={k} type="button" className={`rp-mode ${mode === k ? 'active' : ''}`}
                      onClick={() => setMode(k)}>{t}</button>
                  ))}
                </div>
                <p className="rp-hint">{HINTS[mode]}</p>

                <div className="rp-map">
                  <MapContainer center={NAIROBI} zoom={12} style={{ height: '100%', width: '100%' }}>
                    <TileLayer attribution="&copy; OpenStreetMap contributors"
                      url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
                    <Fit points={fitPoints} tick={tick} />
                    <Clicks onPick={onPick} />

                    {savedLine && (
                      <Polyline positions={savedLine}
                        pathOptions={draftLine
                          ? { color: '#94a3b8', weight: 4, dashArray: '8 8' }
                          : { color: '#34d399', weight: 5 }} />
                    )}
                    {draftLine && <Polyline positions={draftLine} pathOptions={{ color: '#38bdf8', weight: 5 }} />}

                    {stages.map((s) => (
                      <CircleMarker key={s.id} center={[Number(s.latitude), Number(s.longitude)]} radius={7}
                        pathOptions={{ color: s.is_active ? '#facc15' : '#64748b', fillOpacity: 0.9 }}>
                        <Tooltip>{s.order}. {s.name}{s.is_active ? '' : ' (off)'}</Tooltip>
                      </CircleMarker>
                    ))}
                    {start && (
                      <CircleMarker center={[start.latitude, start.longitude]} radius={11}
                        pathOptions={{ color: '#22c55e', fillOpacity: 0.8 }}>
                        <Tooltip permanent>Start{start.name ? `: ${start.name}` : ''}</Tooltip>
                      </CircleMarker>
                    )}
                    {end && (
                      <CircleMarker center={[end.latitude, end.longitude]} radius={11}
                        pathOptions={{ color: '#ef4444', fillOpacity: 0.8 }}>
                        <Tooltip permanent>End{end.name ? `: ${end.name}` : ''}</Tooltip>
                      </CircleMarker>
                    )}
                    {via.map((v, i) => (
                      <CircleMarker key={`${v.latitude}-${v.longitude}-${i}`} center={[v.latitude, v.longitude]} radius={6}
                        pathOptions={{ color: '#a78bfa', fillOpacity: 0.9 }}>
                        <Tooltip>Road point {i + 1}</Tooltip>
                      </CircleMarker>
                    ))}
                    {pending && (
                      <CircleMarker center={[pending.latitude, pending.longitude]} radius={10}
                        pathOptions={{ color: '#fb923c', fillOpacity: 0.5 }} />
                    )}
                  </MapContainer>
                </div>
                <p className="rp-hint">Green: saved line. Blue: new line (preview). Yellow dots: stages. Purple: road points.</p>
              </div>

              <div className="rp-side">
                <div className="svc-card">
                  <h3>Start, end and road line</h3>
                  <div className="svc-form" style={{ gridTemplateColumns: '1fr' }}>
                    <label className="svc-field">Start name
                      <input className="input" maxLength={100} value={start?.name || ''}
                        disabled={!start} placeholder="Tap “Set start”, then the map"
                        onChange={(e) => setStart((s) => ({ ...s, name: e.target.value }))} />
                    </label>
                    <label className="svc-field">End name
                      <input className="input" maxLength={100} value={end?.name || ''}
                        disabled={!end} placeholder="Tap “Set end”, then the map"
                        onChange={(e) => setEnd((s) => ({ ...s, name: e.target.value }))} />
                    </label>
                  </div>
                  <p className="svc-muted" style={{ margin: '12px 0 0' }}>
                    Road points: {via.length}
                    {via.length > 0 && (
                      <> · <button type="button" className="btn btn-ghost"
                        onClick={() => { setVia([]); setDraft(null); }}>Clear</button></>
                    )}
                  </p>
                  <div className="svc-actions">
                    <button type="button" className="btn btn-secondary" disabled={!ready || busy} onClick={() => plan(false)}>
                      <Eye size={16} /> {busy ? 'Working…' : 'Preview road line'}
                    </button>
                    <button type="button" className="btn btn-primary" disabled={!ready || busy || !draft} onClick={() => plan(true)}>
                      <Save size={16} /> Save road line
                    </button>
                  </div>
                  {draft && (
                    <div className="rp-stats" style={{ marginTop: 14 }}>
                      <span>New line: {draft.distance_km} km</span>
                    </div>
                  )}
                  {offRoute.length > 0 && (
                    <div className="rp-warn" style={{ marginTop: 14 }}>
                      These stages are off the new line. Move them or turn them off:
                      {' '}{offRoute.map((s) => `${s.name} (${s.offset_m} m)`).join(', ')}.
                    </div>
                  )}
                </div>

                <div className="svc-card">
                  <h3>Stages</h3>
                  {pending && (
                    <div className="svc-form" style={{ gridTemplateColumns: '1fr', marginBottom: 14 }}>
                      <label className="svc-field">Name the new stage
                        <input className="input" maxLength={150} value={stageName}
                          onChange={(e) => setStageName(e.target.value)} placeholder="e.g. Adams Arcade" />
                      </label>
                      <div>
                        <button type="button" className="btn btn-primary" disabled={busy || !stageName.trim()} onClick={addStage}>
                          <Plus size={16} /> Add stage here
                        </button>
                        {' '}
                        <button type="button" className="btn btn-ghost" onClick={() => setPending(null)}>Cancel</button>
                      </div>
                    </div>
                  )}
                  {!stages.length ? (
                    <p className="svc-muted">No stages yet. Choose “Add stage” and tap the road.</p>
                  ) : (
                    <div className="svc-list">
                      {stages.map((s) => (
                        <div key={s.id} className={`rp-stage ${s.is_active ? '' : 'off'}`}>
                          <span><strong>{s.order}.</strong> {s.name}</span>
                          <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => toggleStage(s)}>
                            {s.is_active ? 'Remove' : 'Bring back'}
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                  <p className="svc-muted" style={{ marginTop: 12 }}>
                    “Remove” hides a stage from passengers without deleting it, so existing bookings and parcels stay valid.
                  </p>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
