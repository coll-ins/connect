import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import { MapContainer, CircleMarker, Marker, Polyline, Tooltip, useMap, useMapEvents } from 'react-leaflet';
import BaseTileLayer from '../../components/maps/BaseTileLayer';
import 'leaflet/dist/leaflet.css';
import { Eye, Plus, Save } from 'lucide-react';

import { apiRequest } from '../../api';
import { useAuth } from '../../context/AuthContext';
import Notice, { NoticeStack } from '../../components/ui/Notice';
import '../shared/Services.css';
import './RoutePlanner.css';

const NAIROBI = [-1.286389, 36.817223];
const MAX_DRAWN = 25;
const SNAP_ALL_M = 300;
const ON_LINE_M = 50;
const ALT_COLORS = ['#f59e0b', '#a78bfa', '#fb7185'];
const MODES = [
  ['start', 'Set start'],
  ['end', 'Set end'],
  ['stage', 'Add stage'],
  ['via', 'Add road point'],
  ['draw', 'Draw the way'],
];
const HINTS = {
  start: 'Tap the map where the route starts, for example the bus station in the CBD.',
  end: 'Tap the map where the route ends.',
  stage: 'Tap the road where passengers board, then name the stage on the right. Drag any yellow pin to move it.',
  via: 'Tap a road you want the bus to use. Road points steer the line, for example around a jam. Up to 10.',
  draw: 'Tap along the road the bus really uses, in the direction it travels, starting at the start. Up to 25 points, then press “Preview this drawing”.',
};

const toLatLng = (c) => [c[1], c[0]];
const num = (v) => (v === null || v === undefined || v === '' ? null : Number(v));
const round6 = (n) => Number(n.toFixed(6));

// Nearest point on a [[lat, lng], ...] line to a spot, and how far away it is in metres.
function nearestOnLine(line, lat, lng) {
  if (!line || line.length < 2) return null;
  const k = Math.cos((lat * Math.PI) / 180);
  let best = null;
  for (let i = 0; i < line.length - 1; i += 1) {
    const ax = (line[i][1] - lng) * k;
    const ay = line[i][0] - lat;
    const bx = (line[i + 1][1] - lng) * k;
    const by = line[i + 1][0] - lat;
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy;
    let t = len2 === 0 ? 0 : -(ax * dx + ay * dy) / len2;
    t = Math.max(0, Math.min(1, t));
    const px = ax + t * dx;
    const py = ay + t * dy;
    const d2 = px * px + py * py;
    if (!best || d2 < best.d2) {
      best = {
        d2,
        lat: line[i][0] + t * (line[i + 1][0] - line[i][0]),
        lng: line[i][1] + t * (line[i + 1][1] - line[i][1]),
      };
    }
  }
  return { lat: best.lat, lng: best.lng, metres: Math.sqrt(best.d2) * 111320 };
}

const mkIcon = (cls) => L.divIcon({
  className: 'rp2-pin',
  html: `<span class="rp2-dot ${cls}"></span>`,
  iconSize: [24, 24],
  iconAnchor: [12, 12],
});
const ICONS = { on: mkIcon(''), off: mkIcon('inactive'), moved: mkIcon('moved') };

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

function StagePin({ stage, position, moved, onLive, onDrop }) {
  const handlers = useMemo(() => ({
    drag: (e) => onLive(stage.name, e.target.getLatLng()),
    dragend: (e) => onDrop(stage.id, e.target.getLatLng()),
  }), [stage.id, stage.name, onLive, onDrop]);
  return (
    <Marker position={position} draggable icon={moved ? ICONS.moved : stage.is_active ? ICONS.on : ICONS.off}
      eventHandlers={handlers} zIndexOffset={500}>
      <Tooltip>{stage.order}. {stage.name}{stage.is_active ? '' : ' (off)'}</Tooltip>
    </Marker>
  );
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
  const [ordered, setOrdered] = useState(false);
  const [drawn, setDrawn] = useState([]);
  const [alts, setAlts] = useState(null);
  const [moved, setMoved] = useState({});
  const [live, setLive] = useState(null);
  const [draft, setDraft] = useState(null);
  const [mode, setMode] = useState('stage');
  const [pending, setPending] = useState(null);
  const [stageName, setStageName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [note, setNote] = useState('');
  const [tick, setTick] = useState(0);

  const [health, setHealth] = useState({});

  const fail = useCallback((title, e) => {
    const text = typeof e === 'string' ? e : (e?.message || 'Something went wrong. Please try again.');
    setError({ title, text });
  }, []);

  const loadHealth = useCallback(async () => {
    try {
      const d = await apiRequest('/companies/routes/health/');
      const rows = Array.isArray(d) ? d : d?.results || [];
      const map = {};
      rows.forEach((h) => { map[h.id] = h; });
      setHealth(map);
    } catch { /* advisory only; the planner works without it */ }
  }, []);

  const route = routes?.find((r) => String(r.id) === routeId);

  const loadRoutes = useCallback(async () => {
    if (!companyId) return;
    try {
      const d = await apiRequest(`/companies/${companyId}/routes/`);
      setRoutes(Array.isArray(d) ? d : d?.results || []);
    } catch (e) { fail('Could not load your routes', e); setRoutes([]); }
  }, [companyId, fail]);

  const loadStages = useCallback(async (fit = false) => {
    if (!routeId) return;
    try {
      const d = await apiRequest(`/companies/routes/${routeId}/pickup-stages/`);
      setStages(Array.isArray(d) ? d : d?.stages || d?.results || []);
      if (fit) setTick((t) => t + 1);
    } catch (e) { fail('Could not load the stages', e); }
  }, [routeId, fail]);

  const choose = (r) => {
    setRouteId(String(r.id));
    setDraft(null); setPending(null);
    setOrdered(false); setDrawn([]); setAlts(null); setMoved({}); setLive(null);
    setVia(Array.isArray(r.via_points) ? r.via_points : []);
    setError(null); setNote(''); setMode('stage');
    const sl = num(r.start_latitude); const sg = num(r.start_longitude);
    const el = num(r.end_latitude); const eg = num(r.end_longitude);
    setStart(sl !== null && sg !== null ? { name: r.start_point || '', latitude: sl, longitude: sg } : null);
    setEnd(el !== null && eg !== null ? { name: r.end_point || '', latitude: el, longitude: eg } : null);
    setTick((t) => t + 1);
  };

  useEffect(() => { loadRoutes(); loadHealth(); }, [loadRoutes, loadHealth]);

  useEffect(() => {
    if (!routes?.length || routeId) return;
    const wanted = new URLSearchParams(window.location.search).get('route');
    choose(routes.find((r) => String(r.id) === wanted) || routes[0]);
  }, [routes, routeId]);

  useEffect(() => {
    if (!routeId) { setStages([]); return; }
    loadStages(true);
  }, [routeId, loadStages]);

  const savedLine = useMemo(
    () => (route?.geometry?.coordinates?.length > 1 ? route.geometry.coordinates.map(toLatLng) : null),
    [route],
  );
  const draftLine = useMemo(
    () => (draft?.geometry?.coordinates?.length > 1 ? draft.geometry.coordinates.map(toLatLng) : null),
    [draft],
  );
  const measureLine = draftLine || savedLine;
  // Snapping never uses a saved line that doubles back: pins would land on the spur.
  const snapLine = draftLine || (health[route?.id]?.status === 'check' ? null : savedLine);
  const altLines = useMemo(
    () => (alts || []).map((o) => o.geometry.coordinates.map(toLatLng)),
    [alts],
  );

  const pins = useMemo(() => stages.map((s) => {
    const m = moved[s.id];
    return {
      s,
      isMoved: Boolean(m),
      pos: m ? [m.latitude, m.longitude] : [Number(s.latitude), Number(s.longitude)],
    };
  }), [stages, moved]);

  const offsets = useMemo(() => {
    const out = {};
    if (!measureLine) return out;
    pins.forEach(({ s, pos }) => {
      const n = nearestOnLine(measureLine, pos[0], pos[1]);
      if (n) out[s.id] = Math.round(n.metres);
    });
    return out;
  }, [measureLine, pins]);

  const measureLineRef = useRef(null);
  useEffect(() => { measureLineRef.current = measureLine; }, [measureLine]);

  const onLive = useCallback((name, ll) => {
    const n = nearestOnLine(measureLineRef.current, ll.lat, ll.lng);
    setLive({ name, metres: n ? Math.round(n.metres) : null });
  }, []);

  const onDrop = useCallback((id, ll) => {
    setMoved((m) => ({ ...m, [id]: { latitude: round6(ll.lat), longitude: round6(ll.lng) } }));
    setLive(null);
  }, []);

  const onPick = (ll) => {
    setError(null); setNote('');
    const p = { latitude: round6(ll.lat), longitude: round6(ll.lng) };
    if (mode === 'start') { setStart((s) => ({ name: s?.name || route?.start_point || '', ...p })); setDraft(null); }
    else if (mode === 'end') { setEnd((s) => ({ name: s?.name || route?.end_point || '', ...p })); setDraft(null); }
    else if (mode === 'via') {
      if (ordered) {
        fail('Road points are locked',
          'This line comes from a drawing or a picked road. Press “Clear” next to the road points to steer it by hand instead.');
        return;
      }
      setVia((v) => (v.length >= 10 ? v : [...v, p])); setDraft(null);
    } else if (mode === 'draw') {
      setDrawn((d) => (d.length >= MAX_DRAWN ? d : [...d, p]));
    } else setPending(p);
  };

  const plan = async (apply, over = {}) => {
    setBusy(true); setError(null); setNote('');
    const useVia = over.via ?? via;
    const useOrdered = over.ordered ?? ordered;
    if (over.via) setVia(over.via);
    if (over.ordered !== undefined) setOrdered(over.ordered);
    try {
      const d = await apiRequest(`/companies/routes/${routeId}/plan/`, {
        method: 'POST',
        body: { start, end, via: useVia, apply, ordered: useOrdered, follow_stages: false },
      });
      if (apply) {
        setDraft(null); setVia(Array.isArray(d.via) ? d.via : []);
        setOrdered(false); setDrawn([]); setAlts(null);
        setNote('Road line saved. Passengers and drivers now see this route.');
        await loadRoutes();
        await loadHealth();
      } else {
        setDraft(d);
      }
      setTick((t) => t + 1);
    } catch (e) {
      fail(apply ? 'Could not save the road line' : 'Could not preview the road line', e);
    } finally { setBusy(false); }
  };

  const autoPlanned = useRef('');

  // A route with a start and an end but no line gets a preview automatically.
  useEffect(() => {
    if (!route || !start || !end || busy) return;
    if (route.geometry?.coordinates?.length > 1) return;
    if (autoPlanned.current === routeId) return;
    autoPlanned.current = routeId;
    plan(false);
  }, [routeId, route, start, end]);

  const loadAlts = async () => {
    setBusy(true); setError(null); setNote('');
    try {
      const d = await apiRequest(`/companies/routes/${routeId}/alternatives/`, {
        method: 'POST',
        body: { start, end },
      });
      const options = Array.isArray(d?.options) ? d.options : [];
      if (options.length < 2) {
        setAlts(null);
        setNote('The road service found no other road between the start and the end. Use “Draw the way” to show where the bus goes.');
      } else {
        setAlts(options);
      }
    } catch (e) { fail('Could not look for other roads', e); } finally { setBusy(false); }
  };

  const pickAlt = (option) => {
    setAlts(null);
    plan(false, { via: option.via, ordered: true });
  };

  const previewDrawing = () => {
    if (drawn.length < 2) {
      fail('Not enough points', 'Tap at least 2 points along the road the bus uses.');
      return;
    }
    setAlts(null);
    plan(false, { via: drawn, ordered: true });
  };

  const nextOrder = useMemo(
    () => stages.reduce((m, s) => Math.max(m, Number(s.order) || 0), 0) + 1,
    [stages],
  );

  const addStage = async () => {
    if (!pending || !stageName.trim()) return;
    setBusy(true); setError(null); setNote('');
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
    } catch (e) { fail('Could not add the stage', e); } finally { setBusy(false); }
  };

  const approveStage = async (s) => {
    setBusy(true); setError(null); setNote('');
    try {
      await apiRequest(`/companies/pickup-stages/${s.id}/approve/`, { method: 'POST' });
      setNote(`Approved “${s.name}”.`);
      await loadStages();
    } catch (e) { fail('Could not approve the stage', e); } finally { setBusy(false); }
  };

  const toggleStage = async (s) => {
    setBusy(true); setError(null); setNote('');
    try {
      await apiRequest(`/companies/pickup-stages/${s.id}/`, {
        method: 'PATCH', body: { is_active: !s.is_active },
      });
      await loadStages();
    } catch (e) { fail('Could not change the stage', e); } finally { setBusy(false); }
  };

  const snapStage = (s, pos) => {
    const n = nearestOnLine(snapLine, pos[0], pos[1]);
    if (!n) return;
    setMoved((m) => ({ ...m, [s.id]: { latitude: round6(n.lat), longitude: round6(n.lng) } }));
  };

  const snapAll = () => {
    if (!snapLine) return;
    const next = {};
    pins.forEach(({ s, pos }) => {
      if (!s.is_active) return;
      const n = nearestOnLine(snapLine, pos[0], pos[1]);
      if (n && n.metres > 1 && n.metres <= SNAP_ALL_M) {
        next[s.id] = { latitude: round6(n.lat), longitude: round6(n.lng) };
      }
    });
    const count = Object.keys(next).length;
    if (!count) {
      setNote(`No stage is between 1 m and ${SNAP_ALL_M} m from the line.`);
      return;
    }
    setMoved((m) => ({ ...m, ...next }));
    setNote(`${count} stage(s) moved onto the line. Press “Save positions” to keep them.`);
  };

  const movedIds = Object.keys(moved);

  const savePins = async () => {
    if (!movedIds.length) return;
    setBusy(true); setError(null); setNote('');
    try {
      for (const id of movedIds) {
        const spot = moved[id];
        await apiRequest(`/companies/pickup-stages/${id}/`, {
          method: 'PATCH',
          body: { latitude: spot.latitude.toFixed(6), longitude: spot.longitude.toFixed(6) },
        });
        setMoved((m) => { const rest = { ...m }; delete rest[id]; return rest; });
      }
      await loadStages();
      setDraft(null);
      setNote(`Saved ${movedIds.length} stage position(s). Preview the road line again to check it.`);
    } catch (e) {
      fail('Could not save the stage positions', e);
      await loadStages();
    } finally { setBusy(false); }
  };

  let fitPoints = draftLine || savedLine;
  if (!fitPoints) {
    fitPoints = stages.map((s) => [Number(s.latitude), Number(s.longitude)]);
    if (start) fitPoints.push([start.latitude, start.longitude]);
    if (end) fitPoints.push([end.latitude, end.longitude]);
    fitPoints = fitPoints.filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]));
  }
  const ready = Boolean(start && end);

  let blocker = '';
  if (!ready) blocker = 'Set the start and the end first.';
  else if (!draft) blocker = 'Preview the road line before saving it.';
  else if (movedIds.length) blocker = 'Save the stage positions first, then preview the road line again.';
  else if (draft.off_route_stages?.length) {
    blocker = 'Some stages are off this line. Drag them onto it or press “Snap to line”, save their positions, then preview again.';
  }

  return (
    <div className="svc-page">
      <NoticeStack>
        {error && (
          <Notice kind="error" title={error.title} onClose={() => setError(null)}>{error.text}</Notice>
        )}
        {note && (
          <Notice kind="success" autoHideMs={8000} onClose={() => setNote('')}>{note}</Notice>
        )}
      </NoticeStack>

      <div className="svc-head">
        <div>
          <span className="glass-eyebrow">ROUTES</span>
          <h1>Route planner</h1>
          <p>Set where a route starts and ends, place its stages, and show the road the bus follows. Nothing changes for passengers until you save.</p>
        </div>
      </div>

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
                    <BaseTileLayer />
                    <Fit points={fitPoints} tick={tick} />
                    <Clicks onPick={onPick} />

                    {savedLine && (
                      <Polyline positions={savedLine}
                        pathOptions={draftLine
                          ? { color: '#94a3b8', weight: 4, dashArray: '8 8' }
                          : { color: '#34d399', weight: 5 }} />
                    )}
                    {altLines.map((line, i) => (
                      <Polyline key={`alt-${i}`} positions={line}
                        pathOptions={{ color: ALT_COLORS[i % ALT_COLORS.length], weight: 5, opacity: 0.85 }} />
                    ))}
                    {draftLine && <Polyline positions={draftLine} pathOptions={{ color: '#38bdf8', weight: 5 }} />}
                    {drawn.length > 1 && (
                      <Polyline positions={drawn.map((p) => [p.latitude, p.longitude])}
                        pathOptions={{ color: '#fb923c', weight: 3, dashArray: '4 6' }} />
                    )}
                    {drawn.map((p, i) => (
                      <CircleMarker key={`drawn-${i}`} center={[p.latitude, p.longitude]} radius={5}
                        pathOptions={{ color: '#fb923c', fillOpacity: 1 }}>
                        <Tooltip>Drawn point {i + 1}</Tooltip>
                      </CircleMarker>
                    ))}

                    {pins.map(({ s, pos, isMoved }) => (
                      <StagePin key={s.id} stage={s} position={pos} moved={isMoved}
                        onLive={onLive} onDrop={onDrop} />
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
                    {(health[route.id]?.spur_points || []).map((sp, i) => (
                      <CircleMarker key={`spur-${i}`} center={sp} radius={9}
                        pathOptions={{ color: '#f87171', fillOpacity: 0.35 }}>
                        <Tooltip>Saved line doubles back here</Tooltip>
                      </CircleMarker>
                    ))}
                    {pending && (
                      <CircleMarker center={[pending.latitude, pending.longitude]} radius={10}
                        pathOptions={{ color: '#fb923c', fillOpacity: 0.5 }} />
                    )}
                  </MapContainer>
                  {live && (
                    <div className="rp2-live">
                      {live.name}: {live.metres === null ? 'no line to measure against' : `${live.metres} m from the line`}
                    </div>
                  )}
                </div>
                <p className="rp-hint">Green: saved line. Blue: new line (preview). Yellow pins: stages (drag to move). Orange: moved or drawn. Purple: road points.</p>
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
                    Road points: {via.length}{ordered ? ' (from a drawing or picked road)' : ''}
                    {via.length > 0 && (
                      <> · <button type="button" className="btn btn-ghost"
                        onClick={() => { setVia([]); setDraft(null); setOrdered(false); }}>Clear</button></>
                    )}
                  </p>

                  <div className="svc-actions">
                    <button type="button" className="btn btn-secondary" disabled={!ready || busy} onClick={() => plan(false)}>
                      <Eye size={16} /> {busy ? 'Working…' : 'Preview road line'}
                    </button>
                    <button type="button" className="btn btn-primary" disabled={!ready || busy || Boolean(blocker)} onClick={() => plan(true)}>
                      <Save size={16} /> {draft?.spurs > 0 ? 'Save anyway (line doubles back)' : 'Save road line'}
                    </button>
                  </div>
                  {blocker && <p className="rp2-block">{blocker}</p>}

                  <div className="rp2-tools">
                    <button type="button" className="btn btn-ghost" disabled={!ready || busy} onClick={loadAlts}>
                      Show other roads
                    </button>
                  </div>

                  {alts && (
                    <div style={{ marginTop: 10 }}>
                      {alts.map((o, i) => (
                        <div key={i} className="rp2-alt">
                          <span>
                            <span className="rp2-swatch" style={{ background: ALT_COLORS[i % ALT_COLORS.length] }} />
                            <strong>Road {String.fromCharCode(65 + i)}</strong> · {o.distance_km} km
                            {o.spurs > 0 ? ` · doubles back ${o.spurs}×` : ''}
                            {o.off_route_stages?.length ? ` · ${o.off_route_stages.length} stage(s) off it` : ''}
                          </span>
                          <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => pickAlt(o)}>
                            Use this road
                          </button>
                        </div>
                      ))}
                      <p className="svc-muted" style={{ marginTop: 8 }}>
                        Only roads between the start and the end are shown. Your road points are not part of these options.
                      </p>
                    </div>
                  )}

                  {mode === 'draw' && (
                    <div style={{ marginTop: 14 }}>
                      <p className="svc-muted" style={{ margin: 0 }}>Drawn points: {drawn.length} / {MAX_DRAWN}</p>
                      <div className="rp2-tools">
                        <button type="button" className="btn btn-ghost" disabled={!drawn.length}
                          onClick={() => setDrawn((d) => d.slice(0, -1))}>Undo</button>
                        <button type="button" className="btn btn-ghost" disabled={drawn.length < 2}
                          onClick={() => setDrawn((d) => [...d].reverse())}>Reverse</button>
                        <button type="button" className="btn btn-ghost" disabled={!drawn.length}
                          onClick={() => setDrawn([])}>Clear drawing</button>
                        <button type="button" className="btn btn-secondary" disabled={!ready || busy || drawn.length < 2}
                          onClick={previewDrawing}>Preview this drawing</button>
                      </div>
                    </div>
                  )}

                  {draft && (
                    <div className="rp-stats" style={{ marginTop: 14 }}>
                      <span>New line: {draft.distance_km} km</span>
                      {typeof draft.spurs === 'number' && (
                        <span>{draft.spurs === 0 ? 'No doubling back' : `Doubles back ${draft.spurs} time(s)`}</span>
                      )}
                    </div>
                  )}
                  {draft?.spurs > 0 && (
                    <div className="rp-warn" style={{ marginTop: 14 }}>
                      This line goes up a street and comes back. A real bus does not do that. Try “Show other roads” or “Draw the way”.
                    </div>
                  )}
                  {draft?.off_route_stages?.length > 0 && (
                    <div className="rp-warn" style={{ marginTop: 14 }}>
                      These stages are off the new line:
                      {' '}{draft.off_route_stages.map((s) => `${s.name} (${s.offset_m} m)`).join(', ')}.
                      {' '}Drag them onto the blue line, or press “Snap to line”.
                    </div>
                  )}
                  {health[route.id]?.status === 'check' && (
                    <div className="rp-warn" style={{ marginTop: 14 }}>
                      Check this route: {health[route.id].reasons.join('; ')}.
                      {health[route.id].spur_points?.length > 0
                        && ' Red circles on the map show where the saved line doubles back. Press “Preview road line” for a clean line, then snap the stages to it.'}
                    </div>
                  )}
                </div>

                <div className="svc-card">
                  <h3>Stages</h3>
                  <div className="rp2-tools" style={{ marginTop: 0, marginBottom: 12 }}>
                    <button type="button" className="btn btn-ghost" disabled={!snapLine || busy} onClick={snapAll}>
                      Snap all within {SNAP_ALL_M} m
                    </button>
                    <button type="button" className="btn btn-primary" disabled={!movedIds.length || busy} onClick={savePins}>
                      Save positions{movedIds.length ? ` (${movedIds.length})` : ''}
                    </button>
                    <button type="button" className="btn btn-ghost" disabled={!movedIds.length || busy}
                      onClick={() => setMoved({})}>Discard moves</button>
                  </div>
                  {!snapLine && (
                    <p className="svc-muted" style={{ margin: '0 0 12px' }}>
                      Press “Preview road line” first. Stages are snapped to the new line, not to a saved line that doubles back.
                    </p>
                  )}
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
                      {pins.map(({ s, pos, isMoved }) => {
                        const off = offsets[s.id];
                        return (
                          <div key={s.id} className={`rp-stage ${s.is_active ? '' : 'off'}`}>
                            <span>
                              <strong>{s.order}.</strong> {s.name}
                              {s.source === 'automatic' ? ' · auto' : ''}
                              {isMoved ? ' · moved, not saved' : ''}
                              {off !== undefined && (
                                <small className={`rp2-off ${off > ON_LINE_M ? 'far' : ''}`}> · {off} m from the line</small>
                              )}
                            </span>
                            {off !== undefined && off > 1 && snapLine && (
                              <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => snapStage(s, pos)}>
                                Snap to line
                              </button>
                            )}
                            {s.source === 'automatic' && (
                              <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => approveStage(s)}>
                                Approve
                              </button>
                            )}
                            <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => toggleStage(s)}>
                              {s.is_active ? 'Remove' : 'Bring back'}
                            </button>
                          </div>
                        );
                      })}
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
