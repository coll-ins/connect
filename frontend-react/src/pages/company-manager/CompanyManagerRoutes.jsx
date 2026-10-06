import { Routes, Route, Navigate } from 'react-router-dom';
import CompanyManagerLayout from './CompanyManagerLayout';
import CompanyManagerOverview from './CompanyManagerOverview';
import CompanyManagerSection from './CompanyManagerSection';

export default function CompanyManagerRoutes() {
  return (
    <Routes>
      <Route element={<CompanyManagerLayout />}>
        <Route index element={<CompanyManagerOverview />} />

        <Route
          path="companies"
          element={<CompanyManagerSection section="company" />}
        />

        <Route
          path="routes"
          element={<CompanyManagerSection section="routes" />}
        />

        <Route
          path="trips"
          element={<CompanyManagerSection section="trips" />}
        />

        <Route
          path="drivers"
          element={<CompanyManagerSection section="drivers" />}
        />

        <Route
          path="operators"
          element={<CompanyManagerSection section="operators" />}
        />

        <Route
          path="bookings"
          element={<CompanyManagerSection section="bookings" />}
        />

        <Route
          path="capacity"
          element={<CompanyManagerSection section="capacity" />}
        />

        <Route
          path="pricing"
          element={<CompanyManagerSection section="pricing" />}
        />

        <Route
          path="revenue"
          element={<CompanyManagerSection section="revenue" />}
        />

        <Route
          path="settings"
          element={<CompanyManagerSection section="settings" />}
        />

        <Route
          path="*"
          element={<Navigate to="/company-manager" replace />}
        />
      </Route>
    </Routes>
  );
}
