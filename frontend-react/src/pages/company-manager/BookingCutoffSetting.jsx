import { useId, useState } from 'react';

import { apiRequest } from '../../api';
import AsyncPanel from '../../components/ui/AsyncPanel';
import useAsyncData from '../../hooks/useAsyncData';
import { parseCutoff } from '../../utils/seatSummary';
import './BookingCutoffSetting.css';

export default function BookingCutoffSetting() {
  const inputId = useId();
  const hintId = useId();
  const query = useAsyncData(() => apiRequest('/companies/booking-settings/', { silent: true }), []);
  // null = untouched, so the field shows the saved value without copying it into state.
  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState(false);
  const [fieldError, setFieldError] = useState('');
  const [result, setResult] = useState(null);

  const saved = query.data?.booking_cutoff_minutes;
  const shown = draft ?? String(saved ?? '');
  const dirty = draft !== null && draft.trim() !== String(saved);

  const submit = async (event) => {
    event.preventDefault();
    if (saving) return;
    setResult(null);
    const { value, error } = parseCutoff(shown);
    setFieldError(error);
    if (error) return;
    setSaving(true);
    try {
      const res = await apiRequest('/companies/booking-settings/', {
        method: 'PATCH',
        body: { booking_cutoff_minutes: value },
        silent: true,
      });
      setDraft(null);
      query.reload();
      setResult({ ok: true, text: `Saved. Online booking now closes ${res?.booking_cutoff_minutes ?? value} minutes before departure.` });
    } catch (e) {
      setResult({ ok: false, text: e?.message || 'Could not save the setting.' });
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="cutoff-card" aria-labelledby={`${inputId}-h`}>
      <h2 id={`${inputId}-h`}>Booking cut-off</h2>
      <AsyncPanel status={query.status} onRetry={query.reload} title="the booking cut-off">
        <form onSubmit={submit} noValidate>
          <label className="cutoff-field" htmlFor={inputId}>
            <span>Close online booking this many minutes before departure</span>
            <input
              id={inputId}
              className="input"
              type="number"
              inputMode="numeric"
              min="0"
              max="240"
              step="1"
              value={shown}
              aria-invalid={fieldError ? 'true' : 'false'}
              aria-describedby={hintId}
              onChange={(e) => { setDraft(e.target.value); setFieldError(''); setResult(null); }}
            />
          </label>
          <small id={hintId} className="cutoff-hint">
            0 to 240. Stage walk-ups can still be booked after online booking closes.
          </small>
          {fieldError && <div className="cutoff-error" role="alert">{fieldError}</div>}
          {result && (
            <div className={result.ok ? 'cutoff-ok' : 'cutoff-error'} role={result.ok ? 'status' : 'alert'}>
              {result.text}
            </div>
          )}
          <button type="submit" className="btn btn-primary" disabled={saving || !dirty}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </form>
      </AsyncPanel>
    </section>
  );
}
