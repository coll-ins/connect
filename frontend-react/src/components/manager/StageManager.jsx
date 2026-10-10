import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  MapContainer,
  TileLayer,
  CircleMarker,
  Tooltip,
  useMap,
  useMapEvents,
} from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import { apiRequest } from '../../api';

const NAIROBI = [-1.286389, 36.817223];

function ClickPicker({ onPick }) {
  useMapEvents({ click: (e) => onPick(e.latlng) });
  return null;
}

function FitStages({ stages }) {
  const map = useMap();

  useEffect(() => {
    const pts = stages
      .map((s) => [Number(s.latitude), Number(s.longitude)])
      .filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]));

    if (pts.length === 1) map.setView(pts[0], 14);
    else if (pts.length > 1) map.fitBounds(pts, { padding: [30, 30], maxZoom: 15 });
  }, [stages, map]);

  return null;
}

const box = {
  padding: '10px 12px',
  borderRadius: 10,
  border: '1px solid rgba(128,128,128,0.4)',
  background: 'transparent',
  color: 'inherit',
  width: '100%',
};

export default function StageManager({ companyId }) {
  const [routes, setRoutes] = useState([]);
  const [routeId, setRouteId] = useState('');
  const [stages, setStages] = useState([]);
  const [form, setForm] = useState({ name: '', latitude: '', longitude: '', order: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [note, setNote] = useState('');

  useEffect(() => {
    if (!companyId) return;

    apiRequest(`/companies/${companyId}/routes/`)
      .then((d) => setRoutes(Array.isArray(d) ? d : d?.results || []))
      .catch((e) => setError(e.message || 'Unable to load routes.'));
  }, [companyId]);

  const loadStages = useCallback(async () => {
    if (!routeId) {
      setStages([]);
      return;
    }

    try {
      const d = await apiRequest(`/companies/routes/${routeId}/pickup-stages/`);
      setStages(Array.isArray(d) ? d : d?.stages || d?.results || []);
    } catch (e) {
      setError(e.message || 'Unable to load stages.');
    }
  }, [routeId]);

  useEffect(() => {
    loadStages();
  }, [loadStages]);

  const nextOrder = useMemo(
    () => stages.reduce((m, s) => Math.max(m, Number(s.order) || 0), 0) + 1,
    [stages],
  );

  const picked =
    Number.isFinite(Number(form.latitude)) &&
    Number.isFinite(Number(form.longitude)) &&
    form.latitude !== '' &&
    form.longitude !== ''
      ? [Number(form.latitude), Number(form.longitude)]
      : null;

  const pick = (latlng) => {
    setNote('');
    setForm((f) => ({
      ...f,
      latitude: latlng.lat.toFixed(6),
      longitude: latlng.lng.toFixed(6),
    }));
  };

  const save = async () => {
    setError('');
    setNote('');

    const lat = Number(form.latitude);
    const lng = Number(form.longitude);

    if (!routeId) return setError('Choose a route first.');
    if (!form.name.trim()) return setError('Give the stage a name.');
    if (!picked || lat < -90 || lat > 90 || lng < -180 || lng > 180) {
      return setError('Click the map (or type valid coordinates) to place the stage.');
    }

    setBusy(true);

    try {
      await apiRequest(`/companies/routes/${routeId}/pickup-stages/create/`, {
        method: 'POST',
        body: {
          name: form.name.trim(),
          latitude: lat.toFixed(6),
          longitude: lng.toFixed(6),
          order: form.order === '' ? nextOrder : Number(form.order),
        },
      });

      setNote('Stage added.');
      setForm({ name: '', latitude: '', longitude: '', order: '' });
      await loadStages();
    } catch (e) {
      setError(e.message || 'Unable to add the stage.');
    } finally {
      setBusy(false);
    }
  };

  const approveStage = async (stage) => {
    setError('');
    setNote('');
    setBusy(true);

    try {
      await apiRequest(`/companies/pickup-stages/${stage.id}/approve/`, {
        method: 'POST',
      });
      setNote(`Approved “${stage.name}”.`);
      await loadStages();
    } catch (e) {
      setError(e.message || 'Unable to approve the stage.');
    } finally {
      setBusy(false);
    }
  };

  const toggleActive = async (stage) => {
    setError('');
    setNote('');
    setBusy(true);

    try {
      await apiRequest(`/companies/pickup-stages/${stage.id}/`, {
        method: 'PATCH',
        body: { is_active: !stage.is_active },
      });
      await loadStages();
    } catch (e) {
      setError(e.message || 'Unable to update the stage.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section style={{ display: 'grid', gap: 12 }}>
      <h2 style={{ margin: 0 }}>Route stages</h2>

      <select
        value={routeId}
        onChange={(e) => {
          setRouteId(e.target.value);
          setError('');
          setNote('');
        }}
        style={box}
      >
        <option value="">Choose a route</option>
        {routes.map((r) => (
          <option key={r.id} value={r.id}>
            {r.name}
          </option>
        ))}
      </select>

      {error && <p style={{ margin: 0, color: '#e57373' }}>{error}</p>}
      {note && <p style={{ margin: 0, color: '#81c784' }}>{note}</p>}

      {routeId && (
        <>
          <div style={{ height: 320, borderRadius: 14, overflow: 'hidden' }}>
            <MapContainer center={NAIROBI} zoom={12} style={{ height: '100%', width: '100%' }}>
              <TileLayer
                attribution="&copy; OpenStreetMap contributors"
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              <FitStages stages={stages} />
              <ClickPicker onPick={pick} />

              {stages.map((s) => (
                <CircleMarker
                  key={s.id}
                  center={[Number(s.latitude), Number(s.longitude)]}
                  radius={7}
                  pathOptions={{
                    color: s.is_active ? '#2e7d32' : '#9e9e9e',
                    fillOpacity: 0.85,
                  }}
                >
                  <Tooltip>
                    {s.order}. {s.name}
                    {s.is_active ? '' : ' (off)'}
                  </Tooltip>
                </CircleMarker>
              ))}

              {picked && (
                <CircleMarker
                  center={picked}
                  radius={10}
                  pathOptions={{ color: '#d97706', fillOpacity: 0.5 }}
                />
              )}
            </MapContainer>
          </div>

          <p style={{ margin: 0, fontSize: 13, opacity: 0.8 }}>
            Click the map to place a new stage. Green dots are active stages.
          </p>

          <div style={{ display: 'grid', gap: 8 }}>
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Stage name, e.g. Adams Arcade"
              style={box}
            />

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 90px', gap: 8 }}>
              <input
                value={form.latitude}
                onChange={(e) => setForm({ ...form, latitude: e.target.value })}
                placeholder="Latitude"
                style={box}
              />
              <input
                value={form.longitude}
                onChange={(e) => setForm({ ...form, longitude: e.target.value })}
                placeholder="Longitude"
                style={box}
              />
              <input
                value={form.order}
                onChange={(e) => setForm({ ...form, order: e.target.value })}
                placeholder={`#${nextOrder}`}
                type="number"
                min="0"
                style={box}
              />
            </div>

            <button
              type="button"
              onClick={save}
              disabled={busy}
              style={{
                padding: '12px 16px',
                borderRadius: 12,
                border: 'none',
                background: '#2563eb',
                color: '#fff',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              {busy ? 'Saving...' : 'Add stage'}
            </button>
          </div>

          <div style={{ display: 'grid', gap: 6 }}>
            {stages.length === 0 && (
              <p style={{ margin: 0, opacity: 0.8 }}>No stages on this route yet.</p>
            )}

            {stages.map((s) => (
              <div
                key={s.id}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '8px 12px',
                  borderRadius: 10,
                  border: '1px solid rgba(128,128,128,0.3)',
                  opacity: s.is_active ? 1 : 0.55,
                }}
              >
                <span>
                  <strong>{s.order}.</strong> {s.name}
                  {s.source === 'automatic' ? ' · auto' : ''}
                </span>
                <span style={{ display: 'flex', gap: 6 }}>
                  {s.source === 'automatic' && (
                    <button
                      type="button"
                      onClick={() => approveStage(s)}
                      disabled={busy}
                      style={{
                        padding: '6px 10px',
                        borderRadius: 8,
                        border: 'none',
                        background: '#2563eb',
                        color: '#fff',
                        cursor: 'pointer',
                      }}
                    >
                      Approve
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => toggleActive(s)}
                    disabled={busy}
                    style={{
                      padding: '6px 10px',
                      borderRadius: 8,
                      border: '1px solid rgba(128,128,128,0.4)',
                      background: 'transparent',
                      color: 'inherit',
                      cursor: 'pointer',
                    }}
                  >
                    {s.is_active ? 'Turn off' : 'Turn on'}
                  </button>
                </span>
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
