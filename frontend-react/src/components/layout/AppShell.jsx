import { useState } from 'react';
import { Menu, X } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import Sidebar from './Sidebar';
import Topbar from './Topbar';
import PageTransition from './PageTransition';

export default function AppShell({ children }) {
  const { user, logout } = useAuth();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div
      className={`connect-app ${collapsed ? 'sidebar-collapsed' : ''} ${
        mobileOpen ? 'mobile-sidebar-open' : ''
      }`}
    >
      <Sidebar
        user={user}
        logout={logout}
        collapsed={collapsed}
        mobileOpen={mobileOpen}
        onToggle={() => setCollapsed((value) => !value)}
        onMobileClose={() => setMobileOpen(false)}
      />

      {mobileOpen && (
        <button
          type="button"
          className="connect-mobile-backdrop"
          onClick={() => setMobileOpen(false)}
          aria-label="Close navigation"
        />
      )}

      <button
        type="button"
        className="connect-mobile-menu"
        onClick={() => setMobileOpen((value) => !value)}
        aria-label={mobileOpen ? 'Close navigation' : 'Open navigation'}
      >
        {mobileOpen ? <X size={21} /> : <Menu size={21} />}
      </button>

      <div className="connect-main">
        <Topbar user={user} />

        <main className="connect-content">
          <PageTransition>
            {children}
          </PageTransition>
        </main>
      </div>
    </div>
  );
}
