import { Navigate, useLocation } from 'react-router-dom';
import type { ReactNode } from 'react';
import { useAuth, homePathForRole } from './AuthContext';
import type { UserRole } from '../api/types';
import { Spinner } from '../components/ui';

/**
 * Client-side routing guard. This is a navigation convenience only —
 * the backend enforces authorisation on every request and remains the
 * only authority on what a role may actually do.
 */
export default function ProtectedRoute({
  roles,
  children,
}: {
  roles?: UserRole[];
  children: ReactNode;
}) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) return <Spinner label="Checking your session…" />;

  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />;

  if (roles && !roles.includes(user.role)) {
    // Signed in, but wrong portal — send them to their own.
    return <Navigate to={homePathForRole(user.role)} replace />;
  }

  return <>{children}</>;
}
