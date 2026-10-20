/**
 * ProtectedRoute — redirect unauthenticated users to /login (M1-AUTH-3).
 *
 * During the initial session-restore fetch (isLoading=true) renders a
 * full-screen spinner so there is no flash of the login page for users
 * who do have a valid session.
 *
 * Optionally accepts a `role` prop; if the authenticated user's role does
 * not match, renders a 403-style message rather than redirecting to login.
 */

import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { LoadingSpinner } from './ui';

interface ProtectedRouteProps {
  children: ReactNode;
  /** If supplied, also enforces the required role. */
  role?: string;
}

export function ProtectedRoute({ children, role }: ProtectedRouteProps) {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="page-shell" aria-busy="true">
        <LoadingSpinner label="Restoring session…" size="lg" />
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  if (role && user.role !== role) {
    return (
      <div className="page-shell">
        <div className="auth-card auth-card--narrow">
          <h1 className="auth-card__title">Access Denied</h1>
          <p className="text-secondary">
            You do not have permission to view this page.
          </p>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
