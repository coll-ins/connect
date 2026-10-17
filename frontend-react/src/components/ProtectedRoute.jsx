import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { dashboardPath } from '../utils/roleRoutes';

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
