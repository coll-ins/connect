import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  BarChart3,
  Bell,
  Bus,
  Building2,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  Database,
  DollarSign,
  LayoutDashboard,
  LogOut,
  Plus,
  RefreshCw,
  Route as RouteIcon,
  Settings,
  ShieldCheck,
  Trash2,
  UserRound,
  Users,
  X,
  Menu,
} from 'lucide-react';
import {
  NavLink,
  useLocation,
  useNavigate,
  Navigate,
} from 'react-router-dom';
import { apiRequest } from '../../api';
import { useAuth } from '../../context/AuthContext';

const money = (value) =>
  `KES ${Number(value || 0).toLocaleString('en-KE', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

const formatDate = (value) =>
  value
    ? new Date(value).toLocaleString('en-KE', {
        dateStyle: 'medium',
        timeStyle: 'short',
      })
    : '—';

const list = (value) =>
  Array.isArray(value)
    ? value
    : value?.results || value?.data || [];

const emptyCompany = {
  name: '',
  description: '',
  areas_served: '',
  phone_number: '',
};

const emptyRoute = {
  name: '',
  start_point: '',
  end_point: '',
  price: '',
  company_id: '',
};

const emptyDriver = {
  name: '',
  phone_number: '',
  password: '',
  bus_number: '',
  company: '',
};

const emptyTrip = {
  route_id: '',
  driver_id: '',
  departure_at: '',
  capacity: 14,
  company_id: '',
};

const emptyOperator = {
  username: '',
  email: '',
  phone_number: '',
  location: '',
  role: 'company_manager',
  company: '',
  password: '',
};

const SIMULATABLE_STATUSES = ['scheduled', 'boarding', 'departed'];

function TripSimulateControl({ trip, sim, busy, onStart, onStop }) {
  const running = sim?.status === 'running';
  if (running && sim.trip_id === trip.id) {
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
        <span
          aria-hidden="true"
          style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--accent)' }}
        />
        <span role="status" style={{ fontVariantNumeric: 'tabular-nums' }}>
          Moving · {sim.progress}%
        </span>
        <button
          type="button"
          className="pa-danger-button"
          onClick={onStop}
          disabled={busy}
        >
          Stop
        </button>
      </span>
    );
  }
  let reason = '';
  if (running) reason = 'Another trip is being simulated. Stop it first.';
  else if (!SIMULATABLE_STATUSES.includes(trip.status)) {
    reason = 'Only scheduled, boarding or departed trips can be simulated.';
  } else if (!(trip.driver || trip.driver_name)) reason = 'Assign a driver first.';
  return (
    <button
      type="button"
      className="pa-secondary-button"
      onClick={() => onStart(trip)}
      disabled={Boolean(reason) || busy}
      title={reason || undefined}
    >
      Simulate
    </button>
  );
}

/*
 * The rest of the journey, for testing it end to end: send the bus off its
 * route, board passengers with their PIN, then end the trip.
 */
function TripJourneyControls({ trip, sim, bookings, busy, onDivert, onBoard, onEnd }) {
  const tripStatus = String(trip.status || '').toLowerCase();
  if (!['boarding', 'departed'].includes(tripStatus)) return null;

  const waiting = bookings.filter(
    (b) => String(b.trip_id) === String(trip.id) && b.status === 'confirmed',
  );
  const moving = sim?.status === 'running' && sim.trip_id === trip.id;

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
      {moving && (
        <button type="button" className="pa-secondary-button" onClick={onDivert} disabled={busy}>
          Divert bus
        </button>
      )}
      {waiting.map((b) => (
        <button
          type="button"
          className="pa-secondary-button"
          key={b.booking_id}
          onClick={() => onBoard(b)}
          disabled={busy}
        >
          Board {b.booking_number}
        </button>
      ))}
      <button type="button" className="pa-danger-button" onClick={() => onEnd(trip)} disabled={busy}>
        End trip
      </button>
    </div>
  );
}

function SideLink({ to, icon: Icon, children, end = false }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `pa-link ${isActive ? 'active' : ''}`
      }
    >
      <Icon size={18} />
      <span>{children}</span>
    </NavLink>
  );
}

function PlatformShell({ logout, children }) {
  const [mobileOpen, setMobileOpen] = useState(false);

  const closeMobile = () => setMobileOpen(false);

  return (
    <div className="pa-shell">
      <style>{`
        .pa-shell {
          min-height: 100vh;
          display: flex;
          background:
            var(--surface);
          color: var(--text);
        }

        .pa-sidebar {
          width: 255px;
          min-height: 100vh;
          position: fixed;
          left: 0;
          top: 0;
          bottom: 0;
          padding: 22px 16px;
          display: flex;
          flex-direction: column;
          background: var(--bg);
          border-right: 1px solid rgba(255,255,255,.08);
          z-index: 20;
        }

        .pa-brand {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 6px 8px 22px;
        }

        .pa-brand-mark {
          width: 40px;
          height: 40px;
          border-radius: 14px;
          display: grid;
          place-items: center;
          font-weight: 700;
          background: var(--accent);
          color: var(--accent-ink);
          box-shadow: none;
        }

        .pa-brand strong,
        .pa-admin-card strong {
          display: block;
        }

        .pa-brand small,
        .pa-admin-card span {
          color: var(--text-3);
          font-size: 11px;
        }

        .pa-admin-card {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 12px;
          margin-bottom: 18px;
          border: 1px solid rgba(255,255,255,.08);
          border-radius: 14px;
          background: rgba(255,255,255,.035);
        }

        .pa-admin-icon {
          width: 34px;
          height: 34px;
          display: grid;
          place-items: center;
          border-radius: 10px;
          color: var(--accent-text);
          background: rgb(var(--accent-rgb) / 0.12);
        }

        .pa-nav {
          display: flex;
          flex-direction: column;
          gap: 4px;
          overflow-y: auto;
        }

        .pa-nav-label {
          margin: 15px 8px 5px;
          color: var(--text-3);
          font-size: 11px;
          font-weight: 600;
          letter-spacing: 0;
        }

        .pa-link {
          display: flex;
          align-items: center;
          gap: 11px;
          padding: 10px 11px;
          border-radius: 10px;
          color: var(--text-2);
          text-decoration: none;
          font-size: 13px;
          transition: .18s ease;
        }

        .pa-link:hover {
          color: var(--text);
          background: rgba(255,255,255,.045);
        }

        .pa-link.active {
          color: var(--text);
          background: rgb(var(--accent-rgb) / 0.13);
          box-shadow: none;
        }

        .pa-logout {
          margin-top: auto;
          border: 1px solid rgba(255,255,255,.08);
          border-radius: 10px;
          background: rgba(255,255,255,.035);
          color: var(--text-2);
          padding: 11px;
          display: flex;
          gap: 10px;
          align-items: center;
          cursor: pointer;
        }

        .pa-mobile-menu,
        .pa-mobile-backdrop {
          display: none;
        }

        .pa-main {
          margin-left: 255px;
          width: calc(100% - 255px);
          min-height: 100vh;
        }

        @media (max-width: 800px) {
          .pa-mobile-menu {
            display: grid;
            place-items: center;
            position: fixed;
            top: 12px;
            left: 12px;
            width: 44px;
            height: 44px;
            z-index: 100;
            border: 1px solid rgba(255,255,255,.10);
            border-radius: 14px;
            background: var(--bg);
            color: var(--text);
            font-size: 22px;
            line-height: 1;
            cursor: pointer;
            backdrop-filter: blur(18px);
            box-shadow: 0 10px 30px rgba(0,0,0,.28);
          }

          .pa-mobile-backdrop {
            display: block;
            position: fixed;
            inset: 0;
            z-index: 110;
            border: 0;
            background: rgba(0,0,0,.48);
            backdrop-filter: blur(2px);
          }

          .pa-sidebar {
            width: min(280px, 84vw) !important;
            min-width: min(280px, 84vw) !important;
            transform: translateX(-105%);
            transition: transform .22s ease;
            z-index: 120;
            overflow-y: auto;
          }

          .pa-sidebar.pa-sidebar-open {
            transform: translateX(0);
          }

          .pa-main {
            width: 100% !important;
            margin-left: 0 !important;
            min-height: 100vh;
          }

          .pa-topbar {
            padding-left: 68px;
          }
        }

        @media (max-width: 430px) {
          .pa-mobile-menu {
            top: 9px;
            left: 9px;
            width: 42px;
            height: 42px;
          }

          .pa-topbar {
            padding-left: 62px;
          }
        }

        .pa-topbar {
          position: sticky;
          top: 0;
          z-index: 10;
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 19px 30px;
          background: var(--bg);
          border-bottom: 1px solid rgba(255,255,255,.07);
          backdrop-filter: blur(18px);
        }

        .pa-overline,
        .pa-card-eyebrow {
          color: var(--accent-text);
          font-size: 11px;
          font-weight: 600;
          letter-spacing: 0;
        }

        .pa-topbar-title {
          margin: 0;
          font-size: 20px;
          font-weight: 600;
          line-height: 1.2;
        }

        .pa-page-head {
          justify-content: flex-end !important;
          margin-bottom: 16px !important;
        }

        @media (max-width: 800px) {
          .pa-user > div:not(.pa-avatar),
          .pa-system-status > svg {
            display: none;
          }

          .pa-system-status > span:not(.pa-status-dot) {
            position: absolute;
            width: 1px;
            height: 1px;
            overflow: hidden;
            clip: rect(0 0 0 0);
            white-space: nowrap;
          }

          .pa-topbar {
            min-height: 68px;
            padding: 12px 16px 12px 68px;
            gap: 12px;
          }

          .pa-topbar-title {
            font-size: 18px;
          }
        }

        .pa-user {
          display: flex;
          align-items: center;
          gap: 10px;
        }

        .pa-user strong,
        .pa-user span {
          display: block;
        }

        .pa-user span {
          color: var(--text-3);
          font-size: 11px;
        }

        .pa-avatar {
          width: 36px;
          height: 36px;
          display: grid;
          place-items: center;
          border-radius: 50%;
          background: rgb(var(--accent-rgb) / 0.16);
          color: var(--accent-text);
          font-weight: 700;
        }

        .pa-content {
          padding: 28px;
          max-width: 1500px;
          margin: auto;
        }

        .pa-system-status {
          border: 1px solid rgba(255,255,255,.09);
          background: rgba(255,255,255,.04);
          color: var(--text-2);
          border-radius: 10px;
          padding: 8px 11px;
          display: inline-flex;
          align-items: center;
          gap: 8px;
          cursor: pointer;
        }

        .pa-system-status.healthy {
          color: var(--accent-text);
        }

        .pa-system-status.warning {
          color: var(--warn);
        }

        .pa-system-status.critical {
          color: var(--danger-text);
        }

        .pa-status-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: currentColor;
          box-shadow: 0 0 12px currentColor;
        }

        .pa-page-head,
        .pa-section-heading {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          gap: 20px;
          margin-bottom: 22px;
        }

        .pa-page-head h1,
        .pa-section-heading h3 {
          margin: 4px 0;
          font-size: 25px;
        }

        .pa-page-head p,
        .pa-section-heading p {
          margin: 0;
          color: var(--text-3);
          font-size: 13px;
        }

        .pa-page-actions {
          display: flex;
          gap: 8px;
          align-items: center;
        }

        .pa-primary-button,
        .pa-secondary-button,
        .pa-danger-button {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          gap: 7px;
          border-radius: 10px;
          padding: 10px 14px;
          cursor: pointer;
          font-weight: 700;
          font-size: 12px;
          border: 1px solid transparent;
        }

        .pa-primary-button {
          background: var(--accent);
          color: #04150f;
        }

        .pa-primary-button:hover {
          background: var(--accent);
        }

        .pa-secondary-button {
          color: var(--text);
          background: rgba(255,255,255,.045);
          border-color: rgba(255,255,255,.08);
        }

        .pa-danger-button {
          color: var(--text);
          background: rgb(var(--danger-rgb) / 0.09);
          border-color: rgb(var(--danger-rgb) / 0.2);
        }

        button:disabled {
          opacity: .55;
          cursor: not-allowed;
        }

        .pa-stat-grid {
          display: grid;
          grid-template-columns: repeat(4,minmax(0,1fr));
          gap: 13px;
          margin-bottom: 20px;
        }

        .pa-stat-card,
        .pa-command-card,
        .pa-panel,
        .pa-test-summary > div,
        .pa-issue-summary-card {
          border: 1px solid rgba(255,255,255,.08);
          background: rgba(255,255,255,.035);
          border-radius: 14px;
        }

        .pa-stat-card {
          padding: 17px;
        }

        .pa-stat-card span {
          display: block;
          color: var(--text-3);
          font-size: 11px;
          margin-bottom: 7px;
        }

        .pa-stat-card strong {
          font-size: 24px;
        }

        .pa-command-grid {
          display: grid;
          grid-template-columns: repeat(2,minmax(0,1fr));
          gap: 14px;
          margin-bottom: 14px;
        }

        .pa-command-card {
          padding: 19px;
        }

        .pa-command-card-head {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
        }

        .pa-command-card h3 {
          margin: 5px 0 0;
          font-size: 17px;
        }

        .pa-command-card p {
          color: var(--text-3);
          line-height: 1.6;
          font-size: 13px;
        }

        .pa-command-icon {
          width: 40px;
          height: 40px;
          border-radius: 10px;
          display: grid;
          place-items: center;
          background: rgb(var(--accent-rgb) / 0.11);
          color: var(--accent-text);
        }

        .pa-command-icon.warning {
          color: var(--warn);
          background: rgb(var(--warn-rgb) / 0.1);
        }

        .pa-command-icon.critical {
          color: var(--danger-text);
          background: rgb(var(--danger-rgb) / 0.1);
        }

        .pa-command-message {
          padding: 11px 14px;
          border: 1px solid rgb(var(--accent-rgb) / 0.2);
          background: rgb(var(--accent-rgb) / 0.07);
          color: var(--accent-text);
          border-radius: 10px;
          margin-bottom: 16px;
          font-size: 12px;
        }

        .pa-demo-map {
          overflow: hidden;
          margin-top: 16px;
          border: 1px solid rgba(255,255,255,.08);
          border-radius: 14px;
        }

        .pa-demo-bus-icon {
          display: grid;
          place-items: center;
          border: 2px solid white;
          border-radius: 999px;
          background: var(--accent);
          box-shadow: 0 2px 9px rgba(0,0,0,.4);
          color: var(--accent-ink);
          font-size: 11px;
          font-weight: 700;
        }

        .pa-demo-meta {
          display: flex;
          align-items: center;
          flex-wrap: wrap;
          gap: 8px 18px;
          color: var(--text-2);
          font-size: 12px;
        }

        .pa-two-col {
          display: grid;
          grid-template-columns: 1.4fr 1fr;
          gap: 15px;
        }

        .pa-panel {
          padding: 18px;
          margin-bottom: 15px;
        }

        .pa-panel-header {
          display: flex;
          justify-content: space-between;
          gap: 12px;
          margin-bottom: 15px;
        }

        .pa-panel-header h3 {
          margin: 0;
          font-size: 15px;
        }

        .pa-panel-header p {
          margin: 4px 0 0;
          color: var(--text-3);
          font-size: 12px;
        }

        .pa-list {
          display: flex;
          flex-direction: column;
        }

        .pa-list-row,
        .pa-report-row,
        .pa-setting-row,
        .pa-test-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          padding: 12px 0;
          border-bottom: 1px solid rgba(255,255,255,.055);
        }

        .pa-list-row:last-child,
        .pa-report-row:last-child,
        .pa-setting-row:last-child,
        .pa-test-row:last-child {
          border-bottom: 0;
        }

        .pa-list-row strong,
        .pa-report-row strong,
        .pa-setting-row strong,
        .pa-test-row strong {
          display: block;
          font-size: 13px;
        }

        .pa-list-row span,
        .pa-report-row span,
        .pa-setting-row span,
        .pa-test-row span {
          color: var(--text-3);
          font-size: 11px;
        }

        .pa-table-wrap {
          overflow-x: auto;
        }

        .pa-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 12px;
        }

        .pa-table th {
          text-align: left;
          color: var(--text-3);
          font-weight: 700;
          padding: 11px 10px;
          border-bottom: 1px solid rgba(255,255,255,.08);
        }

        .pa-table td {
          padding: 12px 10px;
          border-bottom: 1px solid rgba(255,255,255,.055);
          color: var(--text);
        }

        .pa-table td strong {
          color: var(--text);
        }

        .pa-actions {
          display: flex;
          gap: 6px;
          justify-content: flex-end;
        }

        .pa-icon-button {
          width: 31px;
          height: 31px;
          border: 1px solid rgba(255,255,255,.08);
          background: rgba(255,255,255,.035);
          color: var(--text-2);
          border-radius: 10px;
          display: grid;
          place-items: center;
          cursor: pointer;
        }

        .pa-icon-button.danger {
          color: var(--danger-text);
        }

        .pa-badge {
          display: inline-flex;
          align-items: center;
          padding: 4px 8px;
          border-radius: 999px;
          font-size: 11px;
          font-weight: 700;
          background: rgb(var(--accent-rgb) / 0.1);
          color: var(--accent-text);
        }

        .pa-badge.warning {
          background: rgb(var(--warn-rgb) / 0.1);
          color: var(--warn);
        }

        .pa-badge.danger {
          background: rgb(var(--danger-rgb) / 0.1);
          color: var(--danger-text);
        }

        .pa-badge.muted {
          background: rgba(148,163,184,.1);
          color: var(--text-2);
        }

        .pa-empty-state {
          min-height: 220px;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 8px;
          color: var(--text-3);
          text-align: center;
          border: 1px dashed rgba(255,255,255,.1);
          border-radius: 14px;
          padding: 25px;
        }

        .pa-empty-state strong {
          color: var(--text);
        }

        .pa-form {
          display: grid;
          gap: 12px;
        }

        .pa-form-grid {
          display: grid;
          grid-template-columns: repeat(2,minmax(0,1fr));
          gap: 12px;
        }

        .pa-field {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .pa-field.full {
          grid-column: 1/-1;
        }

        .pa-field label {
          color: var(--text-2);
          font-size: 11px;
          font-weight: 700;
        }

        .pa-field input,
        .pa-field select,
        .pa-field textarea {
          width: 100%;
          box-sizing: border-box;
          border: 1px solid rgba(255,255,255,.09);
          border-radius: 10px;
          background: rgba(0,0,0,.18);
          color: var(--text);
          padding: 10px 11px;
          outline: none;
          font: inherit;
          font-size: 12px;
        }

        .pa-field textarea {
          min-height: 82px;
          resize: vertical;
        }

        .pa-field input:focus,
        .pa-field select:focus,
        .pa-field textarea:focus {
          border-color: rgb(var(--accent-rgb) / 0.5);
        }

        .pa-modal-backdrop {
          position: fixed;
          inset: 0;
          z-index: 100;
          background: var(--bg);
          display: grid;
          place-items: center;
          padding: 20px;
        }

        .pa-modal {
          width: min(700px,100%);
          max-height: 90vh;
          overflow-y: auto;
          background: var(--surface);
          border: 1px solid rgba(255,255,255,.1);
          border-radius: 16px;
          box-shadow: 0 25px 80px rgba(0,0,0,.5);
          padding: 22px;
        }

        .pa-modal-head {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          margin-bottom: 18px;
        }

        .pa-modal-head h3 {
          margin: 0;
        }

        .pa-modal-head p {
          margin: 5px 0 0;
          color: var(--text-3);
          font-size: 12px;
        }

        .pa-modal-actions {
          display: flex;
          justify-content: flex-end;
          gap: 8px;
          margin-top: 18px;
        }

        .pa-error {
          padding: 11px 13px;
          margin-bottom: 15px;
          border-radius: 10px;
          color: var(--text);
          background: rgb(var(--danger-rgb) / 0.08);
          border: 1px solid rgb(var(--danger-rgb) / 0.18);
          font-size: 12px;
        }

        .pa-issue-summary {
          display: grid;
          grid-template-columns: repeat(3,1fr);
          gap: 13px;
          margin-bottom: 15px;
        }

        .pa-issue-summary-card {
          padding: 17px;
          display: flex;
          align-items: center;
          gap: 12px;
        }

        .pa-issue-summary-card.critical {
          color: var(--danger-text);
        }

        .pa-issue-summary-card.warning {
          color: var(--warn);
        }

        .pa-issue-summary-card.healthy {
          color: var(--accent-text);
        }

        .pa-issue-summary-card strong,
        .pa-issue-summary-card span {
          display: block;
        }

        .pa-issue-summary-card strong {
          color: inherit;
          font-size: 21px;
        }

        .pa-issue-summary-card span {
          color: var(--text-3);
          font-size: 11px;
        }

        .pa-issue-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .pa-issue-row {
          width: 100%;
          display: flex;
          align-items: center;
          gap: 12px;
          text-align: left;
          padding: 13px;
          border-radius: 10px;
          border: 1px solid rgba(255,255,255,.06);
          background: rgba(255,255,255,.025);
          color: inherit;
          cursor: pointer;
        }

        .pa-issue-row.critical {
          border-color: rgb(var(--danger-rgb) / 0.18);
        }

        .pa-issue-row.warning {
          border-color: rgb(var(--warn-rgb) / 0.15);
        }

        .pa-issue-icon {
          flex: 0 0 auto;
        }

        .pa-issue-row.critical .pa-issue-icon {
          color: var(--danger-text);
        }

        .pa-issue-row.warning .pa-issue-icon {
          color: var(--warn);
        }

        .pa-issue-content {
          flex: 1;
        }

        .pa-issue-content strong,
        .pa-issue-content span {
          display: block;
        }

        .pa-issue-content strong {
          font-size: 13px;
        }

        .pa-issue-content span {
          color: var(--text-3);
          font-size: 11px;
          margin-top: 3px;
        }

        .pa-test-summary {
          display: grid;
          grid-template-columns: repeat(4,1fr);
          gap: 12px;
          margin-bottom: 15px;
        }

        .pa-test-summary > div {
          padding: 16px;
        }

        .pa-test-summary strong,
        .pa-test-summary span {
          display: block;
        }

        .pa-test-summary strong {
          font-size: 21px;
        }

        .pa-test-summary span {
          color: var(--text-3);
          font-size: 11px;
          margin-top: 4px;
        }

        .pa-test-row {
          justify-content: flex-start;
        }

        .pa-test-icon {
          width: 32px;
          height: 32px;
          display: grid;
          place-items: center;
          border-radius: 10px;
          background: rgba(255,255,255,.04);
        }

        .pa-test-row.passed .pa-test-icon {
          color: var(--accent-text);
        }

        .pa-test-row.warning .pa-test-icon {
          color: var(--warn);
        }

        .pa-test-row.failed .pa-test-icon {
          color: var(--danger-text);
        }

        .pa-test-row > div:nth-child(2) {
          flex: 1;
        }

        .pa-test-status {
          padding: 4px 8px;
          border-radius: 999px;
          font-size: 11px !important;
          font-weight: 600;
          background: rgba(255,255,255,.05);
        }

        .pa-report-list,
        .pa-settings-list {
          display: flex;
          flex-direction: column;
        }

        .pa-report-row {
          padding: 13px 0;
        }

        .pa-setting-row {
          padding: 14px 0;
        }

        .pa-setting-value {
          color: var(--accent-text) !important;
        }

        .pa-spin {
          animation: pa-spin 1s linear infinite;
        }

        @keyframes pa-spin {
          to { transform: rotate(360deg); }
        }

        @media (max-width: 1100px) {
          .pa-stat-grid {
            grid-template-columns: repeat(2,1fr);
          }

          .pa-two-col {
            grid-template-columns: 1fr;
          }
        }

        @media (max-width: 800px) {
          .pa-sidebar {
            width: 220px;
            min-width: 220px;
          }

          .pa-brand div:last-child,
          .pa-admin-card > div:last-child,
          .pa-link span,
          .pa-nav-label,
          .pa-logout {
            display: block;
          }

          .pa-main {
            margin-left: 220px;
            width: calc(100% - 220px);
          }

          .pa-link {
            justify-content: flex-start;
          }

          .pa-command-grid,
          .pa-issue-summary,
          .pa-test-summary {
            grid-template-columns: 1fr;
          }

          .pa-form-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>

      <button
        type="button"
        className="pa-mobile-menu"
        onClick={() => setMobileOpen(true)}
        aria-label="Open navigation"
      >
        <Menu size={20} aria-hidden="true" />
      </button>

      {mobileOpen && (
        <button
          type="button"
          className="pa-mobile-backdrop"
          onClick={closeMobile}
          aria-label="Close navigation"
        />
      )}

      <aside className={`pa-sidebar ${mobileOpen ? 'pa-sidebar-open' : ''}`}>
        <div className="pa-brand">
          <div className="pa-brand-mark">C</div>
          <div>
            <strong>CONNECT</strong>
            <small>Platform Control</small>
          </div>
        </div>

        <div className="pa-admin-card">
          <div className="pa-admin-icon">
            <ShieldCheck size={18} />
          </div>
          <div>
            <strong>Platform Admin</strong>
            <span>Global access</span>
          </div>
        </div>

        <nav className="pa-nav">
          <p className="pa-nav-label">Control</p>

          <SideLink to="/platform-admin" icon={LayoutDashboard} end onClick={closeMobile}>
            Overview
          </SideLink>

          <SideLink to="/platform-admin/companies" onClick={closeMobile} icon={Building2}>
            Companies
          </SideLink>

          <SideLink to="/platform-admin/routes" onClick={closeMobile} icon={RouteIcon}>
            Routes
          </SideLink>

          <SideLink to="/platform-admin/trips" onClick={closeMobile} icon={CalendarDays}>
            Trips
          </SideLink>

          <SideLink to="/platform-admin/drivers" onClick={closeMobile} icon={Bus}>
            Drivers
          </SideLink>

          <SideLink to="/platform-admin/operators" onClick={closeMobile} icon={Users}>
            Operators
          </SideLink>

          <SideLink to="/platform-admin/bookings" onClick={closeMobile} icon={ClipboardList}>
            Bookings
          </SideLink>

          <p className="pa-nav-label">Insights</p>

          <SideLink to="/platform-admin/users" onClick={closeMobile} icon={UserRound}>
            Users
          </SideLink>

          <SideLink to="/platform-admin/reports" onClick={closeMobile} icon={BarChart3}>
            Reports
          </SideLink>

          <SideLink to="/platform-admin/revenue" onClick={closeMobile} icon={DollarSign}>
            Revenue
          </SideLink>

          <p className="pa-nav-label">System</p>

          <SideLink to="/platform-admin/issues" onClick={closeMobile} icon={AlertTriangle}>
            Issues
          </SideLink>

          <SideLink to="/platform-admin/system-tests" onClick={closeMobile} icon={Database}>
            System Tests
          </SideLink>

          <SideLink to="/platform-admin/settings" onClick={closeMobile} icon={Settings}>
            Settings
          </SideLink>
        </nav>

        <button
          className="pa-logout"
          onClick={() => {
            closeMobile();
            logout();
          }}
        >
          <LogOut size={18} />
          Logout
        </button>
      </aside>

      <div className="pa-main">
        {children}
      </div>
    </div>
  );
}

export default function PlatformAdminDashboard() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  const section =
    location.pathname
      .replace('/platform-admin', '')
      .split('/')
      .filter(Boolean)[0] || 'overview';

  const [companies, setCompanies] = useState([]);
  const [routes, setRoutes] = useState([]);
  const [drivers, setDrivers] = useState([]);
  const [trips, setTrips] = useState([]);
  const [bookings, setBookings] = useState([]);
  const [users, setUsers] = useState([]);
  const [operators, setOperators] = useState([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [commandMessage, setCommandMessage] = useState('');

  const [currentTime, setCurrentTime] = useState(() => Date.now());

  const [systemChecks, setSystemChecks] = useState(null);
  const [systemTestLoading, setSystemTestLoading] = useState(false);
  const [sim, setSim] = useState(null);
  const [simBusy, setSimBusy] = useState(false);
  const [simError, setSimError] = useState('');

  const [companyModal, setCompanyModal] = useState(false);
  const [companyForm, setCompanyForm] = useState(emptyCompany);
  const [companyEditingId, setCompanyEditingId] = useState(null);
  const [companySaving, setCompanySaving] = useState(false);

  const [routeModal, setRouteModal] = useState(false);
  const [routeForm, setRouteForm] = useState(emptyRoute);
  const [routeEditingId, setRouteEditingId] = useState(null);
  const [routeSaving, setRouteSaving] = useState(false);

  const [driverModal, setDriverModal] = useState(false);
  const [driverForm, setDriverForm] = useState(emptyDriver);
  const [driverEditingId, setDriverEditingId] = useState(null);
  const [driverSaving, setDriverSaving] = useState(false);

  const [tripModal, setTripModal] = useState(false);
  const [tripForm, setTripForm] = useState(emptyTrip);
  const [tripSaving, setTripSaving] = useState(false);

  const [operatorModal, setOperatorModal] = useState(false);
  const [operatorForm, setOperatorForm] = useState(emptyOperator);
  const [operatorSaving, setOperatorSaving] = useState(false);

  useEffect(() => {
    const timer = window.setInterval(
      () => setCurrentTime(Date.now()),
      30000
    );

    return () => window.clearInterval(timer);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');

    const results = await Promise.allSettled([
      apiRequest('/companies/'),
      apiRequest('/companies/routes/'),
      apiRequest('/drivers/'),
      apiRequest('/companies/trips/'),
      apiRequest('/bookings/all/'),
      apiRequest('/users/'),
      apiRequest('/users/company-staff/'),
    ]);

    const [
      companiesResult,
      routesResult,
      driversResult,
      tripsResult,
      bookingsResult,
      usersResult,
      operatorsResult,
    ] = results;

    const errors = [];

    if (companiesResult.status === 'fulfilled') {
      setCompanies(list(companiesResult.value));
    } else {
      errors.push(`Companies: ${companiesResult.reason?.message || 'failed'}`);
    }

    if (routesResult.status === 'fulfilled') {
      setRoutes(list(routesResult.value));
    } else {
      errors.push(`Routes: ${routesResult.reason?.message || 'failed'}`);
    }

    if (driversResult.status === 'fulfilled') {
      setDrivers(list(driversResult.value));
    } else {
      errors.push(`Drivers: ${driversResult.reason?.message || 'failed'}`);
    }

    if (tripsResult.status === 'fulfilled') {
      setTrips(list(tripsResult.value));
    } else {
      errors.push(`Trips: ${tripsResult.reason?.message || 'failed'}`);
    }

    if (bookingsResult.status === 'fulfilled') {
      setBookings(list(bookingsResult.value));
    } else {
      errors.push(`Bookings: ${bookingsResult.reason?.message || 'failed'}`);
    }

    if (usersResult.status === 'fulfilled') {
      setUsers(list(usersResult.value));
    }

    if (operatorsResult.status === 'fulfilled') {
      setOperators(list(operatorsResult.value));
    }

    if (errors.length) {
      setError(errors.join(' • '));
    }

    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (section !== 'trips') return undefined;
    let mounted = true;
    apiRequest('/system/trip-simulations/active/')
      .then((result) => {
        if (mounted) setSim(result?.simulation || null);
      })
      .catch(() => {});
    return () => {
      mounted = false;
    };
  }, [section]);

  const simId = sim?.id;
  const simRunning = sim?.status === 'running';
  useEffect(() => {
    if (!simRunning) return undefined;
    let mounted = true;
    let inFlight = false;
    const timer = window.setInterval(async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const result = await apiRequest(
          `/system/trip-simulations/${simId}/advance/`,
          { method: 'POST', body: {} },
        );
        if (!mounted) return;
        setSim(result.simulation);
        if (result.simulation.status !== 'running') load();
      } catch (err) {
        if (!mounted) return;
        setSimError(err.message || 'The simulation stopped.');
        setSim(null);
      } finally {
        inFlight = false;
      }
    }, 2000);
    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, [simId, simRunning, load]);

  const startSimulation = async (trip) => {
    if (simBusy) return;
    setSimBusy(true);
    setSimError('');
    try {
      const result = await apiRequest(`/system/trips/${trip.id}/simulate/`, {
        method: 'POST',
        body: {},
      });
      setSim(result.simulation);
    } catch (err) {
      setSimError(err.message || 'Unable to start the simulation.');
    } finally {
      setSimBusy(false);
    }
  };

  const runJourneyStep = async (fallbackError, step) => {
    if (simBusy) return;
    setSimBusy(true);
    setSimError('');
    try {
      await step();
    } catch (err) {
      setSimError(err.message || fallbackError);
    } finally {
      setSimBusy(false);
    }
  };

  const divertSimulation = () =>
    runJourneyStep('Unable to divert the bus.', async () => {
      const result = await apiRequest(`/system/trip-simulations/${sim.id}/divert/`, {
        method: 'POST',
        body: {},
      });
      setSim(result.simulation);
      setCommandMessage('Bus diverted. The passenger map shows a new road in about 15 seconds.');
    });

  const boardPassenger = (booking) => {
    const pin = window.prompt(`Boarding PIN for ${booking.booking_number}`);
    if (!pin) return undefined;
    return runJourneyStep('Unable to board this passenger.', async () => {
      await apiRequest(`/bookings/${booking.booking_id}/verify-boarding/`, {
        method: 'POST',
        body: { boarding_pin: pin.trim() },
      });
      setCommandMessage(`${booking.booking_number} is on board.`);
      await load();
    });
  };

  const endSimulatedTrip = (trip) => {
    const warning =
      'End this trip? This is real: anyone who has not boarded becomes a ' +
      'no-show and gets the 50% refund.';
    if (!window.confirm(warning)) return undefined;
    return runJourneyStep('Unable to end this trip.', async () => {
      await apiRequest(`/system/trips/${trip.id}/finish/`, {
        method: 'POST',
        body: {},
      });
      setSim(null);
      setCommandMessage(`Trip ${trip.id} ended.`);
      await load();
    });
  };

  const stopSimulation = async () => {
    if (!sim || simBusy) return;
    setSimBusy(true);
    setSimError('');
    try {
      await apiRequest(`/system/trip-simulations/${sim.id}/stop/`, {
        method: 'POST',
        body: {},
      });
      setSim(null);
    } catch (err) {
      setSimError(err.message || 'Unable to stop the simulation.');
    } finally {
      setSimBusy(false);
    }
  };

  const runSystemTests = useCallback(async () => {
    setSystemTestLoading(true);
    setCommandMessage('');

    try {
      const result = await apiRequest('/system/diagnostics/');
      setSystemChecks(result);

      if (result.status === 'critical') {
        setCommandMessage(
          `${result.failed} critical system check${
            result.failed === 1 ? '' : 's'
          } failed.`
        );
      } else if (result.status === 'warning') {
        setCommandMessage(
          `${result.warnings} system warning${
            result.warnings === 1 ? '' : 's'
          } detected.`
        );
      } else {
        setCommandMessage('All platform system checks passed.');
      }
    } catch (err) {
      setCommandMessage(
        err.message || 'Unable to run system diagnostics.'
      );
    } finally {
      setSystemTestLoading(false);
    }
  }, []);

  const platformAlerts = useMemo(() => {
    const alerts = [];

    const scheduledPastTrips = trips.filter((trip) => {
      const departure = new Date(trip.departure_at).getTime();

      return (
        String(trip.status).toLowerCase() === 'scheduled' &&
        Number.isFinite(departure) &&
        departure < currentTime
      );
    });

    scheduledPastTrips.forEach((trip) => {
      alerts.push({
        id: `past-trip-${trip.id}`,
        severity: 'critical',
        title: 'Trip still scheduled after departure',
        message: `${
          trip.route_details?.name ||
          trip.route_name ||
          `Trip ${trip.id}`
        } was scheduled for ${formatDate(trip.departure_at)} but remains scheduled.`,
        section: 'trips',
      });
    });

    const upcomingUnassignedTrips = trips.filter((trip) => {
      const departure = new Date(trip.departure_at).getTime();

      return (
        departure > currentTime &&
        !['completed', 'cancelled', 'departed'].includes(
          String(trip.status || '').toLowerCase()
        ) &&
        !trip.driver &&
        !trip.driver_name
      );
    });

    upcomingUnassignedTrips.forEach((trip) => {
      alerts.push({
        id: `unassigned-trip-${trip.id}`,
        severity: 'warning',
        title: 'Upcoming trip has no driver',
        message: `${
          trip.route_details?.name ||
          trip.route_name ||
          `Trip ${trip.id}`
        } departs ${formatDate(trip.departure_at)} without a driver.`,
        section: 'trips',
      });
    });

    const unassignedBookings = bookings.filter(
      (booking) =>
        !booking.driver &&
        !booking.driver_name &&
        !['completed', 'cancelled'].includes(
          String(booking.status || '').toLowerCase()
        )
    );

    if (unassignedBookings.length) {
      alerts.push({
        id: 'unassigned-bookings',
        severity: 'warning',
        title: 'Bookings need driver assignment',
        message: `${unassignedBookings.length} active booking${
          unassignedBookings.length === 1 ? '' : 's'
        } have no assigned driver.`,
        section: 'bookings',
      });
    }

    const usage = bookings.reduce((result, booking) => {
      const status = String(
        booking.status || ''
      ).toLowerCase();

      if (['cancelled', 'completed', 'no_show'].includes(status)) {
        return result;
      }

      const tripId =
        booking.trip_id ??
        booking.trip;

      if (!tripId) {
        return result;
      }

      const seats = Number(booking.seats || 0);

      if (seats > 0) {
        result[tripId] =
          (result[tripId] || 0) + seats;
      }

      return result;
    }, {});

    trips.forEach((trip) => {
      const capacity = Number(trip.capacity || 0);
      const bookedSeats = Number(
        usage[trip.id] || 0
      );

      if (
        capacity > 0 &&
        bookedSeats > capacity
      ) {
        alerts.push({
          id: `over-capacity-${trip.id}`,
          severity: 'critical',
          title: 'Trip is over capacity',
          message: `Trip ${trip.id} has ${bookedSeats} booked seats but only ${capacity} seats are available.`,
          section: 'trips',
        });
      }
    });

    trips.forEach((trip) => {
      if (!trip.driver) {
        return;
      }

      const driver = drivers.find(
        (item) =>
          String(item.id) ===
          String(trip.driver)
      );

      if (!driver) {
        return;
      }

      const tripCompany =
        trip.company ||
        trip.company_id ||
        trip.route_details?.company ||
        trip.route_details?.company_id;

      if (
        tripCompany &&
        driver.company &&
        String(driver.company) !==
          String(tripCompany)
      ) {
        alerts.push({
          id: `driver-company-${trip.id}`,
          severity: 'critical',
          title: 'Driver/company mismatch detected',
          message: `Trip ${trip.id} appears to have a driver from another company.`,
          section: 'trips',
        });
      }
    });

    return alerts;
  }, [trips, bookings, drivers, currentTime]);

  const criticalAlerts = platformAlerts.filter(
    (alert) => alert.severity === 'critical'
  );

  const warningAlerts = platformAlerts.filter(
    (alert) => alert.severity === 'warning'
  );

  const systemStatus =
    criticalAlerts.length > 0
      ? 'critical'
      : warningAlerts.length > 0
        ? 'warning'
        : 'healthy';

  const revenue = bookings.reduce(
    (total, booking) =>
      total +
      Number(
        booking.total_amount ||
          booking.amount ||
          0
      ),
    0
  );

  const activeBookings = bookings.filter(
    (booking) =>
      !['completed', 'cancelled'].includes(
        String(booking.status || '').toLowerCase()
      )
  );

  const pageTitles = {
    overview: 'Global overview',
    companies: 'Companies',
    routes: 'Routes',
    trips: 'Trips',
    drivers: 'Drivers',
    operators: 'Operators',
    bookings: 'Bookings',
    users: 'Users',
    reports: 'Reports',
    revenue: 'Revenue',
    issues: 'System issues',
    'system-tests': 'System tests',
    settings: 'Platform settings',
  };
  const pageTitle = pageTitles[section] || 'Global overview';

  const refresh = async () => {
    await load();
    setCommandMessage('Platform data refreshed.');
  };

  const openCreateCompany = () => {
    setCompanyEditingId(null);
    setCompanyForm(emptyCompany);
    setCompanyModal(true);
  };

  const openEditCompany = (company) => {
    setCompanyEditingId(company.id);
    setCompanyForm({
      name: company.name || '',
      description: company.description || '',
      areas_served: company.areas_served || '',
      phone_number: company.phone_number || '',
    });
    setCompanyModal(true);
  };

  const saveCompany = async (event) => {
    event.preventDefault();
    setCompanySaving(true);
    setError('');

    try {
      const payload = {
        name: companyForm.name.trim(),
        description: companyForm.description,
        areas_served: companyForm.areas_served,
        phone_number: companyForm.phone_number,
      };

      if (companyEditingId) {
        await apiRequest(
          `/companies/${companyEditingId}/`,
          {
            method: 'PATCH',
            body: JSON.stringify(payload),
          }
        );
      } else {
        await apiRequest(
          '/companies/create/',
          {
            method: 'POST',
            body: JSON.stringify(payload),
          }
        );
      }

      setCompanyModal(false);
      setCommandMessage(
        companyEditingId
          ? 'Company updated successfully.'
          : 'Company created successfully.'
      );

      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setCompanySaving(false);
    }
  };

  const openCreateRoute = () => {
    setRouteEditingId(null);
    setRouteForm(emptyRoute);
    setRouteModal(true);
  };

  const openEditRoute = (route) => {
    setRouteEditingId(route.id);
    setRouteForm({
      name: route.name || '',
      start_point: route.start_point || '',
      end_point: route.end_point || '',
      price: route.price || '',
      company_id:
        route.company ||
        route.company_id ||
        '',
    });
    setRouteModal(true);
  };

  const saveRoute = async (event) => {
    event.preventDefault();
    setRouteSaving(true);
    setError('');

    try {
      const payload = {
        name: routeForm.name,
        start_point: routeForm.start_point,
        end_point: routeForm.end_point,
        price: routeForm.price,
        company_id: routeForm.company_id,
        company: routeForm.company_id,
      };

      if (routeEditingId) {
        await apiRequest(
          `/companies/routes/${routeEditingId}/`,
          {
            method: 'PATCH',
            body: JSON.stringify(payload),
          }
        );
      } else {
        await apiRequest(
          '/companies/routes/create/',
          {
            method: 'POST',
            body: JSON.stringify(payload),
          }
        );
      }

      setRouteModal(false);
      setCommandMessage(
        routeEditingId
          ? 'Route updated successfully.'
          : 'Route created successfully.'
      );

      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setRouteSaving(false);
    }
  };

  const deleteRoute = async (route) => {
    if (
      !window.confirm(
        `Delete route "${route.name}"?`
      )
    ) {
      return;
    }

    try {
      await apiRequest(
        `/companies/routes/${route.id}/`,
        {
          method: 'DELETE',
        }
      );

      setCommandMessage('Route deleted.');
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  const openCreateDriver = () => {
    setDriverEditingId(null);
    setDriverForm(emptyDriver);
    setDriverModal(true);
  };

  const openEditDriver = (driver) => {
    setDriverEditingId(driver.id);
    setDriverForm({
      name: driver.name || '',
      phone_number: driver.phone_number || '',
      bus_number: driver.bus_number || '',
      company:
        driver.company ||
        driver.company_id ||
        '',
    });
    setDriverModal(true);
  };

  const saveDriver = async (event) => {
    event.preventDefault();
    setDriverSaving(true);
    setError('');

    try {
      const payload = {
        name: driverForm.name,
        phone_number: driverForm.phone_number,
        bus_number: driverForm.bus_number,
        company: driverForm.company,
      };

      if (driverEditingId) {
        await apiRequest(
          `/drivers/${driverEditingId}/`,
          {
            method: 'PATCH',
            body: JSON.stringify(payload),
          }
        );
      } else {
        await apiRequest(
          '/drivers/',
          {
            method: 'POST',
            body: JSON.stringify(payload),
          }
        );
      }

      setDriverModal(false);
      setCommandMessage(
        driverEditingId
          ? 'Driver updated successfully.'
          : 'Driver created successfully.'
      );

      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setDriverSaving(false);
    }
  };

  const deleteDriver = async (driver) => {
    if (
      !window.confirm(
        `Delete driver "${driver.name}"?`
      )
    ) {
      return;
    }

    try {
      await apiRequest(
        `/drivers/${driver.id}/`,
        {
          method: 'DELETE',
        }
      );

      setCommandMessage('Driver deleted.');
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  const openCreateTrip = () => {
    setTripForm(emptyTrip);
    setTripModal(true);
  };

  const createTrip = async (event) => {
    event.preventDefault();
    setTripSaving(true);
    setError('');

    try {
      const payload = {
        route_id: tripForm.route_id,
        route: tripForm.route_id,
        driver_id: tripForm.driver_id,
        driver: tripForm.driver_id,
        departure_at: tripForm.departure_at,
        capacity: Number(tripForm.capacity),
        company_id: tripForm.company_id,
      };

      await apiRequest(
        '/companies/trips/create/',
        {
          method: 'POST',
          body: JSON.stringify(payload),
        }
      );

      setTripModal(false);
      setCommandMessage('Trip created successfully.');
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setTripSaving(false);
    }
  };

  const updateTripStatus = async (trip, status) => {
    try {
      await apiRequest(
        `/companies/trips/${trip.id}/status/`,
        {
          method: 'POST',
          body: JSON.stringify({ status }),
        }
      );

      setCommandMessage(
        `Trip ${trip.id} changed to ${status}.`
      );

      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  const openCreateOperator = () => {
    setOperatorForm(emptyOperator);
    setOperatorModal(true);
  };

  const saveOperator = async (event) => {
    event.preventDefault();
    setOperatorSaving(true);
    setError('');

    try {
      const payload = {
        username: operatorForm.username,
        email: operatorForm.email,
        phone_number: operatorForm.phone_number,
        location: operatorForm.location,
        role: operatorForm.role,
        company: operatorForm.company,
        password: operatorForm.password,
      };

      await apiRequest(
        '/users/company-staff/',
        {
          method: 'POST',
          body: JSON.stringify(payload),
        }
      );

      setOperatorModal(false);
      setCommandMessage(
        'Company staff account created successfully.'
      );

      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setOperatorSaving(false);
    }
  };

  const companyName = (id) =>
    companies.find(
      (company) =>
        String(company.id) === String(id)
    )?.name || '—';

  const routeName = (id) =>
    routes.find(
      (route) =>
        String(route.id) === String(id)
    )?.name || `Route ${id || '—'}`;

  if (!pageTitles[section]) return <Navigate to="/platform-admin" replace />;

  return (
    <PlatformShell
      user={user}
      logout={logout}
    >
      <header className="pa-topbar">
        <h1 className="pa-topbar-title">{pageTitle}</h1>

        <div className="pa-page-actions">
          <button
            type="button"
            className="pa-system-status"
            onClick={() =>
              navigate('/platform-admin/issues')
            }
          >
            <span className="pa-status-dot" />

            <span>
              {systemStatus === 'critical'
                ? `${criticalAlerts.length} critical issue${
                    criticalAlerts.length === 1
                      ? ''
                      : 's'
                  }`
                : systemStatus === 'warning'
                  ? `${warningAlerts.length} warning${
                      warningAlerts.length === 1
                        ? ''
                        : 's'
                    }`
                  : 'System healthy'}
            </span>

            <ChevronRight size={15} />
          </button>

          <div className="pa-user">
            <div className="pa-avatar">
              {(user?.username || 'A')
                .slice(0, 1)
                .toUpperCase()}
            </div>

            <div>
              <strong>
                {user?.username || 'Administrator'}
              </strong>
              <span>Platform Admin</span>
            </div>
          </div>
        </div>
      </header>

      <main className="pa-content">
        {error && (
          <div className="pa-error">
            {error}
          </div>
        )}

        {commandMessage && (
          <div className="pa-command-message">
            {commandMessage}
          </div>
        )}

        <div className="pa-page-head">
          <button
            type="button"
            className="pa-secondary-button"
            onClick={refresh}
            disabled={loading}
          >
            <RefreshCw
              size={15}
              className={
                loading ? 'pa-spin' : ''
              }
            />
            Refresh
          </button>
        </div>

        {section === 'overview' && (
          <>
            <div className="pa-command-grid">
              <div className="pa-command-card">
                <div className="pa-command-card-head">
                  <div>
                    <span className="pa-card-eyebrow">
                      System health
                    </span>

                    <h3>
                      {systemStatus === 'healthy'
                        ? 'System healthy'
                        : systemStatus === 'critical'
                          ? 'Critical attention required'
                          : 'Attention required'}
                    </h3>
                  </div>

                  <div
                    className={`pa-command-icon ${systemStatus}`}
                  >
                    {systemStatus === 'healthy' ? (
                      <CheckCircle2 size={20} />
                    ) : (
                      <AlertTriangle size={20} />
                    )}
                  </div>
                </div>

                <p>
                  {criticalAlerts.length > 0
                    ? `${criticalAlerts.length} critical issue${
                        criticalAlerts.length === 1
                          ? ''
                          : 's'
                      } require attention.`
                    : warningAlerts.length > 0
                      ? `${warningAlerts.length} warning${
                          warningAlerts.length === 1
                            ? ''
                            : 's'
                        } detected.`
                      : 'No active operational issues detected.'}
                </p>

                <button
                  type="button"
                  className="pa-secondary-button"
                  onClick={() =>
                    navigate(
                      '/platform-admin/issues'
                    )
                  }
                >
                  Open issue workspace
                  <ChevronRight size={15} />
                </button>
              </div>

              <div className="pa-command-card">
                <div className="pa-command-card-head">
                  <div>
                    <span className="pa-card-eyebrow">
                      Diagnostics
                    </span>

                    <h3>
                      Platform system tests
                    </h3>
                  </div>

                  <div className="pa-command-icon">
                    <Database size={20} />
                  </div>
                </div>

                <p>
                  Check database connectivity and
                  platform data integrity directly
                  through the Django backend.
                </p>

                <button
                  type="button"
                  className="pa-primary-button"
                  onClick={runSystemTests}
                  disabled={systemTestLoading}
                >
                  <RefreshCw
                    size={15}
                    className={
                      systemTestLoading
                        ? 'pa-spin'
                        : ''
                    }
                  />

                  {systemTestLoading
                    ? 'Running tests...'
                    : 'Run System Tests'}
                </button>
              </div>
            </div>

            <div className="pa-stat-grid">
              <div className="pa-stat-card">
                <span>Companies</span>
                <strong>
                  {companies.length}
                </strong>
              </div>

              <div className="pa-stat-card">
                <span>Routes</span>
                <strong>
                  {routes.length}
                </strong>
              </div>

              <div className="pa-stat-card">
                <span>Trips</span>
                <strong>
                  {trips.length}
                </strong>
              </div>

              <div className="pa-stat-card">
                <span>Drivers</span>
                <strong>
                  {drivers.length}
                </strong>
              </div>

              <div className="pa-stat-card">
                <span>Bookings</span>
                <strong>
                  {bookings.length}
                </strong>
              </div>

              <div className="pa-stat-card">
                <span>Active bookings</span>
                <strong>
                  {activeBookings.length}
                </strong>
              </div>

              <div className="pa-stat-card">
                <span>Booking value</span>
                <strong>
                  {money(revenue)}
                </strong>
              </div>

              <div className="pa-stat-card">
                <span>Platform alerts</span>
                <strong>
                  {platformAlerts.length}
                </strong>
              </div>
            </div>

            <div className="pa-two-col">
              <div className="pa-panel">
                <div className="pa-panel-header">
                  <div>
                    <h3>Companies</h3>
                    <p>
                      Global company directory.
                    </p>
                  </div>

                  <button
                    type="button"
                    className="pa-secondary-button"
                    onClick={() =>
                      navigate(
                        '/platform-admin/companies'
                      )
                    }
                  >
                    View all
                  </button>
                </div>

                <div className="pa-list">
                  {companies.slice(0, 6).map(
                    (company) => (
                      <div
                        className="pa-list-row"
                        key={company.id}
                      >
                        <div>
                          <strong>
                            {company.name}
                          </strong>

                          <span>
                            {company.areas_served ||
                              'Transport operator'}
                          </span>
                        </div>

                        <span>
                          {
                            routes.filter(
                              (route) =>
                                String(
                                  route.company
                                ) ===
                                String(
                                  company.id
                                )
                            ).length
                          } routes
                        </span>
                      </div>
                    )
                  )}

                  {!companies.length && (
                    <div className="pa-empty-state">
                      No companies found.
                    </div>
                  )}
                </div>
              </div>

              <div className="pa-panel">
                <div className="pa-panel-header">
                  <div>
                    <h3>Latest trips</h3>
                    <p>
                      Most recent operational trips.
                    </p>
                  </div>

                  <button
                    type="button"
                    className="pa-secondary-button"
                    onClick={() =>
                      navigate(
                        '/platform-admin/trips'
                      )
                    }
                  >
                    View all
                  </button>
                </div>

                <div className="pa-list">
                  {trips
                    .slice()
                    .sort(
                      (a, b) =>
                        new Date(
                          b.departure_at
                        ) -
                        new Date(
                          a.departure_at
                        )
                    )
                    .slice(0, 6)
                    .map((trip) => (
                      <div
                        className="pa-list-row"
                        key={trip.id}
                      >
                        <div>
                          <strong>
                            {trip.route_details
                              ?.name ||
                              trip.route_name ||
                              `Trip ${trip.id}`}
                          </strong>

                          <span>
                            {formatDate(
                              trip.departure_at
                            )}
                          </span>
                        </div>

                        <span className="pa-badge">
                          {trip.status ||
                            'scheduled'}
                        </span>
                      </div>
                    ))}

                  {!trips.length && (
                    <div className="pa-empty-state">
                      No trips found.
                    </div>
                  )}
                </div>
              </div>
            </div>

            {platformAlerts.length > 0 && (
              <div className="pa-panel">
                <div className="pa-panel-header">
                  <div>
                    <h3>
                      Operational attention
                    </h3>

                    <p>
                      Issues detected from current
                      platform data.
                    </p>
                  </div>

                  <button
                    type="button"
                    className="pa-secondary-button"
                    onClick={() =>
                      navigate(
                        '/platform-admin/issues'
                      )
                    }
                  >
                    Open workspace
                  </button>
                </div>

                <div className="pa-issue-list">
                  {platformAlerts
                    .slice(0, 5)
                    .map((alert) => (
                      <button
                        type="button"
                        className={`pa-issue-row ${alert.severity}`}
                        key={alert.id}
                        onClick={() =>
                          navigate(
                            `/platform-admin/${alert.section}`
                          )
                        }
                      >
                        <div className="pa-issue-icon">
                          {alert.severity ===
                          'critical' ? (
                            <AlertTriangle
                              size={18}
                            />
                          ) : (
                            <Bell size={18} />
                          )}
                        </div>

                        <div className="pa-issue-content">
                          <strong>
                            {alert.title}
                          </strong>

                          <span>
                            {alert.message}
                          </span>
                        </div>

                        <ChevronRight
                          size={16}
                        />
                      </button>
                    ))}
                </div>
              </div>
            )}
          </>
        )}

        {section === 'companies' && (
          <section>
            <div className="pa-section-heading">
              <div>
                <span className="pa-card-eyebrow">
                  Global directory
                </span>

                <h3>
                  Transport companies
                </h3>

                <p>
                  Create and manage companies
                  across the CONNECT platform.
                </p>
              </div>

              <button
                type="button"
                className="pa-primary-button"
                onClick={openCreateCompany}
              >
                <Plus size={16} />
                Add Company
              </button>
            </div>

            <div className="pa-panel">
              <div className="pa-table-wrap">
                <table className="pa-table">
                  <thead>
                    <tr>
                      <th>Company</th>
                      <th>Areas served</th>
                      <th>Routes</th>
                      <th>Trips</th>
                      <th>Actions</th>
                    </tr>
                  </thead>

                  <tbody>
                    {companies.map(
                      (company) => (
                        <tr key={company.id}>
                          <td>
                            <strong>
                              {company.name}
                            </strong>

                            <br />

                            <span>
                              {company.phone_number ||
                                'No phone'}
                            </span>
                          </td>

                          <td>
                            {company.areas_served ||
                              '—'}
                          </td>

                          <td>
                            {
                              routes.filter(
                                (route) =>
                                  String(
                                    route.company
                                  ) ===
                                  String(
                                    company.id
                                  )
                              ).length
                            }
                          </td>

                          <td>
                            {
                              trips.filter(
                                (trip) =>
                                  String(
                                    trip.company ||
                                      trip.company_id ||
                                      trip.route_details
                                        ?.company
                                  ) ===
                                  String(
                                    company.id
                                  )
                              ).length
                            }
                          </td>

                          <td>
                            <div className="pa-actions">
                              <button
                                type="button"
                                className="pa-icon-button"
                                onClick={() =>
                                  openEditCompany(
                                    company
                                  )
                                }
                                title="Edit company"
                              >
                                <Settings
                                  size={14}
                                />
                              </button>
                            </div>
                          </td>
                        </tr>
                      )
                    )}
                  </tbody>
                </table>
              </div>

              {!companies.length && (
                <div className="pa-empty-state">
                  <Building2 size={28} />
                  <strong>
                    No companies found
                  </strong>
                </div>
              )}
            </div>
          </section>
        )}

        {section === 'routes' && (
          <section>
            <div className="pa-section-heading">
              <div>
                <span className="pa-card-eyebrow">
                  Network
                </span>

                <h3>Routes</h3>

                <p>
                  Global route configuration.
                </p>
              </div>

              <button
                type="button"
                className="pa-primary-button"
                onClick={openCreateRoute}
              >
                <Plus size={16} />
                Add Route
              </button>
            </div>

            <div className="pa-panel">
              <div className="pa-table-wrap">
                <table className="pa-table">
                  <thead>
                    <tr>
                      <th>Route</th>
                      <th>Company</th>
                      <th>Start</th>
                      <th>End</th>
                      <th>Price</th>
                      <th>Actions</th>
                    </tr>
                  </thead>

                  <tbody>
                    {routes.map(
                      (route) => (
                        <tr key={route.id}>
                          <td>
                            <strong>
                              {route.name}
                            </strong>
                          </td>

                          <td>
                            {route.company_name ||
                              companyName(
                                route.company
                              )}
                          </td>

                          <td>
                            {route.start_point}
                          </td>

                          <td>
                            {route.end_point}
                          </td>

                          <td>
                            {money(route.price)}
                          </td>

                          <td>
                            <div className="pa-actions">
                              <button
                                type="button"
                                className="pa-icon-button"
                                onClick={() =>
                                  openEditRoute(
                                    route
                                  )
                                }
                              >
                                <Settings
                                  size={14}
                                />
                              </button>

                              <button
                                type="button"
                                className="pa-icon-button danger"
                                onClick={() =>
                                  deleteRoute(
                                    route
                                  )
                                }
                              >
                                <Trash2
                                  size={14}
                                />
                              </button>
                            </div>
                          </td>
                        </tr>
                      )
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        )}

        {section === 'drivers' && (
          <section>
            <div className="pa-section-heading">
              <div>
                <span className="pa-card-eyebrow">
                  Fleet
                </span>

                <h3>Drivers</h3>

                <p>
                  Global driver directory.
                </p>
              </div>

              <button
                type="button"
                className="pa-primary-button"
                onClick={openCreateDriver}
              >
                <Plus size={16} />
                Add Driver
              </button>
            </div>

            <div className="pa-panel">
              <div className="pa-table-wrap">
                <table className="pa-table">
                  <thead>
                    <tr>
                      <th>Driver</th>
                      <th>Phone</th>
                      <th>Bus</th>
                      <th>Company</th>
                      <th>Actions</th>
                    </tr>
                  </thead>

                  <tbody>
                    {drivers.map(
                      (driver) => (
                        <tr key={driver.id}>
                          <td>
                            <strong>
                              {driver.name}
                            </strong>
                          </td>

                          <td>
                            {driver.phone_number ||
                              '—'}
                          </td>

                          <td>
                            {driver.bus_number ||
                              '—'}
                          </td>

                          <td>
                            {companyName(
                              driver.company ||
                                driver.company_id
                            )}
                          </td>

                          <td>
                            <div className="pa-actions">
                              <button
                                type="button"
                                className="pa-icon-button"
                                onClick={() =>
                                  openEditDriver(
                                    driver
                                  )
                                }
                              >
                                <Settings
                                  size={14}
                                />
                              </button>

                              <button
                                type="button"
                                className="pa-icon-button danger"
                                onClick={() =>
                                  deleteDriver(
                                    driver
                                  )
                                }
                              >
                                <Trash2
                                  size={14}
                                />
                              </button>
                            </div>
                          </td>
                        </tr>
                      )
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        )}

        {section === 'trips' && (
          <section>
            <div className="pa-section-heading">
              <div>
                <span className="pa-card-eyebrow">
                  Operations
                </span>

                <h3>Trips</h3>

                <p>
                  Global trip schedule and
                  operational status.
                </p>
              </div>

              <button
                type="button"
                className="pa-primary-button"
                onClick={openCreateTrip}
              >
                <Plus size={16} />
                Create Trip
              </button>
            </div>

            <div className="pa-panel">
              <div className="pa-table-wrap">
                <table className="pa-table">
                  <thead>
                    <tr>
                      <th>Route</th>
                      <th>Company</th>
                      <th>Driver</th>
                      <th>Departure</th>
                      <th>Capacity</th>
                      <th>Status</th>
                      <th>Action</th>
                    </tr>
                  </thead>

                  <tbody>
                    {trips
                      .slice()
                      .sort(
                        (a, b) =>
                          new Date(
                            b.departure_at
                          ) -
                          new Date(
                            a.departure_at
                          )
                      )
                      .map((trip) => (
                        <tr key={trip.id}>
                          <td>
                            <strong>
                              {trip.route_details
                                ?.name ||
                                routeName(
                                  trip.route
                                )}
                            </strong>
                          </td>

                          <td>
                            {trip.company_name ||
                              companyName(
                                trip.route_details
                                  ?.company
                              )}
                          </td>

                          <td>
                            {trip.driver_name ||
                              trip.driver ||
                              'Unassigned'}
                          </td>

                          <td>
                            {formatDate(
                              trip.departure_at
                            )}
                          </td>

                          <td>
                            {trip.capacity}
                          </td>

                          <td>
                            <span
                              className={`pa-badge ${
                                String(
                                  trip.status
                                ).toLowerCase() ===
                                'cancelled'
                                  ? 'danger'
                                  : String(
                                        trip.status
                                      ).toLowerCase() ===
                                      'scheduled'
                                    ? ''
                                    : 'warning'
                              }`}
                            >
                              {trip.status}
                            </span>
                          </td>

                          <td>
                            <select
                              aria-label={`Status for trip ${trip.id}`}
                              value={
                                trip.status || ''
                              }
                              onChange={(event) =>
                                updateTripStatus(
                                  trip,
                                  event.target.value
                                )
                              }
                              style={{
                                background:
                                  '#0b1726',
                                color: '#e5edf5',
                                border:
                                  '1px solid rgba(255,255,255,.08)',
                                borderRadius: 8,
                                padding: '7px',
                                fontSize: 11,
                              }}
                            >
                              <option value="scheduled">
                                Scheduled
                              </option>
                              <option value="boarding">
                                Boarding
                              </option>
                              <option value="departed">
                                Departed
                              </option>
                              <option value="completed">
                                Completed
                              </option>
                              <option value="cancelled">
                                Cancelled
                              </option>
                            </select>
                            {user?.is_superuser && (
                              <div style={{ marginTop: 8 }}>
                                <TripSimulateControl
                                  trip={trip}
                                  sim={sim}
                                  busy={simBusy}
                                  onStart={startSimulation}
                                  onStop={stopSimulation}
                                />
                                <TripJourneyControls
                                  trip={trip}
                                  sim={sim}
                                  bookings={bookings}
                                  busy={simBusy}
                                  onDivert={divertSimulation}
                                  onBoard={boardPassenger}
                                  onEnd={endSimulatedTrip}
                                />
                              </div>
                            )}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </div>

            {simError && (
              <p role="alert" className="pa-error">{simError}</p>
            )}
            <p style={{ color: 'var(--text-2)', fontSize: 12, maxWidth: '72ch' }}>
              Simulate moves this trip's bus along its route as if the driver were
              driving. Passengers booked on it see it live. Keep this tab open;
              closing it stops the bus. Divert bus sends it off the route to test
              rerouting, Board enters a passenger's PIN, and End trip finishes the
              journey. These change the real trip and booking.
            </p>
          </section>
        )}

        {section === 'operators' && (
          <section>
            <div className="pa-section-heading">
              <div>
                <span className="pa-card-eyebrow">
                  Company access
                </span>

                <h3>Operators</h3>

                <p>
                  Manage company managers,
                  auditors and operators.
                </p>
              </div>

              <button
                type="button"
                className="pa-primary-button"
                onClick={openCreateOperator}
              >
                <Plus size={16} />
                Add Company Staff
              </button>
            </div>

            <div className="pa-panel">
              <div className="pa-table-wrap">
                <table className="pa-table">
                  <thead>
                    <tr>
                      <th>User</th>
                      <th>Role</th>
                      <th>Company</th>
                      <th>Email</th>
                      <th>Phone</th>
                    </tr>
                  </thead>

                  <tbody>
                    {operators.map(
                      (operator) => (
                        <tr key={operator.id}>
                          <td>
                            <strong>
                              {operator.username}
                            </strong>
                          </td>

                          <td>
                            <span className="pa-badge">
                              {operator.role}
                            </span>
                          </td>

                          <td>
                            {operator.company_name ||
                              companyName(
                                operator.company
                              )}
                          </td>

                          <td>
                            {operator.email ||
                              '—'}
                          </td>

                          <td>
                            {operator.phone_number ||
                              '—'}
                          </td>
                        </tr>
                      )
                    )}
                  </tbody>
                </table>
              </div>

              {!operators.length && (
                <div className="pa-empty-state">
                  <Users size={28} />
                  <strong>
                    No company staff found
                  </strong>
                </div>
              )}
            </div>
          </section>
        )}

        {section === 'bookings' && (
          <section>
            <div className="pa-section-heading">
              <div>
                <span className="pa-card-eyebrow">
                  Bookings
                </span>

                <h3>Global bookings</h3>

                <p>
                  Platform-wide booking activity.
                </p>
              </div>
            </div>

            <div className="pa-stat-grid">
              <div className="pa-stat-card">
                <span>Total</span>
                <strong>
                  {bookings.length}
                </strong>
              </div>

              <div className="pa-stat-card">
                <span>Active</span>
                <strong>
                  {activeBookings.length}
                </strong>
              </div>

              <div className="pa-stat-card">
                <span>Completed</span>
                <strong>
                  {
                    bookings.filter(
                      (booking) =>
                        String(
                          booking.status
                        ).toLowerCase() ===
                        'completed'
                    ).length
                  }
                </strong>
              </div>

              <div className="pa-stat-card">
                <span>Booking value</span>
                <strong>
                  {money(revenue)}
                </strong>
              </div>
            </div>

            <div className="pa-panel">
              <div className="pa-table-wrap">
                <table className="pa-table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Passenger</th>
                      <th>Trip</th>
                      <th>Seats</th>
                      <th>Amount</th>
                      <th>Status</th>
                    </tr>
                  </thead>

                  <tbody>
                    {bookings.map(
                      (booking) => (
                        <tr key={booking.id}>
                          <td>
                            #{booking.id}
                          </td>

                          <td>
                            <strong>
                              {booking.passenger_name ||
                                booking.user_name ||
                                booking.user ||
                                'Passenger'}
                            </strong>
                          </td>

                          <td>
                            {booking.trip_id ||
                              booking.trip ||
                              '—'}
                          </td>

                          <td>
                            {booking.seats ||
                              1}
                          </td>

                          <td>
                            {money(
                              booking.total_amount ||
                                booking.amount
                            )}
                          </td>

                          <td>
                            <span className="pa-badge">
                              {booking.status ||
                                'unknown'}
                            </span>
                          </td>
                        </tr>
                      )
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        )}

        {section === 'users' && (
          <section>
            <div className="pa-section-heading">
              <div>
                <span className="pa-card-eyebrow">
                  Platform directory
                </span>

                <h3>Users</h3>

                <p>
                  Global user population across
                  CONNECT.
                </p>
              </div>
            </div>

            <div className="pa-stat-grid">
              <div className="pa-stat-card">
                <span>Total users</span>
                <strong>
                  {users.length}
                </strong>
              </div>

              <div className="pa-stat-card">
                <span>Passengers</span>
                <strong>
                  {
                    users.filter(
                      (item) =>
                        item.role ===
                        'passenger'
                    ).length
                  }
                </strong>
              </div>

              <div className="pa-stat-card">
                <span>Drivers</span>
                <strong>
                  {
                    users.filter(
                      (item) =>
                        item.role ===
                        'driver'
                    ).length
                  }
                </strong>
              </div>

              <div className="pa-stat-card">
                <span>Company staff</span>
                <strong>
                  {
                    users.filter(
                      (item) =>
                        [
                          'company_manager',
                          'company_auditor',
                          'company_operator',
                        ].includes(
                          item.role
                        )
                    ).length
                  }
                </strong>
              </div>
            </div>

            <div className="pa-panel">
              <div className="pa-table-wrap">
                <table className="pa-table">
                  <thead>
                    <tr>
                      <th>User</th>
                      <th>Email</th>
                      <th>Phone</th>
                      <th>Role</th>
                      <th>Company</th>
                      <th>Active</th>
                    </tr>
                  </thead>

                  <tbody>
                    {users.map(
                      (item) => (
                        <tr key={item.id}>
                          <td>
                            <strong>
                              {item.username}
                            </strong>
                          </td>

                          <td>
                            {item.email || '—'}
                          </td>

                          <td>
                            {item.phone_number ||
                              '—'}
                          </td>

                          <td>
                            <span className="pa-badge">
                              {item.role}
                            </span>
                          </td>

                          <td>
                            {item.company_name ||
                              companyName(
                                item.company
                              )}
                          </td>

                          <td>
                            <span
                              className={
                                item.is_active ===
                                false
                                  ? 'pa-badge danger'
                                  : 'pa-badge'
                              }
                            >
                              {item.is_active ===
                              false
                                ? 'Inactive'
                                : 'Active'}
                            </span>
                          </td>
                        </tr>
                      )
                    )}
                  </tbody>
                </table>
              </div>

              {!users.length && (
                <div className="pa-empty-state">
                  <UserRound size={28} />
                  <strong>
                    User directory unavailable
                  </strong>
                  <span>
                    The platform user endpoint did
                    not return a user list.
                  </span>
                </div>
              )}
            </div>
          </section>
        )}

        {section === 'reports' && (
          <section>
            <div className="pa-section-heading">
              <div>
                <span className="pa-card-eyebrow">
                  Platform insights
                </span>

                <h3>
                  Operational reports
                </h3>

                <p>
                  Current platform-wide operational
                  statistics.
                </p>
              </div>
            </div>

            <div className="pa-stat-grid">
              <div className="pa-stat-card">
                <span>Companies</span>
                <strong>
                  {companies.length}
                </strong>
              </div>

              <div className="pa-stat-card">
                <span>Routes</span>
                <strong>
                  {routes.length}
                </strong>
              </div>

              <div className="pa-stat-card">
                <span>Trips</span>
                <strong>
                  {trips.length}
                </strong>
              </div>

              <div className="pa-stat-card">
                <span>Bookings</span>
                <strong>
                  {bookings.length}
                </strong>
              </div>
            </div>

            <div className="pa-panel">
              <div className="pa-panel-header">
                <div>
                  <h3>
                    Company activity
                  </h3>

                  <p>
                    Route and trip distribution
                    across companies.
                  </p>
                </div>
              </div>

              <div className="pa-report-list">
                {companies.map(
                  (company) => {
                    const companyRoutes =
                      routes.filter(
                        (route) =>
                          String(
                            route.company
                          ) ===
                          String(
                            company.id
                          )
                      );

                    const companyTrips =
                      trips.filter(
                        (trip) =>
                          String(
                            trip.company ||
                              trip.company_id ||
                              trip.route_details
                                ?.company
                          ) ===
                          String(
                            company.id
                          )
                      );

                    const companyBookings =
                      bookings.filter(
                        (booking) =>
                          String(
                            booking.company ||
                              booking.company_id
                          ) ===
                          String(
                            company.id
                          )
                      );

                    return (
                      <div
                        className="pa-report-row"
                        key={company.id}
                      >
                        <div>
                          <strong>
                            {company.name}
                          </strong>

                          <span>
                            {
                              companyRoutes.length
                            } routes ·{' '}
                            {
                              companyTrips.length
                            } trips ·{' '}
                            {
                              companyBookings.length
                            } bookings
                          </span>
                        </div>

                        <ChevronRight
                          size={17}
                        />
                      </div>
                    );
                  }
                )}
              </div>
            </div>
          </section>
        )}

        {section === 'revenue' && (
          <section>
            <div className="pa-section-heading">
              <div>
                <span className="pa-card-eyebrow">
                  Financial overview
                </span>

                <h3>Revenue</h3>

                <p>
                  Platform-wide booking value.
                  This is not presented as settled
                  company revenue.
                </p>
              </div>
            </div>

            <div className="pa-stat-grid">
              <div className="pa-stat-card">
                <span>Total booking value</span>
                <strong>
                  {money(revenue)}
                </strong>
              </div>

              <div className="pa-stat-card">
                <span>Total bookings</span>
                <strong>
                  {bookings.length}
                </strong>
              </div>

              <div className="pa-stat-card">
                <span>Active bookings</span>
                <strong>
                  {activeBookings.length}
                </strong>
              </div>

              <div className="pa-stat-card">
                <span>Average booking</span>
                <strong>
                  {money(
                    bookings.length
                      ? revenue /
                          bookings.length
                      : 0
                  )}
                </strong>
              </div>
            </div>

            <div className="pa-panel">
              <div className="pa-panel-header">
                <div>
                  <h3>
                    Booking value by company
                  </h3>

                  <p>
                    Calculated from booking amounts
                    returned by the API.
                  </p>
                </div>
              </div>

              <div className="pa-report-list">
                {companies.map(
                  (company) => {
                    const companyValue =
                      bookings
                        .filter(
                          (booking) =>
                            String(
                              booking.company ||
                                booking.company_id
                            ) ===
                            String(
                              company.id
                            )
                        )
                        .reduce(
                          (sum, booking) =>
                            sum +
                            Number(
                              booking.total_amount ||
                                booking.amount ||
                                0
                            ),
                          0
                        );

                    return (
                      <div
                        className="pa-report-row"
                        key={company.id}
                      >
                        <div>
                          <strong>
                            {company.name}
                          </strong>

                          <span>
                            Platform booking value
                          </span>
                        </div>

                        <strong>
                          {money(
                            companyValue
                          )}
                        </strong>
                      </div>
                    );
                  }
                )}
              </div>
            </div>
          </section>
        )}

        {section === 'issues' && (
          <section>
            <div className="pa-section-heading">
              <div>
                <span className="pa-card-eyebrow">
                  Operations
                </span>

                <h3>
                  Issue workspace
                </h3>

                <p>
                  Live operational exceptions
                  detected from current platform data.
                </p>
              </div>

              <button
                type="button"
                className="pa-primary-button"
                onClick={runSystemTests}
                disabled={systemTestLoading}
              >
                <RefreshCw
                  size={15}
                  className={
                    systemTestLoading
                      ? 'pa-spin'
                      : ''
                  }
                />

                {systemTestLoading
                  ? 'Testing...'
                  : 'Run System Tests'}
              </button>
            </div>

            <div className="pa-issue-summary">
              <div className="pa-issue-summary-card critical">
                <AlertTriangle size={20} />

                <div>
                  <strong>
                    {criticalAlerts.length}
                  </strong>

                  <span>
                    Critical
                  </span>
                </div>
              </div>

              <div className="pa-issue-summary-card warning">
                <Bell size={20} />

                <div>
                  <strong>
                    {warningAlerts.length}
                  </strong>

                  <span>
                    Warnings
                  </span>
                </div>
              </div>

              <div className="pa-issue-summary-card healthy">
                <CheckCircle2 size={20} />

                <div>
                  <strong>
                    {platformAlerts.length
                      ? 'Review'
                      : 'OK'}
                  </strong>

                  <span>
                    Platform status
                  </span>
                </div>
              </div>
            </div>

            <div className="pa-panel">
              <div className="pa-panel-header">
                <div>
                  <h3>
                    Active issues
                  </h3>

                  <p>
                    Click an issue to open its
                    operational workspace.
                  </p>
                </div>
              </div>

              {platformAlerts.length === 0 ? (
                <div className="pa-empty-state">
                  <CheckCircle2
                    size={30}
                  />

                  <strong>
                    No active issues
                  </strong>

                  <span>
                    Current platform data has no
                    detected operational exceptions.
                  </span>
                </div>
              ) : (
                <div className="pa-issue-list">
                  {platformAlerts.map(
                    (alert) => (
                      <button
                        type="button"
                        className={`pa-issue-row ${alert.severity}`}
                        key={alert.id}
                        onClick={() =>
                          navigate(
                            `/platform-admin/${alert.section}`
                          )
                        }
                      >
                        <div className="pa-issue-icon">
                          {alert.severity ===
                          'critical' ? (
                            <AlertTriangle
                              size={19}
                            />
                          ) : (
                            <Bell size={19} />
                          )}
                        </div>

                        <div className="pa-issue-content">
                          <strong>
                            {alert.title}
                          </strong>

                          <span>
                            {alert.message}
                          </span>
                        </div>

                        <ChevronRight
                          size={17}
                        />
                      </button>
                    )
                  )}
                </div>
              )}
            </div>
          </section>
        )}

        {section === 'system-tests' && (
          <section>
            <div className="pa-section-heading">
              <div>
                <span className="pa-card-eyebrow">
                  System
                </span>

                <h3>
                  Platform system tests
                </h3>

                <p>
                  Verify the health and integrity
                  of the CONNECT backend.
                </p>
              </div>

              <button
                type="button"
                className="pa-primary-button"
                onClick={runSystemTests}
                disabled={systemTestLoading}
              >
                <RefreshCw
                  size={15}
                  className={
                    systemTestLoading
                      ? 'pa-spin'
                      : ''
                  }
                />

                {systemTestLoading
                  ? 'Running...'
                  : 'Run System Tests'}
              </button>
            </div>

            {!systemChecks ? (
              <div className="pa-empty-state">
                <Database size={30} />

                <strong>
                  No test run yet
                </strong>

                <span>
                  Run the system tests to inspect
                  the current backend.
                </span>

                <button
                  type="button"
                  className="pa-primary-button"
                  onClick={runSystemTests}
                >
                  Run System Tests
                </button>
              </div>
            ) : (
              <>
                <div className="pa-test-summary">
                  <div>
                    <strong>
                      {systemChecks.passed}
                    </strong>

                    <span>
                      Passed
                    </span>
                  </div>

                  <div>
                    <strong>
                      {systemChecks.warnings}
                    </strong>

                    <span>
                      Warnings
                    </span>
                  </div>

                  <div>
                    <strong>
                      {systemChecks.failed}
                    </strong>

                    <span>
                      Failed
                    </span>
                  </div>

                  <div>
                    <strong>
                      {systemChecks.status}
                    </strong>

                    <span>
                      Overall status
                    </span>
                  </div>
                </div>

                <div className="pa-panel">
                  <div className="pa-panel-header">
                    <div>
                      <h3>
                        Diagnostic results
                      </h3>

                      <p>
                        Results returned directly
                        from Django.
                      </p>
                    </div>
                  </div>

                  <div>
                    {systemChecks.checks.map(
                      (check) => (
                        <div
                          className={`pa-test-row ${check.status}`}
                          key={check.name}
                        >
                          <div className="pa-test-icon">
                            {check.status ===
                            'passed' ? (
                              <CheckCircle2
                                size={18}
                              />
                            ) : (
                              <AlertTriangle
                                size={18}
                              />
                            )}
                          </div>

                          <div>
                            <strong>
                              {check.name}
                            </strong>

                            <span>
                              {check.message}
                            </span>
                          </div>

                          <span className="pa-test-status">
                            {check.status}
                          </span>
                        </div>
                      )
                    )}
                  </div>
                </div>
              </>
            )}
          </section>
        )}

        {section === 'settings' && (
          <section>
            <div className="pa-section-heading">
              <div>
                <span className="pa-card-eyebrow">
                  System configuration
                </span>

                <h3>
                  Platform settings
                </h3>

                <p>
                  Platform-level configuration and
                  system information.
                </p>
              </div>
            </div>

            <div className="pa-panel">
              <div className="pa-panel-header">
                <div>
                  <h3>
                    System information
                  </h3>

                  <p>
                    Current CONNECT platform
                    environment.
                  </p>
                </div>
              </div>

              <div className="pa-settings-list">
                <div className="pa-setting-row">
                  <div>
                    <strong>
                      Platform
                    </strong>

                    <span>
                      CONNECT Transport Platform
                    </span>
                  </div>

                  <span className="pa-setting-value">
                    Active
                  </span>
                </div>

                <div className="pa-setting-row">
                  <div>
                    <strong>
                      Access level
                    </strong>

                    <span>
                      Global platform
                      administration
                    </span>
                  </div>

                  <span className="pa-setting-value">
                    Platform
                  </span>
                </div>

                <div className="pa-setting-row">
                  <div>
                    <strong>
                      Companies
                    </strong>

                    <span>
                      Registered transport
                      companies
                    </span>
                  </div>

                  <span className="pa-setting-value">
                    {companies.length}
                  </span>
                </div>

                <div className="pa-setting-row">
                  <div>
                    <strong>
                      Routes
                    </strong>

                    <span>
                      Registered platform routes
                    </span>
                  </div>

                  <span className="pa-setting-value">
                    {routes.length}
                  </span>
                </div>

                <div className="pa-setting-row">
                  <div>
                    <strong>
                      Diagnostics
                    </strong>

                    <span>
                      Backend integrity checks
                    </span>
                  </div>

                  <button
                    type="button"
                    className="pa-secondary-button"
                    onClick={() =>
                      navigate(
                        '/platform-admin/system-tests'
                      )
                    }
                  >
                    Open tests
                  </button>
                </div>
              </div>
            </div>
          </section>
        )}
      </main>

      {companyModal && (
        <div className="pa-modal-backdrop">
          <div className="pa-modal">
            <div className="pa-modal-head">
              <div>
                <h3>
                  {companyEditingId
                    ? 'Edit company'
                    : 'Add company'}
                </h3>

                <p>
                  Platform administrators can create
                  and update transport companies.
                </p>
              </div>

              <button
                type="button"
                className="pa-icon-button"
                onClick={() =>
                  setCompanyModal(false)
                }
              >
                <X size={17} />
              </button>
            </div>

            <form
              className="pa-form"
              onSubmit={saveCompany}
            >
              <div className="pa-form-grid">
                <div className="pa-field full">
                  <label>
                    Company name
                  </label>

                  <input
                    value={companyForm.name}
                    onChange={(event) =>
                      setCompanyForm({
                        ...companyForm,
                        name: event.target.value,
                      })
                    }
                    required
                  />
                </div>

                <div className="pa-field full">
                  <label>
                    Areas served
                  </label>

                  <input
                    value={
                      companyForm.areas_served
                    }
                    onChange={(event) =>
                      setCompanyForm({
                        ...companyForm,
                        areas_served:
                          event.target.value,
                      })
                    }
                    placeholder="CBD, Rongai, Ngong..."
                    required
                  />
                </div>

                <div className="pa-field">
                  <label>
                    Phone number
                  </label>

                  <input
                    value={
                      companyForm.phone_number
                    }
                    onChange={(event) =>
                      setCompanyForm({
                        ...companyForm,
                        phone_number:
                          event.target.value,
                      })
                    }
                  />
                </div>

                <div className="pa-field full">
                  <label>
                    Description
                  </label>

                  <textarea
                    value={
                      companyForm.description
                    }
                    onChange={(event) =>
                      setCompanyForm({
                        ...companyForm,
                        description:
                          event.target.value,
                      })
                    }
                  />
                </div>
              </div>

              <div className="pa-modal-actions">
                <button
                  type="button"
                  className="pa-secondary-button"
                  onClick={() =>
                    setCompanyModal(false)
                  }
                >
                  Cancel
                </button>

                <button
                  type="submit"
                  className="pa-primary-button"
                  disabled={companySaving}
                >
                  {companySaving
                    ? 'Saving...'
                    : companyEditingId
                      ? 'Save Changes'
                      : 'Create Company'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {routeModal && (
        <div className="pa-modal-backdrop">
          <div className="pa-modal">
            <div className="pa-modal-head">
              <div>
                <h3>
                  {routeEditingId
                    ? 'Edit route'
                    : 'Add route'}
                </h3>

                <p>
                  Configure the route and owning
                  company.
                </p>
              </div>

              <button
                type="button"
                className="pa-icon-button"
                onClick={() =>
                  setRouteModal(false)
                }
              >
                <X size={17} />
              </button>
            </div>

            <form
              className="pa-form"
              onSubmit={saveRoute}
            >
              <div className="pa-form-grid">
                <div className="pa-field full">
                  <label>
                    Company
                  </label>

                  <select
                    value={
                      routeForm.company_id
                    }
                    onChange={(event) =>
                      setRouteForm({
                        ...routeForm,
                        company_id:
                          event.target.value,
                      })
                    }
                    required
                  >
                    <option value="">
                      Select company
                    </option>

                    {companies.map(
                      (company) => (
                        <option
                          key={company.id}
                          value={company.id}
                        >
                          {company.name}
                        </option>
                      )
                    )}
                  </select>
                </div>

                <div className="pa-field full">
                  <label>
                    Route name
                  </label>

                  <input
                    value={routeForm.name}
                    onChange={(event) =>
                      setRouteForm({
                        ...routeForm,
                        name: event.target.value,
                      })
                    }
                    required
                  />
                </div>

                <div className="pa-field">
                  <label>
                    Start point
                  </label>

                  <input
                    value={
                      routeForm.start_point
                    }
                    onChange={(event) =>
                      setRouteForm({
                        ...routeForm,
                        start_point:
                          event.target.value,
                      })
                    }
                    required
                  />
                </div>

                <div className="pa-field">
                  <label>
                    End point
                  </label>

                  <input
                    value={
                      routeForm.end_point
                    }
                    onChange={(event) =>
                      setRouteForm({
                        ...routeForm,
                        end_point:
                          event.target.value,
                      })
                    }
                    required
                  />
                </div>

                <div className="pa-field">
                  <label>
                    Price (KES)
                  </label>

                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={
                      routeForm.price
                    }
                    onChange={(event) =>
                      setRouteForm({
                        ...routeForm,
                        price: event.target.value,
                      })
                    }
                    required
                  />
                </div>
              </div>

              <div className="pa-modal-actions">
                <button
                  type="button"
                  className="pa-secondary-button"
                  onClick={() =>
                    setRouteModal(false)
                  }
                >
                  Cancel
                </button>

                <button
                  type="submit"
                  className="pa-primary-button"
                  disabled={routeSaving}
                >
                  {routeSaving
                    ? 'Saving...'
                    : routeEditingId
                      ? 'Save Changes'
                      : 'Create Route'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {driverModal && (
        <div className="pa-modal-backdrop">
          <div className="pa-modal">
            <div className="pa-modal-head">
              <div>
                <h3>
                  {driverEditingId
                    ? 'Edit driver'
                    : 'Add driver'}
                </h3>

                <p>
                  Assign the driver to exactly one
                  transport company.
                </p>
              </div>

              <button
                type="button"
                className="pa-icon-button"
                onClick={() =>
                  setDriverModal(false)
                }
              >
                <X size={17} />
              </button>
            </div>

            <form
              className="pa-form"
              onSubmit={saveDriver}
            >
              <div className="pa-form-grid">
                <div className="pa-field full">
                  <label>
                    Company
                  </label>

                  <select
                    value={
                      driverForm.company
                    }
                    onChange={(event) =>
                      setDriverForm({
                        ...driverForm,
                        company:
                          event.target.value,
                      })
                    }
                    required
                  >
                    <option value="">
                      Select company
                    </option>

                    {companies.map(
                      (company) => (
                        <option
                          key={company.id}
                          value={company.id}
                        >
                          {company.name}
                        </option>
                      )
                    )}
                  </select>
                </div>

                <div className="pa-field">
                  <label>
                    Driver name
                  </label>

                  <input
                    value={driverForm.name}
                    onChange={(event) =>
                      setDriverForm({
                        ...driverForm,
                        name: event.target.value,
                      })
                    }
                    required
                  />
                </div>

                <div className="pa-field">
                  <label>
                    Phone
                  </label>

                  <input
                    value={
                      driverForm.phone_number
                    }
                    onChange={(event) =>
                      setDriverForm({
                        ...driverForm,
                        phone_number:
                          event.target.value,
                      })
                    }
                  />
                </div>

                <div className="pa-field">
                  <label>
                    Bus number
                  </label>

                  <input
                    value={
                      driverForm.bus_number
                    }
                    onChange={(event) =>
                      setDriverForm({
                        ...driverForm,
                        bus_number:
                          event.target.value,
                      })
                    }
                  />
                </div>
              </div>

              <div className="pa-modal-actions">
                <button
                  type="button"
                  className="pa-secondary-button"
                  onClick={() =>
                    setDriverModal(false)
                  }
                >
                  Cancel
                </button>

                <button
                  type="submit"
                  className="pa-primary-button"
                  disabled={driverSaving}
                >
                  {driverSaving
                    ? 'Saving...'
                    : driverEditingId
                      ? 'Save Changes'
                      : 'Create Driver'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {tripModal && (
        <div className="pa-modal-backdrop">
          <div className="pa-modal">
            <div className="pa-modal-head">
              <div>
                <h3>
                  Create trip
                </h3>

                <p>
                  Create a scheduled trip using an
                  existing route and driver.
                </p>
              </div>

              <button
                type="button"
                className="pa-icon-button"
                onClick={() =>
                  setTripModal(false)
                }
              >
                <X size={17} />
              </button>
            </div>

            <form
              className="pa-form"
              onSubmit={createTrip}
            >
              <div className="pa-form-grid">
                <div className="pa-field full">
                  <label>
                    Company
                  </label>

                  <select
                    value={
                      tripForm.company_id
                    }
                    onChange={(event) =>
                      setTripForm({
                        ...tripForm,
                        company_id:
                          event.target.value,
                        route_id: '',
                        driver_id: '',
                      })
                    }
                    required
                  >
                    <option value="">
                      Select company
                    </option>

                    {companies.map(
                      (company) => (
                        <option
                          key={company.id}
                          value={company.id}
                        >
                          {company.name}
                        </option>
                      )
                    )}
                  </select>
                </div>

                <div className="pa-field full">
                  <label>
                    Route
                  </label>

                  <select
                    value={
                      tripForm.route_id
                    }
                    onChange={(event) =>
                      setTripForm({
                        ...tripForm,
                        route_id:
                          event.target.value,
                      })
                    }
                    required
                  >
                    <option value="">
                      Select route
                    </option>

                    {routes
                      .filter(
                        (route) =>
                          !tripForm.company_id ||
                          String(
                            route.company
                          ) ===
                            String(
                              tripForm.company_id
                            )
                      )
                      .map((route) => (
                        <option
                          key={route.id}
                          value={route.id}
                        >
                          {route.name}
                        </option>
                      ))}
                  </select>
                </div>

                <div className="pa-field full">
                  <label>
                    Driver
                  </label>

                  <select
                    value={
                      tripForm.driver_id
                    }
                    onChange={(event) =>
                      setTripForm({
                        ...tripForm,
                        driver_id:
                          event.target.value,
                      })
                    }
                    required
                  >
                    <option value="">
                      Select driver
                    </option>

                    {drivers
                      .filter(
                        (driver) =>
                          !tripForm.company_id ||
                          String(
                            driver.company
                          ) ===
                            String(
                              tripForm.company_id
                            )
                      )
                      .map((driver) => (
                        <option
                          key={driver.id}
                          value={driver.id}
                        >
                          {driver.name} —{' '}
                          {driver.bus_number ||
                            'No bus'}
                        </option>
                      ))}
                  </select>
                </div>

                <div className="pa-field">
                  <label>
                    Departure
                  </label>

                  <input
                    type="datetime-local"
                    value={
                      tripForm.departure_at
                    }
                    onChange={(event) =>
                      setTripForm({
                        ...tripForm,
                        departure_at:
                          event.target.value,
                      })
                    }
                    required
                  />
                </div>

                <div className="pa-field">
                  <label>
                    Capacity
                  </label>

                  <input
                    type="number"
                    min="1"
                    value={
                      tripForm.capacity
                    }
                    onChange={(event) =>
                      setTripForm({
                        ...tripForm,
                        capacity:
                          event.target.value,
                      })
                    }
                    required
                  />
                </div>
              </div>

              <div className="pa-modal-actions">
                <button
                  type="button"
                  className="pa-secondary-button"
                  onClick={() =>
                    setTripModal(false)
                  }
                >
                  Cancel
                </button>

                <button
                  type="submit"
                  className="pa-primary-button"
                  disabled={tripSaving}
                >
                  {tripSaving
                    ? 'Creating...'
                    : 'Create Trip'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {operatorModal && (
        <div className="pa-modal-backdrop">
          <div className="pa-modal">
            <div className="pa-modal-head">
              <div>
                <h3>
                  Add company staff
                </h3>

                <p>
                  Create a manager, auditor or
                  operator for one company.
                </p>
              </div>

              <button
                type="button"
                className="pa-icon-button"
                onClick={() =>
                  setOperatorModal(false)
                }
              >
                <X size={17} />
              </button>
            </div>

            <form
              className="pa-form"
              onSubmit={saveOperator}
            >
              <div className="pa-form-grid">
                <div className="pa-field">
                  <label>
                    Username
                  </label>

                  <input
                    value={
                      operatorForm.username
                    }
                    onChange={(event) =>
                      setOperatorForm({
                        ...operatorForm,
                        username:
                          event.target.value,
                      })
                    }
                    required
                  />
                </div>

                <div className="pa-field">
                  <label>
                    Email
                  </label>

                  <input
                    type="email"
                    value={
                      operatorForm.email
                    }
                    onChange={(event) =>
                      setOperatorForm({
                        ...operatorForm,
                        email:
                          event.target.value,
                      })
                    }
                  />
                </div>

                <div className="pa-field">
                  <label>
                    Phone
                  </label>

                  <input
                    value={
                      operatorForm.phone_number
                    }
                    onChange={(event) =>
                      setOperatorForm({
                        ...operatorForm,
                        phone_number:
                          event.target.value,
                      })
                    }
                  />
                </div>

                <div className="pa-field">
                  <label>
                    Location
                  </label>

                  <input
                    value={
                      operatorForm.location
                    }
                    onChange={(event) =>
                      setOperatorForm({
                        ...operatorForm,
                        location:
                          event.target.value,
                      })
                    }
                  />
                </div>

                <div className="pa-field">
                  <label>
                    Role
                  </label>

                  <select
                    value={
                      operatorForm.role
                    }
                    onChange={(event) =>
                      setOperatorForm({
                        ...operatorForm,
                        role: event.target.value,
                      })
                    }
                  >
                    <option value="company_manager">
                      Company Manager
                    </option>

                    <option value="company_operator">
                      Company Operator
                    </option>

                    <option value="company_auditor">
                      Company Auditor
                    </option>
                  </select>
                </div>

                <div className="pa-field">
                  <label>
                    Company
                  </label>

                  <select
                    value={
                      operatorForm.company
                    }
                    onChange={(event) =>
                      setOperatorForm({
                        ...operatorForm,
                        company:
                          event.target.value,
                      })
                    }
                    required
                  >
                    <option value="">
                      Select company
                    </option>

                    {companies.map(
                      (company) => (
                        <option
                          key={company.id}
                          value={company.id}
                        >
                          {company.name}
                        </option>
                      )
                    )}
                  </select>
                </div>

                <div className="pa-field full">
                  <label>
                    Temporary password
                  </label>

                  <input
                    type="password"
                    value={
                      operatorForm.password
                    }
                    onChange={(event) =>
                      setOperatorForm({
                        ...operatorForm,
                        password:
                          event.target.value,
                      })
                    }
                    minLength={6}
                    required
                  />
                </div>
              </div>

              <div className="pa-modal-actions">
                <button
                  type="button"
                  className="pa-secondary-button"
                  onClick={() =>
                    setOperatorModal(false)
                  }
                >
                  Cancel
                </button>

                <button
                  type="submit"
                  className="pa-primary-button"
                  disabled={operatorSaving}
                >
                  {operatorSaving
                    ? 'Creating...'
                    : 'Create Staff Account'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </PlatformShell>
  );
}