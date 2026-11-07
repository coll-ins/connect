import { useCallback, useEffect, useState } from 'react';
import { Mail, RefreshCw, ShieldAlert } from 'lucide-react';
import { apiRequest } from '../../api';
import { useAuth } from '../../context/AuthContext';
import './WeeklyReports.css';

const dateLabel = (value) => value
  ? new Date(`${value}T12:00:00`).toLocaleDateString('en-KE', {
    dateStyle: 'medium',
  })
  : '—';

function SummaryList({ title, rows, labelKey = 'status' }) {
  return (
    <section className="weekly-report-summary-section">
      <h3>{title}</h3>
      {rows?.length
        ? <ul>{rows.map((row) => (
          <li key={`${row[labelKey]}-${row.count}`}>
            <span>{row[labelKey]}</span>
            <strong>
              {row.count}
              {row.amount ? ` · KES ${Number(row.amount).toLocaleString('en-KE')}` : ''}
            </strong>
          </li>
        ))}</ul>
        : <p>None recorded</p>}
    </section>
  );
}

export default function WeeklyReports() {
  const { user } = useAuth();
  const companyId = user?.company_id || user?.company?.id || user?.company;
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async (refresh = false) => {
    if (!companyId) {
      setLoading(false);
      setError('Your manager account is not assigned to a company.');
      return;
    }
    if (refresh) setRefreshing(true);
    else setLoading(true);
    setError('');
    try {
      const data = await apiRequest(`/companies/${companyId}/weekly-reports/`);
      setReports(Array.isArray(data) ? data : []);
    } catch (requestError) {
      setError(requestError?.message || 'Weekly reports could not be loaded.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [companyId]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="weekly-reports-page">
      <header className="weekly-reports-heading">
        <div>
          <span>Operations summary</span>
          <h2>Weekly reports</h2>
          <p>
            Review the previous week before auto-renewal, or the day before a
            manual schedule needs renewal.
          </p>
        </div>
        <button type="button" onClick={() => load(true)} disabled={loading || refreshing}>
          <RefreshCw size={16} className={refreshing ? 'weekly-reports-spin' : ''} />
          Refresh
        </button>
      </header>

      {error && <div className="weekly-reports-error" role="alert">{error}</div>}
      {loading && <p role="status">Loading reports…</p>}
      {!loading && !error && reports.length === 0 && (
        <div className="weekly-report-empty">
          Reports appear here on Monday before auto-renewal, or the day before
          a manual schedule expires.
        </div>
      )}

      {reports.map((report) => {
        const summary = report.summary || {};
        const emailStatus = report.email_status || 'skipped';
        return (
          <article className="weekly-report-card" key={report.id}>
            <header>
              <div>
                <span className="weekly-report-kicker">
                  {report.report_type === 'manual_renewal'
                    ? 'Manual renewal reminder'
                    : 'Weekly operations'}
                </span>
                <h3>{dateLabel(report.period_start)} – {dateLabel(report.period_end)}</h3>
                {report.renewal_date && (
                  <p>Renewal due {dateLabel(report.renewal_date)}</p>
                )}
              </div>
              <div className={`weekly-report-email weekly-report-email-${emailStatus}`}>
                <Mail size={15} />
                <span>Email {emailStatus}</span>
              </div>
            </header>
            {report.email_error && (
              <p className="weekly-report-delivery-note" role="status">
                {report.email_error}
              </p>
            )}
            <div className="weekly-report-grid">
              <SummaryList title="Trips" rows={summary.trips_by_status} />
              <SummaryList title="Bookings" rows={summary.bookings_by_status} />
              <SummaryList title="Payments" rows={summary.payments_by_status} />
              <SummaryList title="Incidents by status" rows={summary.incidents_by_status} />
              <SummaryList title="Incidents by type" rows={summary.incidents_by_type} labelKey="type" />
            </div>
            <section className="weekly-report-summary-section weekly-report-issues">
              <h3><ShieldAlert size={16} /> Schedule exceptions</h3>
              {summary.schedule_generation_issues?.length
                ? <ul>{summary.schedule_generation_issues.map((issue) => (
                  <li key={issue.schedule_id}>
                    <span>{issue.route} · {issue.driver}</span>
                    <strong>
                      {issue.driver_unavailable} unavailable · {issue.driver_conflicts} conflicts
                    </strong>
                  </li>
                ))}</ul>
                : <p>No schedule-generation exceptions recorded.</p>}
            </section>
          </article>
        );
      })}
    </div>
  );
}
