/**
 * DashboardPage — role-aware post-login landing page (M1-AUTH-3).
 *
 * This is a placeholder shell for future milestone work (M2+ exam UI).
 * It:
 *   - Displays the user's name and role.
 *   - Provides a functional Logout button that sends the CSRF-protected
 *     POST /auth/logout request and clears client state.
 *   - Shows role-appropriate navigation hints so the design surface is in
 *     place for later milestones.
 *
 * It is accessible only via <ProtectedRoute>; the auth-guard redirect to
 * /login happens there.
 */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity, BookOpen, ClipboardList, LogOut, Settings, User } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { ApiError } from '../api/auth';
import { InlineError } from '../components/ui';

function RoleBadge({ role }: { role: string }) {
  const label = role === 'FACULTY_ADMIN' ? 'Faculty / Admin' : 'Student';
  return (
    <span className={`role-badge role-badge--${role === 'FACULTY_ADMIN' ? 'faculty' : 'student'}`}>
      {label}
    </span>
  );
}

interface NavCardProps {
  icon: React.ReactNode;
  title: string;
  description: string;
  href?: string;
  comingSoon?: boolean;
}

function NavCard({ icon, title, description, href, comingSoon }: NavCardProps) {
  const content = (
    <div className={`nav-card${comingSoon ? ' nav-card--disabled' : ''}`}>
      <div className="nav-card__icon" aria-hidden="true">{icon}</div>
      <div className="nav-card__content">
        <h3 className="nav-card__title">{title}</h3>
        <p className="nav-card__description">{description}</p>
      </div>
      {comingSoon && <span className="nav-card__badge">Coming soon</span>}
    </div>
  );

  if (href && !comingSoon) {
    return (
      <a href={href} style={{ textDecoration: 'none', color: 'inherit', display: 'block' }}>
        {content}
      </a>
    );
  }

  return content;
}

export function DashboardPage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);

  async function handleLogout() {
    setLogoutError(null);
    setIsLoggingOut(true);
    try {
      await logout();
      navigate('/login', { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        setLogoutError('Logout failed. Please try again.');
      } else {
        setLogoutError('An unexpected error occurred.');
      }
      setIsLoggingOut(false);
    }
  }

  if (!user) return null; // ProtectedRoute guards this; defensive only.

  const isFaculty = user.role === 'FACULTY_ADMIN';

  const studentLinks: NavCardProps[] = [
    {
      icon: <BookOpen />,
      title: 'Available Exams',
      description: 'View, start, or continue published examinations.',
      href: '/exams/available',
    },
    {
      icon: <ClipboardList />,
      title: 'My Results',
      description: 'Review your submitted and expired attempt results in Available Exams.',
      href: '/exams/available',
    },
    {
      icon: <Activity />,
      title: 'My Performance',
      description: 'Analytics across your finalized attempts.',
      comingSoon: true,
    },
  ];

  const facultyLinks: NavCardProps[] = [
    {
      icon: <BookOpen />,
      title: 'Examinations',
      description: 'Create, author drafts, and publish exams.',
      href: '/faculty/exams',
    },
    {
      icon: <ClipboardList />,
      title: 'Question Bank',
      description: 'Author, edit, and organize MCQ questions.',
      href: '/faculty/questions',
    },
    {
      icon: <Activity />,
      title: 'Results & Analytics',
      description: 'Aggregated results for all attempts.',
      comingSoon: true,
    },
    {
      icon: <Settings />,
      title: 'OS Scheduling Simulator',
      description: 'Run scheduling algorithm simulations.',
      href: '/faculty/os-scheduler',
    },
  ];

  const links = isFaculty ? facultyLinks : studentLinks;

  return (
    <div className="app-shell">
      {/* Top navigation bar */}
      <header className="app-header" role="banner">
        <div className="app-header__brand">
          <Activity className="app-header__logo-icon" aria-hidden="true" />
          <span className="app-header__logo-text">ExamOS</span>
        </div>
        <div className="app-header__user">
          <User className="app-header__user-icon" aria-hidden="true" />
          <span className="app-header__user-name">{user.display_name}</span>
          <RoleBadge role={user.role} />
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={handleLogout}
            disabled={isLoggingOut}
            aria-label="Sign out"
          >
            <LogOut className="btn__icon" aria-hidden="true" />
            {isLoggingOut ? 'Signing out…' : 'Sign out'}
          </button>
        </div>
      </header>

      {/* Main content */}
      <main className="app-main" id="main-content">
        {logoutError && (
          <div className="dashboard-error">
            <InlineError message={logoutError} />
          </div>
        )}

        <div className="dashboard-hero">
          <h1 className="dashboard-hero__title">
            Welcome back, {user.display_name.split(' ')[0]}.
          </h1>
          <p className="dashboard-hero__subtitle text-secondary">
            {isFaculty
              ? 'Manage your examinations, question bank, and review results.'
              : 'View available exams, continue in-progress attempts, and review your results.'}
          </p>
        </div>

        <nav aria-label="Dashboard navigation">
          <ul className="nav-grid" role="list">
            {links.map((link) => (
              <li key={link.title}>
                <NavCard {...link} />
              </li>
            ))}
          </ul>
        </nav>
      </main>
    </div>
  );
}
