/**
 * Finalized Examination Result Page — /attempts/:attemptId/result (M1-STUD-UI-1).
 *
 * Responsibilities:
 * - Fetches authoritative finalized results from GET /api/v1/attempts/{attempt_id}/result.
 * - Confirms score, total marks, percentage, and completion timestamp.
 * - Handles non-finalized attempts (400 RESULT_NOT_AVAILABLE) by directing student back to workspace.
 * - Post-finalization answer breakdown:
 *     - Displays student's selected option vs the correct option.
 *     - Never calculates or discloses correctness on the client; uses server fields is_correct and student_selected_option_id.
 * - Provides navigation back to available exams or student dashboard.
 */

import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  AlertCircle,
  ArrowLeft,
  Award,
  CheckCircle2,
  Clock,
  HelpCircle,
  ListOrdered,
  XCircle,
} from 'lucide-react';
import {
  apiGetAttemptResult,
  type AttemptResultResponse,
  type ResultQuestionItem,
} from '../api/attempts';
import { LoadingSpinner } from '../components/ui';

export function AttemptResultPage() {
  const { attemptId } = useParams<{ attemptId: string }>();
  const navigate = useNavigate();

  const [result, setResult] = useState<AttemptResultResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isNotFinalized, setIsNotFinalized] = useState(false);

  const loadResult = useCallback(async () => {
    if (!attemptId) return;
    setIsLoading(true);
    setError(null);
    setIsNotFinalized(false);
    try {
      const data = await apiGetAttemptResult(attemptId);
      setResult(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to retrieve results.';
      if (msg.includes('only available after') || msg.includes('RESULT_NOT_AVAILABLE')) {
        setIsNotFinalized(true);
      } else {
        setError(msg);
      }
    } finally {
      setIsLoading(false);
    }
  }, [attemptId]);

  useEffect(() => {
    loadResult();
  }, [loadResult]);

  if (isLoading) {
    return (
      <div className="page-shell" aria-busy="true">
        <LoadingSpinner label="Loading examination results…" size="lg" />
        <p className="text-secondary" style={{ marginTop: '1rem' }}>
          Retrieving finalized assessment report…
        </p>
      </div>
    );
  }

  if (isNotFinalized) {
    return (
      <div className="page-shell">
        <div className="auth-card">
          <Clock className="text-warning" size={36} style={{ marginBottom: '1rem' }} />
          <h1 className="auth-card__title">Attempt Still In Progress</h1>
          <p className="text-secondary" style={{ marginBottom: '1.5rem' }}>
            Results can only be viewed after the examination attempt is finalized (submitted or expired).
          </p>
          <button
            type="button"
            className="btn btn--primary btn--full"
            onClick={() => navigate(`/attempts/${attemptId}`)}
          >
            Resume Examination
          </button>
        </div>
      </div>
    );
  }

  if (error || !result) {
    return (
      <div className="page-shell">
        <div className="auth-card">
          <AlertCircle className="text-error" size={36} style={{ marginBottom: '1rem' }} />
          <h1 className="auth-card__title">Unable to Load Result</h1>
          <p className="text-secondary" style={{ marginBottom: '1.5rem' }}>
            {error ?? 'An unexpected error occurred while fetching your examination result.'}
          </p>
          <Link to="/exams/available" className="btn btn--primary btn--full">
            Back to Available Exams
          </Link>
        </div>
      </div>
    );
  }

  const questions: ResultQuestionItem[] = result.questions ?? [];
  const correctCount = questions.filter((q) => q.is_correct).length;
  const totalCount = questions.length;
  const scoreNum = Number(result.score);
  const totalMarksNum = Number(result.total_marks);
  const percentNum = Number(result.percentage);

  return (
    <div className="app-shell">
      <header className="app-header" role="banner">
        <div className="app-header__brand">
          <Award className="app-header__logo-icon text-accent" aria-hidden="true" />
          <Link to="/dashboard" className="app-header__logo-text text-accent" style={{ textDecoration: 'none' }}>
            ExamOS
          </Link>
          <span className="text-secondary" style={{ margin: '0 0.5rem' }}>/</span>
          <span className="text-secondary font-medium">Examination Result</span>
        </div>
        <div className="app-header__user">
          <Link to="/exams/available" className="btn btn--ghost btn--sm">
            <ArrowLeft className="btn__icon" aria-hidden="true" /> Available Exams
          </Link>
        </div>
      </header>

      <main className="app-main" id="main-content">
        {/* Results Hero Card */}
        <div className="results-hero-card">
          <div className="results-hero-card__header">
            <div>
              <span className="workspace-badge" style={{ marginBottom: '0.5rem' }}>
                {result.status === 'SUBMITTED' ? 'SUBMITTED ATTEMPT' : 'EXPIRED ATTEMPT'}
              </span>
              <h1 className="results-hero-card__title">{result.exam_title}</h1>
              <p className="text-secondary" style={{ fontSize: '0.875rem', margin: 0 }}>
                Finalized at {new Date(result.finalized_at).toLocaleString()}
              </p>
            </div>

            <div className="results-score-badge">
              <div className="results-score-badge__val">
                {percentNum.toFixed(1)}%
              </div>
              <div className="results-score-badge__sub">
                {scoreNum.toFixed(1)} / {totalMarksNum.toFixed(1)} marks
              </div>
            </div>
          </div>

          <div className="results-metrics-grid">
            <div className="results-metric">
              <span className="results-metric__label">Correct Answers</span>
              <span className="results-metric__val text-success">
                {correctCount} / {totalCount}
              </span>
            </div>
            <div className="results-metric">
              <span className="results-metric__label">Total Questions</span>
              <span className="results-metric__val text-text">{totalCount}</span>
            </div>
            <div className="results-metric">
              <span className="results-metric__label">Status</span>
              <span className="results-metric__val text-accent">{result.status}</span>
            </div>
          </div>
        </div>

        {/* Section Heading */}
        <div style={{ margin: '2rem 0 1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <ListOrdered className="text-secondary" size={20} aria-hidden="true" />
          <h2 style={{ fontSize: '1.25rem', fontWeight: 600, margin: 0 }}>Question Breakdown & Review</h2>
        </div>

        {questions.length === 0 ? (
          <div className="exam-card exam-card--empty">
            <HelpCircle className="exam-card__empty-icon" aria-hidden="true" />
            <p className="text-secondary">No question details available for this attempt.</p>
          </div>
        ) : (
          <div className="results-question-list" role="list">
            {questions.map((q, idx) => {
              const isCorrect = q.is_correct;
              const hasAnswered = q.student_selected_option_id !== null;

              return (
                <article key={q.exam_question_id} className="result-question-card" role="listitem">
                  <div className="result-question-card__header">
                    <div className="result-question-card__title-row">
                      <span className="result-q-number">Q{idx + 1}</span>
                      <span className="text-secondary" style={{ fontSize: '0.875rem' }}>
                        {Number(q.marks).toFixed(1)} marks
                      </span>
                      {q.topic_name && (
                        <span className="exam-badge" style={{ fontSize: '0.75rem' }}>
                          {q.topic_name}
                        </span>
                      )}
                    </div>

                    <div className="result-q-outcome">
                      {isCorrect ? (
                        <span className="result-status-tag result-status-tag--correct">
                          <CheckCircle2 size={15} aria-hidden="true" /> Correct (+{Number(q.marks).toFixed(1)})
                        </span>
                      ) : (
                        <span className="result-status-tag result-status-tag--incorrect">
                          <XCircle size={15} aria-hidden="true" /> {hasAnswered ? 'Incorrect' : 'Unanswered'} (0.0)
                        </span>
                      )}
                    </div>
                  </div>

                  <p className="result-question-prompt">{q.prompt}</p>

                  <div className="result-options-list" role="list">
                    {q.options.map((opt) => {
                      const wasSelected = q.student_selected_option_id === opt.id;
                      const isOptionCorrect = opt.is_correct;

                      let optModifier = '';
                      if (isOptionCorrect) {
                        optModifier = 'result-opt--correct';
                      } else if (wasSelected && !isOptionCorrect) {
                        optModifier = 'result-opt--wrong-choice';
                      }

                      return (
                        <div
                          key={opt.id}
                          className={`result-opt ${optModifier}`}
                          role="listitem"
                        >
                          <div className="result-opt__indicator">
                            {isOptionCorrect ? (
                              <CheckCircle2 size={16} className="text-success" aria-hidden="true" />
                            ) : wasSelected ? (
                              <XCircle size={16} className="text-error" aria-hidden="true" />
                            ) : (
                              <span className="result-opt__empty-dot" aria-hidden="true" />
                            )}
                          </div>
                          <span className="result-opt__text">{opt.text}</span>
                          <div className="result-opt__badges">
                            {wasSelected && (
                              <span className="result-badge result-badge--choice">Your choice</span>
                            )}
                            {isOptionCorrect && (
                              <span className="result-badge result-badge--key">Correct Answer</span>
                            )}
                          </div>
                        </div>
                      );
                    })}
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
