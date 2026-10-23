/**
 * Student Catalogue Page — /exams/available (M1-STUD-UI-1).
 *
 * Responsibilities:
 * - Fetches published exams available to the student via GET /api/v1/exams/available.
 * - Displays title, duration, question count, marks, and student attempt status.
 * - Handles states:
 *     - No attempt: "Start Exam" triggers POST /exams/{exam_id}/attempts/start.
 *     - IN_PROGRESS attempt: "Resume Exam" navigates to /attempts/{attempt_id}.
 *     - SUBMITTED or EXPIRED attempt: "View Results" navigates to /attempts/{attempt_id}/result.
 * - Handles loading, empty state, and error with retry.
 * - Disables action buttons during flight to prevent accidental double-clicks.
 */

import { useCallback, useEffect, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  AlertCircle,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  Clock,
  FileQuestion,
  HelpCircle,
  Play,
  RotateCcw,
} from 'lucide-react';
import {
  apiGetAvailableExams,
  apiStartExamAttempt,
  type AvailableExamItem,
} from '../api/attempts';
import { useAuth } from '../contexts/AuthContext';
import { LoadingSpinner } from '../components/ui';

export function AvailableExamsPage() {
  const { csrfToken } = useAuth();
  const navigate = useNavigate();

  const [exams, setExams] = useState<AvailableExamItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [startingExamId, setStartingExamId] = useState<string | null>(null);

  const loadExams = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await apiGetAvailableExams();
      setExams(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Unable to load available exams.';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadExams();
  }, [loadExams]);

  async function handleStartOrResume(exam: AvailableExamItem) {
    if (exam.has_attempt && exam.attempt_id) {
      if (exam.attempt_status === 'IN_PROGRESS') {
        navigate(`/attempts/${exam.attempt_id}`);
        return;
      }
      if (exam.attempt_status === 'SUBMITTED' || exam.attempt_status === 'EXPIRED') {
        navigate(`/attempts/${exam.attempt_id}/result`);
        return;
      }
    }

    // Start new attempt (or resume existing server-side)
    setStartingExamId(exam.id);
    try {
      const attempt = await apiStartExamAttempt(exam.id, csrfToken);
      navigate(`/attempts/${attempt.attempt_id}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to start examination.';
      setError(msg);
      setStartingExamId(null);
    }
  }

  return (
    <div className="app-shell">
      <header className="app-header" role="banner">
        <div className="app-header__brand">
          <BookOpen className="app-header__logo-icon" aria-hidden="true" />
          <Link to="/dashboard" className="app-header__logo-text text-accent" style={{ textDecoration: 'none' }}>
            ExamOS
          </Link>
          <span className="text-secondary" style={{ margin: '0 0.5rem' }}>/</span>
          <span className="text-secondary font-medium">Available Exams</span>
        </div>
        <div className="app-header__user">
          <Link to="/dashboard" className="btn btn--ghost btn--sm">
            Back to Dashboard
          </Link>
        </div>
      </header>

      <main className="app-main" id="main-content">
        <div className="dashboard-hero">
          <h1 className="dashboard-hero__title">Available Examinations</h1>
          <p className="dashboard-hero__subtitle text-secondary">
            Select an examination below to start or continue your attempt.
          </p>
        </div>

        {error && (
          <div className="inline-error" style={{ marginBottom: '1.5rem' }} role="alert">
            <AlertCircle className="inline-error__icon" aria-hidden="true" />
            <div style={{ flex: 1 }}>
              <p style={{ margin: '0 0 0.5rem 0' }}>{error}</p>
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={loadExams}
                style={{ fontSize: '0.8125rem' }}
              >
                <RotateCcw className="btn__icon" aria-hidden="true" /> Retry
              </button>
            </div>
          </div>
        )}

        {isLoading ? (
          <div style={{ textAlign: 'center', padding: '4rem 1rem' }} aria-busy="true">
            <LoadingSpinner label="Loading examinations…" size="lg" />
            <p className="text-secondary" style={{ marginTop: '1rem' }}>
              Fetching published examinations…
            </p>
          </div>
        ) : exams.length === 0 ? (
          <div className="exam-card exam-card--empty">
            <HelpCircle className="exam-card__empty-icon" aria-hidden="true" />
            <h2 className="exam-card__empty-title">No examinations currently available</h2>
            <p className="text-secondary">
              There are no published examinations open for enrollment at this time. Please check back later.
            </p>
          </div>
        ) : (
          <div className="exam-list" role="list">
            {exams.map((exam) => {
              const isStarting = startingExamId === exam.id;
              const isTerminal =
                exam.has_attempt &&
                (exam.attempt_status === 'SUBMITTED' || exam.attempt_status === 'EXPIRED');
              const isInProgress = exam.has_attempt && exam.attempt_status === 'IN_PROGRESS';

              return (
                <article key={exam.id} className="exam-card" role="listitem">
                  <div className="exam-card__header">
                    <div className="exam-card__title-row">
                      <h2 className="exam-card__title">{exam.title}</h2>
                      {isTerminal && (
                        <span className="exam-badge exam-badge--completed">
                          <CheckCircle2 size={13} aria-hidden="true" /> Finalized ({exam.attempt_status})
                        </span>
                      )}
                      {isInProgress && (
                        <span className="exam-badge exam-badge--active">
                          <Clock size={13} aria-hidden="true" /> In Progress
                        </span>
                      )}
                    </div>
                    {exam.instructions && (
                      <p className="exam-card__instructions text-secondary">
                        {exam.instructions}
                      </p>
                    )}
                  </div>

                  <div className="exam-card__meta-bar">
                    <div className="exam-meta-item">
                      <Clock size={16} className="text-muted" aria-hidden="true" />
                      <span>{exam.duration_minutes} mins</span>
                    </div>
                    <div className="exam-meta-item">
                      <FileQuestion size={16} className="text-muted" aria-hidden="true" />
                      <span>{exam.question_count} questions</span>
                    </div>
                    <div className="exam-meta-item">
                      <span className="text-muted font-medium">Marks:</span>
                      <span>{Number(exam.total_marks).toFixed(2)}</span>
                    </div>
                  </div>

                  <div className="exam-card__footer">
                    {isTerminal ? (
                      <Link
                        to={`/attempts/${exam.attempt_id}/result`}
                        className="btn btn--ghost"
                      >
                        View Results <ArrowRight className="btn__icon" aria-hidden="true" />
                      </Link>
                    ) : (
                      <button
                        type="button"
                        className="btn btn--primary"
                        onClick={() => handleStartOrResume(exam)}
                        disabled={isStarting}
                        aria-busy={isStarting}
                      >
                        {isStarting ? (
                          <>
                            <LoadingSpinner size="sm" />
                            <span>Connecting…</span>
                          </>
                        ) : isInProgress ? (
                          <>
                            <Play className="btn__icon" aria-hidden="true" /> Resume Examination
                          </>
                        ) : (
                          <>
                            <Play className="btn__icon" aria-hidden="true" /> Start Examination
                          </>
                        )}
                      </button>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}
