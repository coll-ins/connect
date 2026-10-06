import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';
import Login from './pages/auth/Login';
import Signup from './pages/auth/Signup';
import PassengerDashboard from './pages/passenger/PassengerDashboard';
import PaymentReturn from './pages/passenger/PaymentReturn';
import DriverDashboard from './pages/driver/DriverDashboard';
import CompanyAdminDashboard from './pages/company-admin/CompanyAdminDashboard';
import PlatformAdminDashboard from './pages/platform-admin/PlatformAdminDashboard';

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

function Home() {
  const { user, booting } = useAuth();

  if (booting) {
    return <div className="loading-screen">Loading CONNECT…</div>;
  }

  return <Navigate to={dashboardPath(user)} replace />;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />

      <Route path="/login" element={<Login />} />

      <Route path="/signup" element={<Signup />} />

      <Route
        path="/passenger/payment/:bookingId"
        element={
          <ProtectedRoute allowedRoles={['passenger']}>
            <PaymentReturn />
          </ProtectedRoute>
        }
      />

      <Route
        path="/passenger/*"
        element={
          <ProtectedRoute allowedRoles={['passenger']}>
            <PassengerDashboard />
          </ProtectedRoute>
        }
      />

      <Route
        path="/driver/*"
        element={
          <ProtectedRoute allowedRoles={['driver']}>
            <DriverDashboard />
          </ProtectedRoute>
        }
      />

      <Route
        path="/company-admin/*"
        element={
          <ProtectedRoute allowedRoles={['company_admin']}>
            <CompanyAdminDashboard />
          </ProtectedRoute>
        }
      />

      <Route
        path="/platform-admin/*"
        element={
          <ProtectedRoute allowedRoles={['platform_admin']}>
            <PlatformAdminDashboard />
          </ProtectedRoute>
        }
      />

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <div className="app-shell">
          <AppRoutes />
        </div>
      </BrowserRouter>
    </AuthProvider>
  );
}
