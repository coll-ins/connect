import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

function dashboardPath(user) {
  if (!user) return '/login';

  switch (user.role) {
    case 'platform_admin':
      return '/platform-admin';

    case 'company_admin':
      return '/company-admin';

    case 'driver':
      return '/driver';

    case 'passenger':
    default:
      return '/passenger';
  }
}

export default function ProtectedRoute({ allowedRoles, children }) {
  const { user, booting } = useAuth();

  if (booting) {
    return <div className="loading-screen">Loading CONNECT…</div>;
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  if (!allowedRoles.includes(user.role)) {
    return <Navigate to={dashboardPath(user)} replace />;
  }

  return children;
}
