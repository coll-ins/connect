import { Bell, Search } from 'lucide-react';

export default function Topbar({ user }) {
  const roleLabel = (user?.role || 'user')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

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
          aria-label="Notifications"
        >
          <Bell size={19} />
          <span className="notification-dot" />
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
