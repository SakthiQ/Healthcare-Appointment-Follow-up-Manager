import { Navigate, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import ProtectedRoute from './auth/ProtectedRoute';
import { useAuth, homePathForRole } from './auth/AuthContext';
import { Spinner } from './components/ui';

import Login from './pages/Login';
import Register from './pages/Register';

import PatientDashboard from './pages/patient/PatientDashboard';
import DoctorSearch from './pages/patient/DoctorSearch';
import BookAppointment from './pages/patient/BookAppointment';
import PatientAppointments from './pages/patient/PatientAppointments';
import PatientAppointmentDetail from './pages/patient/PatientAppointmentDetail';

import DoctorDashboard from './pages/doctor/DoctorDashboard';
import DoctorAppointments from './pages/doctor/DoctorAppointments';
import DoctorAppointmentDetail from './pages/doctor/DoctorAppointmentDetail';

import AdminDashboard from './pages/admin/AdminDashboard';
import DoctorManagement from './pages/admin/DoctorManagement';
import DoctorConfig from './pages/admin/DoctorConfig';
import ConflictedAppointments from './pages/admin/ConflictedAppointments';

function RootRedirect() {
  const { user, loading } = useAuth();
  if (loading) return <Spinner label="Loading…" />;
  return <Navigate to={user ? homePathForRole(user.role) : '/login'} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />

      <Route element={<Layout />}>
        <Route path="/" element={<RootRedirect />} />

        {/* --- Patient portal --- */}
        <Route
          path="/patient"
          element={
            <ProtectedRoute roles={['PATIENT']}>
              <PatientDashboard />
            </ProtectedRoute>
          }
        />
        <Route
          path="/patient/doctors"
          element={
            <ProtectedRoute roles={['PATIENT']}>
              <DoctorSearch />
            </ProtectedRoute>
          }
        />
        <Route
          path="/patient/doctors/:doctorId"
          element={
            <ProtectedRoute roles={['PATIENT']}>
              <BookAppointment />
            </ProtectedRoute>
          }
        />
        <Route
          path="/patient/appointments"
          element={
            <ProtectedRoute roles={['PATIENT']}>
              <PatientAppointments />
            </ProtectedRoute>
          }
        />
        <Route
          path="/patient/appointments/:appointmentId"
          element={
            <ProtectedRoute roles={['PATIENT']}>
              <PatientAppointmentDetail />
            </ProtectedRoute>
          }
        />

        {/* --- Doctor portal --- */}
        <Route
          path="/doctor"
          element={
            <ProtectedRoute roles={['DOCTOR']}>
              <DoctorDashboard />
            </ProtectedRoute>
          }
        />
        <Route
          path="/doctor/appointments"
          element={
            <ProtectedRoute roles={['DOCTOR']}>
              <DoctorAppointments />
            </ProtectedRoute>
          }
        />
        <Route
          path="/doctor/appointments/:appointmentId"
          element={
            <ProtectedRoute roles={['DOCTOR']}>
              <DoctorAppointmentDetail />
            </ProtectedRoute>
          }
        />

        {/* --- Admin portal --- */}
        <Route
          path="/admin"
          element={
            <ProtectedRoute roles={['ADMIN']}>
              <AdminDashboard />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/doctors"
          element={
            <ProtectedRoute roles={['ADMIN']}>
              <DoctorManagement />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/doctors/:doctorId"
          element={
            <ProtectedRoute roles={['ADMIN']}>
              <DoctorConfig />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/conflicts"
          element={
            <ProtectedRoute roles={['ADMIN']}>
              <ConflictedAppointments />
            </ProtectedRoute>
          }
        />

        <Route path="*" element={<RootRedirect />} />
      </Route>
    </Routes>
  );
}
