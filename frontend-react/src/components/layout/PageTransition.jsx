import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { titleForPath } from '../../utils/pageTitle';

// Each page renders its own AppShell, so this component remounts on every
// navigation; the last path has to live outside it to tell a route change from
// the first load (which must not steal focus).
let lastPath = null;

export default function PageTransition({ children }) {
  const location = useLocation();

  useEffect(function announceRoute() {
    document.title = titleForPath(location.pathname);
    if (lastPath !== null && lastPath !== location.pathname) {
      document.getElementById('main-content')?.focus({ preventScroll: true });
    }
    lastPath = location.pathname;
  }, [location.pathname]);

  return (
    <div key={location.pathname} className="page-transition">
      {children}
    </div>
  );
}
