import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { dashboardPath } from '../utils/roleRoutes';

export default function ProtectedRoute({ allowedRoles, children }) {
  const { user, booting } = useAuth();
  const location = useLocation();

  if (booting) {
    return <div className="loading-screen">Loading CONNECT…</div>;
  }

  if (!user) {
    // Remember where they were going (e.g. back from a bank payment) so
    // logging in finishes that instead of dropping them on the dashboard.
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: `${location.pathname}${location.search}` }}
      />
    );
  }

  if (!allowedRoles.includes(user.role)) {
    return <Navigate to={dashboardPath(user)} replace />;
  }

  return children;
}
