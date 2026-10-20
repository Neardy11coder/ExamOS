/**
 * Shared UI primitives (M1-AUTH-3).
 *
 * FormField   – labelled input wrapper with accessible error display.
 * InlineError – standalone inline error message (icon + text).
 * LoadingSpinner – accessible spinner.
 */

import type { InputHTMLAttributes, ReactNode } from 'react';
import { AlertCircle, Loader2 } from 'lucide-react';

// ---------------------------------------------------------------------------
// FormField
// ---------------------------------------------------------------------------

interface FormFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  id: string;
  label: string;
  error?: string;
}

export function FormField({ id, label, error, ...inputProps }: FormFieldProps) {
  const errorId = `${id}-error`;
  return (
    <div className="form-field">
      <label htmlFor={id} className="form-label">
        {label}
      </label>
      <input
        id={id}
        aria-describedby={error ? errorId : undefined}
        aria-invalid={error ? true : undefined}
        className={`form-input${error ? ' form-input--error' : ''}`}
        {...inputProps}
      />
      {error && (
        <p id={errorId} className="form-field-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// InlineError
// ---------------------------------------------------------------------------

interface InlineErrorProps {
  message: string;
  id?: string;
}

export function InlineError({ message, id }: InlineErrorProps) {
  return (
    <div className="inline-error" role="alert" id={id}>
      <AlertCircle className="inline-error__icon" aria-hidden="true" />
      <span>{message}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// LoadingSpinner
// ---------------------------------------------------------------------------

interface LoadingSpinnerProps {
  label?: string;
  size?: 'sm' | 'md' | 'lg';
}

export function LoadingSpinner({ label = 'Loading…', size = 'md' }: LoadingSpinnerProps) {
  const sizeClass = {
    sm: 'spinner--sm',
    md: 'spinner--md',
    lg: 'spinner--lg',
  }[size];
  return (
    <span className={`spinner ${sizeClass}`} role="status" aria-label={label}>
      <Loader2 className="spinner__icon" aria-hidden="true" />
    </span>
  );
}

// ---------------------------------------------------------------------------
// PageShell — centred card container for auth pages
// ---------------------------------------------------------------------------

export function PageShell({ children }: { children: ReactNode }) {
  return (
    <div className="page-shell">
      <div className="auth-card">
        {children}
      </div>
    </div>
  );
}
