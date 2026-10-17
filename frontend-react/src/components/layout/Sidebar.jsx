import { NavLink } from 'react-router-dom';
import { LogOut, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { getNavigation } from '../navigation/navigationConfig';

export default function Sidebar({
  user,
  logout,
  collapsed,
  mobileOpen,
  onToggle,
  onMobileClose,
}) {
  const navigation = getNavigation(user?.role);
  const showLabels = !collapsed || mobileOpen;

  return (
    <aside
      className={`connect-sidebar ${
        collapsed ? 'is-collapsed' : ''
      } ${mobileOpen ? 'mobile-open' : ''}`}
    >
      <div className="sidebar-brand">
        <div className="sidebar-logo">C</div>

        {showLabels && (
          <div className="sidebar-brand-copy">
            <strong>CONNECT</strong>
            <span>Smart matatu travel</span>
          </div>
        )}
      </div>

      <button
        type="button"
        className="sidebar-toggle"
        onClick={onToggle}
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
      </button>

      <nav className="sidebar-nav">
        <div className="sidebar-section-label">
          {showLabels && 'Workspace'}
        </div>

        {navigation.map(({ label, icon: Icon, path }) => (
          <NavLink
            key={path}
            onClick={onMobileClose}
            to={path}
            end={path === `/${user?.role?.replace('_', '-')}`}
            className={({ isActive }) =>
              `sidebar-link ${isActive ? 'active' : ''}`
            }
            title={collapsed ? label : undefined}
          >
            <Icon size={19} strokeWidth={1.9} />

            {showLabels && <span>{label}</span>}
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-bottom">
        {showLabels && (
          <div className="sidebar-user">
            <div className="sidebar-avatar">
              {(user?.name || 'U').charAt(0).toUpperCase()}
            </div>

            <div className="sidebar-user-info">
              <strong>{user?.name || 'User'}</strong>
              <span>
                {(user?.role || 'user')
                  .replace(/_/g, ' ')
                  .replace(/\b\w/g, (letter) => letter.toUpperCase())}
              </span>
            </div>
          </div>
        )}

        <button
          type="button"
          className="sidebar-logout"
          onClick={() => {
            onMobileClose?.();
            logout();
          }}
          title={collapsed ? 'Logout' : undefined}
        >
          <LogOut size={18} />
          {showLabels && <span>Logout</span>}
        </button>
      </div>
    </aside>
  );
}
