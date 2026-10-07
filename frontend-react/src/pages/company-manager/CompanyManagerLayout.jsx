import { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import {
  BarChart3,
  Bus,
  CalendarDays,
  ClipboardList,
  Gauge,
  Menu,
  Package,
  CarFront,
  Route,
  Settings,
  ShieldCheck,
  Users,
  WalletCards,
  LogOut,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

const nav = [
  { label: 'Overview', path: '/company-manager', icon: Gauge, end: true },
  { label: 'Company Profile', path: '/company-manager/companies', icon: Bus },
  { label: 'Routes', path: '/company-manager/routes', icon: Route },
  { label: 'Trips', path: '/company-manager/trips', icon: CalendarDays },
  { label: 'Drivers', path: '/company-manager/drivers', icon: Users },
  { label: 'Operators', path: '/company-manager/operators', icon: ShieldCheck },
  { label: 'Bookings', path: '/company-manager/bookings', icon: ClipboardList },
  { label: 'Parcels', path: '/company-manager/parcels', icon: Package },
  { label: 'Bus hire', path: '/company-manager/charters', icon: CarFront },
  { label: 'Seats & Capacity', path: '/company-manager/capacity', icon: Bus },
  { label: 'Pricing', path: '/company-manager/pricing', icon: WalletCards },
  { label: 'Revenue', path: '/company-manager/revenue', icon: BarChart3 },
  { label: 'Settings', path: '/company-manager/settings', icon: Settings },
];

export default function CompanyManagerLayout() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);

  const closeMenu = () => setOpen(false);

  const management = nav.slice(0, 9);
  const operations = nav.slice(9, 12);
  const settings = nav[12];

  return (
    <div className="company-management-page">

      {open && (
        <button
          type="button"
          className="company-sidebar-overlay"
          onClick={closeMenu}
          aria-label="Close navigation"
        />
      )}

      <aside className={`company-sidebar ${open ? 'open' : ''}`}>
        <div className="company-brand">
          <div className="company-brand-mark">C</div>
          <div>
            <strong>CONNECT</strong>
            <span>Company Manager</span>
          </div>
        </div>

        <div className="company-user-identity">
          <div className="company-user-name">
            {user?.username || 'Company Manager'}
          </div>
          <div className="company-user-role">
            Company Manager
          </div>
          <div className="company-user-company">
            {user?.company_name || 'My Company'}
          </div>
        </div>

        <div className="company-nav-label">MANAGEMENT</div>

        <div className="company-sidebar-links">
          {management.map(({ label, path, icon: Icon, end }) => (
            <NavLink
              key={path}
              to={path}
              end={end}
              onClick={closeMenu}
              className={({ isActive }) =>
                `company-nav-link ${isActive ? 'active' : ''}`
              }
            >
              <Icon size={18} />
              <span>{label}</span>
            </NavLink>
          ))}
        </div>

        <div className="company-nav-label">OPERATIONS</div>

        <div className="company-sidebar-links">
          {operations.map(({ label, path, icon: Icon }) => (
            <NavLink
              key={path}
              to={path}
              onClick={closeMenu}
              className={({ isActive }) =>
                `company-nav-link ${isActive ? 'active' : ''}`
              }
            >
              <Icon size={18} />
              <span>{label}</span>
            </NavLink>
          ))}
        </div>

        <div className="company-nav-label">SYSTEM</div>

        <NavLink
          to={settings.path}
          onClick={closeMenu}
          className={({ isActive }) =>
            `company-nav-link ${isActive ? 'active' : ''}`
          }
        >
          <settings.icon size={18} />
          <span>{settings.label}</span>
        </NavLink>

        <div style={{ marginTop: 'auto', paddingTop: 18 }}>
          <button
            type="button"
            className="company-nav-link company-manager-logout-link"
            onClick={() => {
              closeMenu();
              logout();
            }}
            style={{
              width: '100%',
              background: 'transparent',
              cursor: 'pointer',
              border: '1px solid transparent',
              font: 'inherit',
              textAlign: 'left',
            }}
          >
            <LogOut size={18} />
            <span>Logout</span>
          </button>
        </div>
      </aside>

      <main className="company-management-main">
        <header className="company-management-topbar">
          <button
            type="button"
            className="company-mobile-menu"
            onClick={() => setOpen(true)}
            aria-label="Open navigation"
          >
            <Menu size={21} />
          </button>

          <div>
            <p className="company-eyebrow">COMPANY MANAGER</p>
            <h1>{user?.company_name || 'My Company'}</h1>
          </div>

          <div className="company-top-actions">
            <button
              type="button"
              className="company-logout"
              onClick={logout}
            >
              Logout
            </button>
          </div>
        </header>

        <Outlet />
      </main>
    </div>
  );
}
