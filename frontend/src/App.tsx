/**
 * App — root router for ExamOS (M1-AUTH-3).
 *
 * Route table:
 *   /               → redirect to /login
 *   /login          → LoginPage  (public; redirects authenticated users to /dashboard)
 *   /register       → RegisterPage (public; students only)
 *   /dashboard      → DashboardPage (ProtectedRoute)
 *
 * The AuthProvider wraps the entire tree so any descendant can call useAuth().
 * react-router-dom BrowserRouter is set in main.tsx so this file stays testable.
 */

import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { useAuth } from './contexts/AuthContext';
import { ProtectedRoute } from './components/ProtectedRoute';
import { LoginPage } from './pages/LoginPage';
import { RegisterPage } from './pages/RegisterPage';
import { DashboardPage } from './pages/DashboardPage';
import { AvailableExamsPage } from './pages/AvailableExamsPage';
import { AttemptWorkspacePage } from './pages/AttemptWorkspacePage';
import { AttemptResultPage } from './pages/AttemptResultPage';
import { QuestionBankPage } from './pages/QuestionBankPage';
import { FacultyExamsPage } from './pages/FacultyExamsPage';
import { ExamEditorPage } from './pages/ExamEditorPage';
import { LoadingSpinner } from './components/ui';

/**
 * Thin wrapper around LoginPage that redirects already-authenticated users
 * away from the auth pages so pressing Back after logout works correctly.
 */
function PublicOnlyRoute({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();
  if (isLoading) {
    return (
      <div className="page-shell" aria-busy="true">
        <LoadingSpinner label="Restoring session…" size="lg" />
      </div>
    );
  }
  if (user) {
    return <Navigate to="/dashboard" replace />;
  }
  return <>{children}</>;
}

/**
 * LoginPageWithNotice — passes a success notice if the user just registered.
 */
function LoginPageWithNotice() {
  const location = useLocation();
  const registered = (location.state as { registered?: boolean } | null)?.registered;
  // LoginPage reads this via its own location if we pass it, or we can
  // render a banner here above LoginPage.  For simplicity, we inject it
  // into the page via a wrapper banner.
  return (
    <>
      {registered && (
        <div className="page-shell__notice" role="status" aria-live="polite">
          Account created — you can now sign in.
        </div>
      )}
      <LoginPage />
    </>
  );
}

export function App() {
  return (
    <Routes>
      {/* Default redirect */}
      <Route path="/" element={<Navigate to="/login" replace />} />

      {/* Public auth routes */}
      <Route
        path="/login"
        element={
          <PublicOnlyRoute>
            <LoginPageWithNotice />
          </PublicOnlyRoute>
        }
      />
      <Route
        path="/register"
        element={
          <PublicOnlyRoute>
            <RegisterPage />
          </PublicOnlyRoute>
        }
      />

      {/* Protected routes */}
      <Route
        path="/dashboard"
        element={
          <ProtectedRoute>
            <DashboardPage />
          </ProtectedRoute>
        }
      />

      {/* Student examination routes (M1-STUD-UI-1) */}
      <Route
        path="/exams/available"
        element={
          <ProtectedRoute role="STUDENT">
            <AvailableExamsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/attempts/:attemptId"
        element={
          <ProtectedRoute role="STUDENT">
            <AttemptWorkspacePage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/attempts/:attemptId/result"
        element={
          <ProtectedRoute>
            <AttemptResultPage />
          </ProtectedRoute>
        }
      />

      {/* Faculty routes (M1-EXAM-UI-1) */}
      <Route
        path="/faculty/questions"
        element={
          <ProtectedRoute role="FACULTY_ADMIN">
            <QuestionBankPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/faculty/exams"
        element={
          <ProtectedRoute role="FACULTY_ADMIN">
            <FacultyExamsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/faculty/exams/:examId"
        element={
          <ProtectedRoute role="FACULTY_ADMIN">
            <ExamEditorPage />
          </ProtectedRoute>
        }
      />

      {/* Fallback */}
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}

export default App;
