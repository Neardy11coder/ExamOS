/**
 * RegisterPage (M1-AUTH-3).
 *
 * Implements FR-AUTH-010, Appendix A OD-01, API §2 POST /auth/register.
 *
 * Behaviour:
 *   - Collects display name, email, password, and confirm-password.
 *   - Client-side validation: non-blank fields, email format, password ≥ 8 chars,
 *     passwords match.
 *   - Disables submit while in-flight.
 *   - On 409: surfaces "Registration could not be completed" without disclosing
 *     whether the account exists.
 *   - On success (201): navigates to /login with a success notice so the user
 *     can sign in; does NOT auto-login after registration (keeps flows separate
 *     and avoids a second round-trip).
 *   - Never exposes a role picker (OD-01: students only via self-registration).
 */

import { type FormEvent, useId, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { GraduationCap } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { ApiError } from '../api/auth';
import { FormField, InlineError, LoadingSpinner, PageShell } from '../components/ui';

export function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const uid = useId();

  const [displayName, setDisplayName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [fieldErrors, setFieldErrors] = useState<{
    displayName?: string;
    email?: string;
    password?: string;
    confirmPassword?: string;
  }>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  function validate(): boolean {
    const errs: typeof fieldErrors = {};
    if (!displayName.trim()) errs.displayName = 'Full name is required.';
    else if (displayName.trim().length > 200)
      errs.displayName = 'Full name must not exceed 200 characters.';

    if (!email.trim()) errs.email = 'Email is required.';
    else if (!email.includes('@')) errs.email = 'Enter a valid email address.';

    if (!password) errs.password = 'Password is required.';
    else if (password.length < 8) errs.password = 'Password must be at least 8 characters.';
    else if (password.length > 128) errs.password = 'Password must not exceed 128 characters.';

    if (!confirmPassword) errs.confirmPassword = 'Please confirm your password.';
    else if (password && confirmPassword && password !== confirmPassword)
      errs.confirmPassword = 'Passwords do not match.';

    setFieldErrors(errs);
    return Object.keys(errs).length === 0;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setServerError(null);
    if (!validate()) return;

    setIsSubmitting(true);
    try {
      await register(email.trim().toLowerCase(), displayName.trim(), password);
      // Navigate to login with a success flag so LoginPage can show a notice.
      navigate('/login', { state: { registered: true }, replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setServerError(
          'Registration could not be completed. Check your details and try again.',
        );
      } else if (err instanceof ApiError && err.status === 422) {
        setServerError('One or more fields are invalid. Please review and try again.');
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
        <h1 className="auth-card__title">Create a student account</h1>
        <p className="auth-card__subtitle">
          Register to access published examinations.
        </p>
      </div>

      <form
        className="auth-form"
        onSubmit={handleSubmit}
        noValidate
        aria-label="Student registration form"
      >
        {serverError && (
          <InlineError message={serverError} id={`${uid}-server-error`} />
        )}

        <FormField
          id={`${uid}-display-name`}
          label="Full name"
          type="text"
          autoComplete="name"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          error={fieldErrors.displayName}
          disabled={isSubmitting}
          required
        />

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
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={fieldErrors.password}
          disabled={isSubmitting}
          required
        />

        <FormField
          id={`${uid}-confirm-password`}
          label="Confirm password"
          type="password"
          autoComplete="new-password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          error={fieldErrors.confirmPassword}
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
              <LoadingSpinner size="sm" label="Creating account…" />
              <span>Creating account…</span>
            </>
          ) : (
            'Create account'
          )}
        </button>
      </form>

      <p className="auth-card__footer">
        Already have an account?{' '}
        <Link to="/login" className="auth-link">
          Sign in
        </Link>
      </p>
    </PageShell>
  );
}
