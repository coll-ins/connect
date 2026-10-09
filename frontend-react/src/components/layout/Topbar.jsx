import { useEffect, useState } from 'react';
import { Bell, Search } from 'lucide-react';
import { apiRequest } from '../../api';

// Roles whose home is the alert feed. Passengers/drivers don't poll it.
const STAFF_ROLES = ['company_manager', 'company_operator'];

export default function Topbar({ user }) {
  const roleLabel = (user?.role || 'user')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

  const shouldPoll = Boolean(
    user && (STAFF_ROLES.includes(user.role) || user.is_superuser)
  );
  const [alertCount, setAlertCount] = useState(0);

  useEffect(() => {
    if (!shouldPoll) return undefined;

    let cancelled = false;

    const load = async () => {
      try {
        const data = await apiRequest('/bookings/alerts/');
        if (!cancelled) {
          setAlertCount(Number(data?.count) || 0);
        }
      } catch {
        // A failed poll never breaks the shell; retry on the next tick.
      }
    };

    load();
    const timer = setInterval(load, 60000);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [shouldPoll, user?.id]);

  return (
    <header className="connect-topbar">
      <div className="topbar-search">
        <Search size={18} />
        <input
          type="search"
          placeholder="Search CONNECT..."
          aria-label="Search CONNECT"
        />
        <kbd>⌘ K</kbd>
      </div>

      <div className="topbar-actions">
        <button
          type="button"
          className="topbar-icon-button"
          aria-label={
            alertCount > 0 ? `Notifications: ${alertCount} new` : 'Notifications'
          }
        >
          <Bell size={19} />
          {shouldPoll && alertCount > 0 && <span className="notification-dot" />}
        </button>

        <div className="topbar-divider" />

        <div className="topbar-profile">
          <div className="topbar-avatar">
            {(user?.name || 'U').charAt(0).toUpperCase()}
          </div>

          <div className="topbar-profile-copy">
            <strong>{user?.name || 'User'}</strong>
            <span>{roleLabel}</span>
          </div>
        </div>
      </div>
    </header>
  );
}
