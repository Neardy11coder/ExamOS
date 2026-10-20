/**
 * LoginPage (M1-AUTH-3).
 *
 * Implements FR-AUTH-001, FR-AUTH-002, API §2 POST /auth/login.
 *
 * Behaviour:
 *   - Validates email and password client-side before submission.
 *   - Disables the submit button while a request is in flight (FR-AUTH-010
 *     UI principle: no duplicate submission while pending).
 *   - Displays a generic "Invalid email or password" error on 401.
 *   - On success, navigates to the dashboard; the AuthContext stores the
 *     user and CSRF token so subsequent protected requests can use them.
 *   - Provides a link to the student registration page.
 */

import { type FormEvent, useId, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { GraduationCap } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { ApiError } from '../api/auth';
import { FormField, InlineError, LoadingSpinner, PageShell } from '../components/ui';

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const uid = useId();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fieldErrors, setFieldErrors] = useState<{ email?: string; password?: string }>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  function validate(): boolean {
    const errs: typeof fieldErrors = {};
    if (!email.trim()) errs.email = 'Email is required.';
    else if (!email.includes('@')) errs.email = 'Enter a valid email address.';
    if (!password) errs.password = 'Password is required.';
    setFieldErrors(errs);
    return Object.keys(errs).length === 0;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setServerError(null);
    if (!validate()) return;

    setIsSubmitting(true);
    try {
      await login(email.trim().toLowerCase(), password);
      navigate('/dashboard', { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setServerError('Invalid email or password.');
      } else {
        setServerError('Something went wrong. Please try again.');
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <PageShell>
      <div className="auth-card__header">
        <div className="auth-logo" aria-hidden="true">
          <GraduationCap />
        </div>
        <h1 className="auth-card__title">Sign in to ExamOS</h1>
        <p className="auth-card__subtitle">Enter your credentials to continue.</p>
      </div>

      <form
        className="auth-form"
        onSubmit={handleSubmit}
        noValidate
        aria-label="Sign in form"
      >
        {serverError && (
          <InlineError message={serverError} id={`${uid}-server-error`} />
        )}

        <FormField
          id={`${uid}-email`}
          label="Email address"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={fieldErrors.email}
          disabled={isSubmitting}
          required
        />

        <FormField
          id={`${uid}-password`}
          label="Password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={fieldErrors.password}
          disabled={isSubmitting}
          required
        />

        <button
          type="submit"
          className="btn btn--primary btn--full"
          disabled={isSubmitting}
          aria-describedby={serverError ? `${uid}-server-error` : undefined}
        >
          {isSubmitting ? (
            <>
              <LoadingSpinner size="sm" label="Signing in…" />
              <span>Signing in…</span>
            </>
          ) : (
            'Sign in'
          )}
        </button>
      </form>

      <p className="auth-card__footer">
        Don&apos;t have an account?{' '}
        <Link to="/register" className="auth-link">
          Create a student account
        </Link>
      </p>
    </PageShell>
  );
}
