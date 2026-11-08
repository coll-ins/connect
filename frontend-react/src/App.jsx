import { lazy, Suspense, useEffect, useState } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';
import Notice, { NoticeStack } from './components/ui/Notice';
import { clearRequestError, getLatestRequestError } from './api';

function RequestErrorNotice() {
  const [message, setMessage] = useState(getLatestRequestError);

  useEffect(() => {
    const showError = (event) => {
      setMessage(event.detail?.message || 'Something went wrong. Please try again.');
    };
    window.addEventListener('connect:request-error', showError);
    return () => window.removeEventListener('connect:request-error', showError);
  }, []);

  return (
    <NoticeStack>
      {message && (
        <Notice
          kind="error"
          title="Something went wrong"
          onClose={() => {
            clearRequestError();
            setMessage('');
          }}
        >
          {message}
        </Notice>
      )}
    </NoticeStack>
  );
}

const Login = lazy(() => import('./pages/auth/Login'));
const Signup = lazy(() => import('./pages/auth/Signup'));

const PassengerDashboard = lazy(() => import('./pages/passenger/PassengerDashboard'));
const PassengerMapPage = lazy(() => import('./pages/passenger/PassengerMapPage'));
const PaymentReturn = lazy(() => import('./pages/passenger/PaymentReturn'));
const DeliveryList = lazy(() => import('./pages/passenger/DeliveryPages').then(m => ({ default: m.DeliveryList })));
const DeliveryDetail = lazy(() => import('./pages/passenger/DeliveryPages').then(m => ({ default: m.DeliveryDetail })));
const DeliveryNew = lazy(() => import('./pages/passenger/DeliveryWizard').then(m => ({ default: m.DeliveryNew })));
const CharterList = lazy(() => import('./pages/passenger/CharterPages').then(m => ({ default: m.CharterList })));
const CharterDetail = lazy(() => import('./pages/passenger/CharterPages').then(m => ({ default: m.CharterDetail })));
const CharterNew = lazy(() => import('./pages/passenger/CharterWizard').then(m => ({ default: m.CharterNew })));
const PassengerBookings = lazy(() => import('./pages/passenger/PassengerPages').then(m => ({ default: m.PassengerBookings })));
const PassengerWallet = lazy(() => import('./pages/passenger/PassengerPages').then(m => ({ default: m.PassengerWallet })));
const PassengerPayments = lazy(() => import('./pages/passenger/PassengerPages').then(m => ({ default: m.PassengerPayments })));
const PassengerProfile = lazy(() => import('./pages/passenger/PassengerPages').then(m => ({ default: m.PassengerProfile })));
const PassengerRecords = lazy(() => import('./pages/passenger/PassengerPages').then(m => ({ default: m.PassengerRecords })));
const PassengerSeats = lazy(() => import('./pages/passenger/PassengerPages').then(m => ({ default: m.PassengerSeats })));
const LegalPage = lazy(() => import('./legal/LegalPage'));
const PassengerHelp = lazy(() => import('./pages/passenger/PassengerPages').then(m => ({ default: m.PassengerHelp })));

const DriverPortal = lazy(() => import('./pages/driver/DriverPortal.jsx'));
const DriverLiveLocation = lazy(() => import('./pages/driver/DriverLiveLocation.jsx'));
const CompanyManagerRoutes = lazy(() => import('./pages/company-manager/CompanyManagerRoutes'));
const CompanyAuditorDashboard = lazy(() => import('./pages/company-auditor/CompanyAuditorDashboard'));
const CompanyOperatorDashboard = lazy(() => import('./pages/company-operator/CompanyOperatorDashboard'));
const PlatformAdminDashboard = lazy(() => import('./pages/platform-admin/PlatformAdminDashboard'));

function PassengerRoutes() {
  return (
    <ProtectedRoute allowedRoles={['passenger']}>
      <Routes>
        <Route index element={<PassengerDashboard />} />
        <Route path="schedules" element={<PassengerDashboard initialJourneyStep="companies" />} />
        <Route path="map" element={<PassengerMapPage />} />
        <Route path="bookings" element={<PassengerBookings />} />
        <Route path="wallet" element={<PassengerWallet />} />
        <Route path="payments" element={<PassengerPayments />} />
        <Route path="receipts" element={<PassengerRecords mode="receipts" />} />
        <Route path="history" element={<PassengerRecords mode="history" />} />
        <Route path="seats" element={<PassengerSeats />} />
        <Route path="help" element={<PassengerHelp />} />
        <Route path="profile" element={<PassengerProfile />} />
        <Route path="payment/:bookingId" element={<PaymentReturn />} />
        <Route path="delivery" element={<DeliveryList />} />
        <Route path="delivery/new" element={<DeliveryNew />} />
        <Route path="delivery/:id" element={<DeliveryDetail />} />
        <Route path="charter" element={<CharterList />} />
        <Route path="charter/new" element={<CharterNew />} />
        <Route path="charter/:id" element={<CharterDetail />} />
        <Route
          path="*"
          element={<Navigate to="/passenger" replace />}
        />
      </Routes>
    </ProtectedRoute>
  );
}

function DriverRoutes() {
  return (
    <ProtectedRoute allowedRoles={['driver']}>
      <Routes>
        <Route index element={<DriverPortal />} />
        <Route path="trips" element={<DriverPortal />} />
        <Route path="passengers" element={<DriverPortal />} />
        <Route path="location" element={<DriverLiveLocation />} />
        <Route path="boarding" element={<DriverPortal />} />
        <Route path="jobs" element={<DriverPortal />} />
        <Route path="profile" element={<DriverPortal />} />
        <Route path="*" element={<Navigate to="/driver" replace />} />
      </Routes>
    </ProtectedRoute>
  );
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/login" replace />} />
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route path="/legal" element={<Navigate to="/legal/terms" replace />} />
      <Route path="/legal/:slug" element={<LegalPage />} />

      <Route path="/passenger/*" element={<PassengerRoutes />} />

      <Route path="/driver/*" element={<DriverRoutes />} />

      <Route
        path="/company-manager/*"
        element={
          <ProtectedRoute allowedRoles={['company_manager']}>
            <CompanyManagerRoutes />
          </ProtectedRoute>
        }
      />

      <Route
        path="/company-auditor/*"
        element={
          <ProtectedRoute allowedRoles={['company_auditor']}>
            <CompanyAuditorDashboard />
          </ProtectedRoute>
        }
      />

      <Route
        path="/company-operator/*"
        element={
          <ProtectedRoute allowedRoles={['company_operator']}>
            <CompanyOperatorDashboard />
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
          <RequestErrorNotice />
          <Suspense fallback={<div role="status">Loading CONNECT...</div>}>
            <AppRoutes />
          </Suspense>
        </div>
      </BrowserRouter>
    </AuthProvider>
  );
}
