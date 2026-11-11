import { useCallback, useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { apiRequest } from '../../api';
import { useAuth } from '../../context/AuthContext';
import { DEFAULT_VEHICLE, VehicleOptions, driverVehicle, useCompanyBuses } from '../../components/Fleet';
import '../shared/Services.css';
import './ServiceTemplateManager.css';

const dayLabels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const localDate = (date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
const plusDays = (value, days) => {
  const date = value ? new Date(`${value}T12:00:00`) : new Date();
  date.setDate(date.getDate() + days);
  return localDate(date);
};

const blankTemplate = () => {
  const today = localDate(new Date());
  return {
    route_id: '',
    driver_id: '',
    vehicle_type: DEFAULT_VEHICLE,
    days_of_week: [0, 1, 2, 3, 4],
    departure_time: '06:00',
    service_end_time: '18:00',
    normal_interval_minutes: '60',
    rush_interval_minutes: '30',
    rush_start_time: '',
    rush_end_time: '',
    auto_renew: false,
    start_date: today,
    end_date: plusDays(today, 6),
  };
};

export default function ServiceTemplateManager({ companyId: companyIdProp }) {
  const { user } = useAuth();
  const companyId = companyIdProp || user?.company_id || user?.company?.id;
  const { buses } = useCompanyBuses(companyId);
  const [routes, setRoutes] = useState([]);
  const [drivers, setDrivers] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [form, setForm] = useState(blankTemplate);
  const [editingId, setEditingId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const load = useCallback(async () => {
    if (!companyId) {
      setError('This manager account is not assigned to a company.');
      setLoading(false);
      return;
    }
    setLoading(true);
    setError('');
    try {
      const [routeData, driverData, templateData] = await Promise.all([
        apiRequest(`/companies/${companyId}/routes/`),
        apiRequest(`/drivers/?company_id=${companyId}`),
        apiRequest(`/companies/${companyId}/schedules/`),
      ]);
      setRoutes(Array.isArray(routeData) ? routeData : routeData?.results || []);
      setDrivers(Array.isArray(driverData) ? driverData : driverData?.results || []);
      setTemplates(Array.isArray(templateData) ? templateData : []);
    } catch (requestError) {
      setError(requestError?.message || 'Unable to load service templates.');
    } finally {
      setLoading(false);
    }
  }, [companyId]);

  useEffect(() => {
    load();
  }, [load]);

  const update = (key, value) =>
    setForm((current) => ({ ...current, [key]: value }));

  const reset = () => {
    setEditingId(null);
    setForm(blankTemplate());
    setNotice('');
  };

  const edit = (template) => {
    setEditingId(template.id);
    setNotice('');
    setError('');
    setForm({
      route_id: String(template.route_id),
      driver_id: String(template.driver_id),
      bus_id: template.bus_id || '',
      vehicle_type: buses.find((b) => b.id === template.bus_id)?.vehicle_type || DEFAULT_VEHICLE,
      days_of_week: template.days_of_week,
      departure_time: template.departure_time,
      service_end_time: template.service_end_time || '',
      normal_interval_minutes: String(template.normal_interval_minutes || 60),
      rush_interval_minutes: String(template.rush_interval_minutes || 30),
      rush_start_time: template.rush_start_time || '',
      rush_end_time: template.rush_end_time || '',
      auto_renew: Boolean(template.auto_renew),
      start_date: template.start_date || '',
      end_date: template.end_date || '',
    });
  };

  const save = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    setNotice('');
    const body = {
      company_id: Number(companyId),
      route_id: Number(form.route_id),
      driver_id: Number(form.driver_id),
      ...(form.bus_id ? { bus_id: form.bus_id } : { vehicle_type: form.vehicle_type }),
      days_of_week: form.days_of_week,
      departure_time: form.departure_time,
      service_end_time: form.service_end_time || null,
      normal_interval_minutes: Number(form.normal_interval_minutes),
      rush_interval_minutes: Number(form.rush_interval_minutes),
      rush_start_time: form.rush_start_time || null,
      rush_end_time: form.rush_end_time || null,
      auto_renew: form.auto_renew,
      start_date: form.auto_renew ? null : form.start_date,
      end_date: form.auto_renew ? null : form.end_date,
    };
    try {
      const result = await apiRequest(
        editingId
          ? `/companies/schedules/${editingId}/`
          : '/companies/schedules/create/',
        { method: editingId ? 'PATCH' : 'POST', body },
      );
      setNotice(
        `${editingId ? 'Service template updated' : 'Service template created'}${result?.generated_trips ? ` · ${result.generated_trips} trips generated` : ''}.`,
      );
      setEditingId(null);
      setForm(blankTemplate());
      await load();
    } catch (requestError) {
      setError(requestError?.message || 'Unable to save this service template.');
    } finally {
      setBusy(false);
    }
  };

  const setActive = async (template, isActive) => {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const result = await apiRequest(`/companies/schedules/${template.id}/`, {
        method: 'PATCH',
        body: { is_active: isActive },
      });
      setNotice(
        `${isActive ? 'Service resumed' : 'Service paused'}${result?.cancelled_trips ? ` · ${result.cancelled_trips} unbooked trips cancelled` : ''}.`,
      );
      await load();
    } catch (requestError) {
      setError(requestError?.message || 'Unable to update service status.');
    } finally {
      setBusy(false);
    }
  };

  const renew = async (template) => {
    const today = localDate(new Date());
    const start = template.end_date && template.end_date >= today
      ? plusDays(template.end_date, 1)
      : today;
    const end = plusDays(start, 6);
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await apiRequest(`/companies/schedules/${template.id}/`, {
        method: 'PATCH',
        body: { start_date: start, end_date: end },
      });
      setNotice(`Manual service renewed for ${start} through ${end}.`);
      await load();
    } catch (requestError) {
      setError(requestError?.message || 'Unable to renew this service.');
    } finally {
      setBusy(false);
    }
  };

  const toggleDay = (day) => {
    const selected = new Set(form.days_of_week);
    if (selected.has(day)) selected.delete(day);
    else selected.add(day);
    update('days_of_week', [...selected].sort());
  };

  return (
    <div className="svc-page">
      <section className="svc-head">
        <div>
          <span className="glass-eyebrow">Weekly service</span>
          <h1>Service templates</h1>
          <p>
            Set regular departures for a route. Choose manual weekly renewal,
            or explicitly turn on auto-renew.
          </p>
        </div>
        <button type="button" className="btn btn-ghost" onClick={load} disabled={loading || busy}>
          <RefreshCw size={17} className={loading ? 'service-template-spin' : ''} />
          Refresh
        </button>
      </section>

      {error && <div className="svc-error" role="alert">{error}</div>}
      {notice && <div className="svc-note" role="status">{notice}</div>}

      <section className="svc-card">
        <div className="service-template-heading">
          <div>
            <span className="glass-eyebrow">{editingId ? 'Edit service' : 'New service'}</span>
            <h2>{editingId ? 'Update weekly template' : 'Create weekly template'}</h2>
          </div>
        </div>
        <form className="service-template-form svc-form" onSubmit={save}>
          <label className="svc-field">
            Route
            <select className="input" required value={form.route_id} onChange={(event) => update('route_id', event.target.value)}>
              <option value="">Choose a route</option>
              {routes.map((route) => <option key={route.id} value={route.id}>{route.name}</option>)}
            </select>
          </label>
          <label className="svc-field">
            Driver
            <select className="input" required value={form.driver_id} onChange={(event) => setForm((f) => ({
              ...f,
              driver_id: event.target.value,
              bus_id: '',
              vehicle_type: driverVehicle(buses, drivers.find((d) => String(d.id) === event.target.value)) || f.vehicle_type,
            }))}>
              <option value="">Choose a driver</option>
              {drivers.map((driver) => <option key={driver.id} value={driver.id}>{driver.name || driver.username} · {driver.bus_number || 'No bus number'}</option>)}
            </select>
          </label>
          <label className="svc-field">
            Vehicle (its seats are each trip's seats)
            <select className="input" required value={form.vehicle_type} onChange={(event) => setForm((f) => ({ ...f, bus_id: '', vehicle_type: event.target.value }))}>
              <VehicleOptions />
            </select>
          </label>
          <fieldset className="service-template-days">
            <legend>Operating days</legend>
            {dayLabels.map((day, index) => (
              <label key={day}>
                <input type="checkbox" checked={form.days_of_week.includes(index)} onChange={() => toggleDay(index)} />
                {day}
              </label>
            ))}
          </fieldset>
          <label className="svc-field">
            First departure
            <input className="input" type="time" required value={form.departure_time} onChange={(event) => update('departure_time', event.target.value)} />
          </label>
          <label className="svc-field">
            Last departure
            <input className="input" type="time" required value={form.service_end_time} onChange={(event) => update('service_end_time', event.target.value)} />
          </label>
          <label className="svc-field">
            Normal frequency (minutes)
            <input className="input" type="number" min="15" max="240" required value={form.normal_interval_minutes} onChange={(event) => update('normal_interval_minutes', event.target.value)} />
          </label>
          <label className="svc-field">
            Rush-hour frequency (minutes)
            <input className="input" type="number" min="15" max="240" required value={form.rush_interval_minutes} onChange={(event) => update('rush_interval_minutes', event.target.value)} />
          </label>
          <label className="svc-field">
            Rush-hour starts (optional)
            <input className="input" type="time" value={form.rush_start_time} onChange={(event) => update('rush_start_time', event.target.value)} />
          </label>
          <label className="svc-field">
            Rush-hour ends (optional)
            <input className="input" type="time" value={form.rush_end_time} onChange={(event) => update('rush_end_time', event.target.value)} />
          </label>
          <label className="svc-check service-template-renew">
            <input
              type="checkbox"
              checked={form.auto_renew}
              onChange={(event) => {
                const enabled = event.target.checked;
                setForm((current) => ({
                  ...current,
                  auto_renew: enabled,
                  start_date: enabled ? '' : current.start_date || localDate(new Date()),
                  end_date: enabled ? '' : current.end_date || plusDays(localDate(new Date()), 6),
                }));
              }}
            />
            <span>
              <strong>Enable auto-renew</strong>
              <small>Off by default. When enabled, this template keeps generating a rolling seven-day trip window.</small>
            </span>
          </label>
          {!form.auto_renew && (
            <>
                  <label className="svc-field">
                Manual week starts
                    <input className="input" type="date" required value={form.start_date} onChange={(event) => update('start_date', event.target.value)} />
              </label>
                  <label className="svc-field">
                Manual week ends
                    <input className="input" type="date" required value={form.end_date} onChange={(event) => update('end_date', event.target.value)} />
              </label>
            </>
          )}
              <div className="svc-actions service-template-actions">
                <button type="submit" className="btn btn-primary" disabled={busy || !form.days_of_week.length}>
              {busy ? 'Saving…' : editingId ? 'Save changes' : 'Create service'}
            </button>
                {editingId && <button type="button" className="btn btn-ghost" onClick={reset} disabled={busy}>Cancel edit</button>}
          </div>
              <small className="service-template-hint">
            Default frequency is one trip per hour, with one every 30 minutes during the optional rush-hour window. Times use the company’s local timezone.
          </small>
        </form>
      </section>

      <section className="svc-card">
        <div className="service-template-heading">
          <div>
            <span className="glass-eyebrow">Manage services</span>
            <h2>{templates.length} service templates</h2>
          </div>
        </div>
        <div className="service-template-list">
          {templates.map((template) => (
            <article key={template.id} className="service-template-card">
              <div>
                <div className="service-template-card-title">
                  <h3>{template.route_name}</h3>
                  <span className={`svc-badge ${template.is_active ? 'svc-st-confirmed' : 'svc-st-cancelled'}`}>
                    {template.is_active ? 'Active' : 'Paused'}
                  </span>
                </div>
                <p>{template.driver_name} · {template.bus_plate ? `Bus ${template.bus_number} · ${template.bus_plate}` : 'No bus assigned: edit to pick one'} · {template.capacity} seats</p>
                <p>
                  {template.departure_time}–{template.service_end_time || template.departure_time}
                  {' · '}{template.normal_interval_minutes || 60} min normal
                  {template.rush_start_time && ` · ${template.rush_start_time}–${template.rush_end_time} at ${template.rush_interval_minutes || 30} min`}
                </p>
                <p>
                  {template.days_of_week.map((day) => dayLabels[day]).join(', ')}
                  {' · '}{template.auto_renew ? 'Auto-renews' : `Manual · ${template.start_date} to ${template.end_date}`}
                </p>
              </div>
              <div className="service-template-card-actions">
                {!template.auto_renew && <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => renew(template)}>Renew next week</button>}
                <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => edit(template)}>Edit</button>
                <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => setActive(template, !template.is_active)}>
                  {template.is_active ? 'Pause' : 'Resume'}
                </button>
              </div>
            </article>
          ))}
          {!loading && templates.length === 0 && (
            <div className="service-template-empty">
              No weekly service templates yet. Creating one leaves one-off trip creation unchanged.
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
