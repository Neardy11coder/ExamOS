/**
 * Active Examination Workspace — /attempts/:attemptId (M1-STUD-UI-1).
 *
 * Responsibilities:
 * - Loads authoritative attempt state via GET /api/v1/attempts/{attempt_id}.
 * - Renders exam metadata, numbered question navigation palette, and question prompt.
 * - Handles question selection without exposing correctness keys.
 * - Manages answer autosave via PUT /api/v1/attempts/{attempt_id}/answers/{exam_question_id}.
 * - Displays per-question save indicators: 'saved', 'saving', 'save-failed'.
 * - Displays non-colour question palette status: Current (bold/indicator), Answered (✓), Unanswered (•), Review (⚑).
 * - Implements countdown timer based on server remaining_seconds and deadline_at.
 * - On 0 countdown, auto-triggers authoritative refresh, locking workspace if status transitions to EXPIRED.
 * - Handles optimistic concurrency (409 ANSWER_REVISION_CONFLICT) by accepting server revision safely.
 * - Provides submit confirmation modal with counts of answered/unanswered/flagged questions.
 * - Submits via POST /api/v1/attempts/{attempt_id}/submit and redirects to /attempts/{attempt_id}/result.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  AlertCircle,
  AlertTriangle,
  Bookmark,
  Check,
  CheckCircle,
  ChevronLeft,
  ChevronRight,
  Clock,
  HelpCircle,
  Loader2,
  Send,
  X,
} from 'lucide-react';
import {
  apiGetAttempt,
  apiSaveAnswer,
  apiSubmitAttempt,
  RevisionConflictError,
  type AttemptDetailRead,
  type StudentQuestionRead,
} from '../api/attempts';
import { useAuth } from '../contexts/AuthContext';
import { LoadingSpinner } from '../components/ui';

type SaveStatus = 'idle' | 'saving' | 'saved' | 'failed';

export function AttemptWorkspacePage() {
  const { attemptId } = useParams<{ attemptId: string }>();
  const { csrfToken } = useAuth();
  const navigate = useNavigate();

  const [attempt, setAttempt] = useState<AttemptDetailRead | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Active question index
  const [currentIndex, setCurrentIndex] = useState(0);

  // Per-question save status: questionId -> SaveStatus
  const [saveStatuses, setSaveStatuses] = useState<Record<string, SaveStatus>>({});
  // Per-question save error messages
  const [saveErrors, setSaveErrors] = useState<Record<string, string>>({});

  // Countdown seconds remaining
  const [remainingSeconds, setRemainingSeconds] = useState<number | null>(null);

  // Submit modal
  const [showSubmitModal, setShowSubmitModal] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Track pending save promises to block premature submit races
  const inFlightSavesRef = useRef<Set<string>>(new Set());

  // -------------------------------------------------------------------------
  // 1. Authoritative Attempt Loader
  // -------------------------------------------------------------------------
  const loadAttempt = useCallback(
    async (isInitial = false) => {
      if (!attemptId) return;
      if (isInitial) setIsLoading(true);
      try {
        const data = await apiGetAttempt(attemptId);
        setAttempt(data);
        setRemainingSeconds(Math.max(0, data.remaining_seconds));

        // If already finalized, redirect to result
        if (data.status === 'SUBMITTED' || data.status === 'EXPIRED') {
          navigate(`/attempts/${attemptId}/result`, { replace: true });
          return;
        }
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'Failed to load attempt.';
        setLoadError(msg);
      } finally {
        if (isInitial) setIsLoading(false);
      }
    },
    [attemptId, navigate],
  );

  useEffect(() => {
    loadAttempt(true);
  }, [loadAttempt]);

  // -------------------------------------------------------------------------
  // 2. Countdown Timer
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (remainingSeconds === null || remainingSeconds <= 0) return;

    const timer = setInterval(() => {
      setRemainingSeconds((prev) => {
        if (prev === null) return null;
        if (prev <= 1) {
          clearInterval(timer);
          // Zero reached: trigger authoritative backend sync
          loadAttempt(false);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [remainingSeconds, loadAttempt]);

  // -------------------------------------------------------------------------
  // 3. Question Navigation & Computed Stats
  // -------------------------------------------------------------------------
  const questions: StudentQuestionRead[] = useMemo(() => {
    return attempt?.questions ?? [];
  }, [attempt]);

  const currentQuestion: StudentQuestionRead | undefined = questions[currentIndex];

  const totalQuestions = questions.length;
  const answeredCount = questions.filter((q) => q.answer.selected_option_id !== null).length;
  const flaggedCount = questions.filter((q) => q.answer.marked_for_review).length;
  const unansweredCount = totalQuestions - answeredCount;

  // Format countdown mm:ss or hh:mm:ss
  const formatTime = (secs: number) => {
    const hours = Math.floor(secs / 3600);
    const minutes = Math.floor((secs % 3600) / 60);
    const seconds = secs % 60;
    if (hours > 0) {
      return `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    }
    return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
  };

  // -------------------------------------------------------------------------
  // 4. Durable Answer Saving
  // -------------------------------------------------------------------------
  const persistAnswer = async (
    qId: string,
    selectedOptionId: string | null,
    markedForReview: boolean,
    expectedRevision: number,
  ) => {
    if (!attemptId) return;

    inFlightSavesRef.current.add(qId);
    setSaveStatuses((prev) => ({ ...prev, [qId]: 'saving' }));
    setSaveErrors((prev) => {
      const next = { ...prev };
      delete next[qId];
      return next;
    });

    try {
      const resp = await apiSaveAnswer(
        attemptId,
        qId,
        {
          selected_option_id: selectedOptionId,
          marked_for_review: markedForReview,
          expected_revision: expectedRevision,
        },
        csrfToken,
      );

      // Server confirmed save: update authoritative local state
      setAttempt((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          questions: prev.questions.map((q) =>
            q.exam_question_id === qId
              ? {
                  ...q,
                  answer: {
                    selected_option_id: resp.selected_option_id,
                    marked_for_review: resp.marked_for_review,
                    revision: resp.revision,
                  },
                }
              : q,
          ),
        };
      });

      setSaveStatuses((prev) => ({ ...prev, [qId]: 'saved' }));
    } catch (err: unknown) {
      if (err instanceof RevisionConflictError) {
        // 409 Conflict: reconcile with canonical server state
        const canonical = err.canonicalState;
        setAttempt((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            questions: prev.questions.map((q) =>
              q.exam_question_id === qId
                ? {
                    ...q,
                    answer: {
                      selected_option_id: canonical.selected_option_id,
                      marked_for_review: canonical.marked_for_review,
                      revision: canonical.revision,
                    },
                  }
                : q,
            ),
          };
        });
        setSaveStatuses((prev) => ({ ...prev, [qId]: 'failed' }));
        setSaveErrors((prev) => ({
          ...prev,
          [qId]: 'Answer was modified in another session. Synchronized with server.',
        }));
      } else {
        const msg = err instanceof Error ? err.message : 'Save failed. Please retry.';
        setSaveStatuses((prev) => ({ ...prev, [qId]: 'failed' }));
        setSaveErrors((prev) => ({ ...prev, [qId]: msg }));
      }
    } finally {
      inFlightSavesRef.current.delete(qId);
    }
  };

  const handleSelectOption = (optionId: string) => {
    if (!currentQuestion || attempt?.status !== 'IN_PROGRESS') return;
    const currentSelected = currentQuestion.answer.selected_option_id;
    // Allow toggle deselect if student clicks active option, or select new
    const nextSelected = currentSelected === optionId ? null : optionId;

    // Optimistically update local view while flight persists
    setAttempt((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        questions: prev.questions.map((q, idx) =>
          idx === currentIndex
            ? {
                ...q,
                answer: {
                  ...q.answer,
                  selected_option_id: nextSelected,
                },
              }
            : q,
        ),
      };
    });

    persistAnswer(
      currentQuestion.exam_question_id,
      nextSelected,
      currentQuestion.answer.marked_for_review,
      currentQuestion.answer.revision,
    );
  };

  const handleToggleReview = () => {
    if (!currentQuestion || attempt?.status !== 'IN_PROGRESS') return;
    const nextFlag = !currentQuestion.answer.marked_for_review;

    setAttempt((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        questions: prev.questions.map((q, idx) =>
          idx === currentIndex
            ? {
                ...q,
                answer: {
                  ...q.answer,
                  marked_for_review: nextFlag,
                },
              }
            : q,
        ),
      };
    });

    persistAnswer(
      currentQuestion.exam_question_id,
      currentQuestion.answer.selected_option_id,
      nextFlag,
      currentQuestion.answer.revision,
    );
  };

  // -------------------------------------------------------------------------
  // 5. Final Submission
  // -------------------------------------------------------------------------
  const handleSubmit = async () => {
    if (!attemptId || isSubmitting) return;

    // Check if any saves are still in flight
    if (inFlightSavesRef.current.size > 0) {
      setSubmitError('Answers are currently saving. Please wait a moment before submitting.');
      return;
    }

    setIsSubmitting(true);
    setSubmitError(null);

    try {
      await apiSubmitAttempt(attemptId, {}, csrfToken);
      setShowSubmitModal(false);
      navigate(`/attempts/${attemptId}/result`, { replace: true });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Submission failed. Please try again.';
      setSubmitError(msg);
      setIsSubmitting(false);
    }
  };

  // -------------------------------------------------------------------------
  // Rendering
  // -------------------------------------------------------------------------
  if (isLoading) {
    return (
      <div className="page-shell" aria-busy="true">
        <LoadingSpinner label="Loading examination workspace…" size="lg" />
        <p className="text-secondary" style={{ marginTop: '1rem' }}>
          Loading assessment snapshot…
        </p>
      </div>
    );
  }

  if (loadError || !attempt) {
    return (
      <div className="page-shell">
        <div className="auth-card">
          <AlertCircle className="text-error" size={32} style={{ marginBottom: '1rem' }} />
          <h1 className="auth-card__title">Unable to Open Examination</h1>
          <p className="text-secondary" style={{ marginBottom: '1.5rem' }}>
            {loadError ?? 'Examination attempt could not be found or verified.'}
          </p>
          <button
            type="button"
            className="btn btn--primary btn--full"
            onClick={() => navigate('/exams/available')}
          >
            Return to Available Exams
          </button>
        </div>
      </div>
    );
  }

  const isTimeCritical = (remainingSeconds ?? 100) < 300; // Under 5 mins
  const activeQSaveStatus = currentQuestion ? saveStatuses[currentQuestion.exam_question_id] ?? 'idle' : 'idle';
  const activeQSaveError = currentQuestion ? saveErrors[currentQuestion.exam_question_id] : null;

  return (
    <div className="workspace-layout">
      {/* Workspace Top Bar */}
      <header className="workspace-header" role="banner">
        <div className="workspace-header__meta">
          <span className="workspace-badge">EXAM RUNTIME</span>
          <h1 className="workspace-title">{attempt.exam.title}</h1>
        </div>

        <div className="workspace-header__actions">
          {/* Timer Display */}
          <div
            className={`workspace-timer ${isTimeCritical ? 'workspace-timer--critical' : ''}`}
            role="timer"
            aria-live="polite"
            aria-atomic="true"
          >
            <Clock size={18} aria-hidden="true" />
            <div className="workspace-timer__text">
              <span className="workspace-timer__label">Time Remaining</span>
              <span className="workspace-timer__value">
                {remainingSeconds !== null ? formatTime(remainingSeconds) : '--:--'}
              </span>
            </div>
          </div>

          <button
            type="button"
            className="btn btn--primary"
            onClick={() => setShowSubmitModal(true)}
            disabled={inFlightSavesRef.current.size > 0}
          >
            <Send className="btn__icon" aria-hidden="true" /> Finish & Submit
          </button>
        </div>
      </header>

      {/* Main Workspace Body */}
      <div className="workspace-body">
        {/* Left Side: Question Pane */}
        <main className="workspace-question-pane" id="main-content">
          {currentQuestion ? (
            <div className="question-container">
              {/* Question Header & Status */}
              <div className="question-header">
                <div className="question-header__meta">
                  <span className="question-number">
                    Question {currentIndex + 1} of {totalQuestions}
                  </span>
                  <span className="question-marks">
                    {Number(currentQuestion.marks).toFixed(2)} marks
                  </span>
                </div>

                <div className="question-header__actions">
                  {/* Save Status Indicator */}
                  <div className="save-status-indicator" aria-live="polite">
                    {activeQSaveStatus === 'saving' && (
                      <span className="save-status save-status--saving">
                        <Loader2 size={13} className="spinner__icon" aria-hidden="true" /> Saving…
                      </span>
                    )}
                    {activeQSaveStatus === 'saved' && (
                      <span className="save-status save-status--saved">
                        <Check size={13} aria-hidden="true" /> Saved
                      </span>
                    )}
                    {activeQSaveStatus === 'failed' && (
                      <span className="save-status save-status--failed">
                        <AlertTriangle size={13} aria-hidden="true" /> Save failed
                      </span>
                    )}
                  </div>

                  {/* Review Flag Toggle */}
                  <button
                    type="button"
                    className={`btn-flag ${currentQuestion.answer.marked_for_review ? 'btn-flag--active' : ''}`}
                    onClick={handleToggleReview}
                    aria-pressed={currentQuestion.answer.marked_for_review}
                    title="Mark question for review before submitting"
                  >
                    <Bookmark size={15} aria-hidden="true" />
                    <span>{currentQuestion.answer.marked_for_review ? 'Marked for Review' : 'Mark for Review'}</span>
                  </button>
                </div>
              </div>

              {activeQSaveError && (
                <div className="inline-error" style={{ marginBottom: '1rem' }} role="alert">
                  <AlertCircle className="inline-error__icon" aria-hidden="true" />
                  <span>{activeQSaveError}</span>
                </div>
              )}

              {/* Question Prompt */}
              <div className="question-prompt">
                <p>{currentQuestion.prompt}</p>
              </div>

              {/* Radio Options */}
              <fieldset className="options-fieldset">
                <legend className="sr-only">Answer options for question {currentIndex + 1}</legend>
                <div className="options-list" role="radiogroup">
                  {currentQuestion.options.map((opt) => {
                    const isSelected = currentQuestion.answer.selected_option_id === opt.id;
                    const optionInputId = `opt-${currentQuestion.exam_question_id}-${opt.id}`;

                    return (
                      <label
                        key={opt.id}
                        htmlFor={optionInputId}
                        className={`option-card ${isSelected ? 'option-card--selected' : ''}`}
                      >
                        <input
                          type="radio"
                          id={optionInputId}
                          name={`q-${currentQuestion.exam_question_id}`}
                          value={opt.id}
                          checked={isSelected}
                          onChange={() => handleSelectOption(opt.id)}
                          className="option-radio"
                        />
                        <span className="option-indicator" aria-hidden="true">
                          {isSelected && <span className="option-indicator__dot" />}
                        </span>
                        <span className="option-text">{opt.text}</span>
                      </label>
                    );
                  })}
                </div>
              </fieldset>

              {/* Bottom Nav Between Questions */}
              <div className="question-nav-bar">
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={() => setCurrentIndex((prev) => Math.max(0, prev - 1))}
                  disabled={currentIndex === 0}
                >
                  <ChevronLeft className="btn__icon" aria-hidden="true" /> Previous
                </button>

                <span className="text-secondary font-medium" style={{ fontSize: '0.875rem' }}>
                  {currentIndex + 1} / {totalQuestions}
                </span>

                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={() => setCurrentIndex((prev) => Math.min(totalQuestions - 1, prev + 1))}
                  disabled={currentIndex === totalQuestions - 1}
                >
                  Next <ChevronRight className="btn__icon" aria-hidden="true" />
                </button>
              </div>
            </div>
          ) : (
            <div className="exam-card exam-card--empty">
              <HelpCircle className="exam-card__empty-icon" aria-hidden="true" />
              <h2>No questions found</h2>
              <p className="text-secondary">This examination does not contain any published questions.</p>
            </div>
          )}
        </main>

        {/* Right Side: Palette / Overview Sidebar */}
        <aside className="workspace-sidebar" aria-label="Question Navigator">
          <div className="sidebar-card">
            <h2 className="sidebar-title">Question Navigator</h2>

            {/* Accessible Legend */}
            <div className="palette-legend" aria-label="Status Legend">
              <div className="legend-item">
                <span className="legend-dot legend-dot--answered" aria-hidden="true">✓</span>
                <span>Answered ({answeredCount})</span>
              </div>
              <div className="legend-item">
                <span className="legend-dot legend-dot--unanswered" aria-hidden="true">•</span>
                <span>Unanswered ({unansweredCount})</span>
              </div>
              <div className="legend-item">
                <span className="legend-dot legend-dot--flagged" aria-hidden="true">⚑</span>
                <span>Flagged ({flaggedCount})</span>
              </div>
            </div>

            {/* Grid Palette */}
            <nav className="palette-grid" aria-label="Questions list">
              {questions.map((q, idx) => {
                const isCurrent = idx === currentIndex;
                const isAnswered = q.answer.selected_option_id !== null;
                const isFlagged = q.answer.marked_for_review;

                return (
                  <button
                    key={q.exam_question_id}
                    type="button"
                    onClick={() => setCurrentIndex(idx)}
                    className={`palette-btn ${
                      isCurrent ? 'palette-btn--current' : ''
                    } ${isAnswered ? 'palette-btn--answered' : 'palette-btn--unanswered'} ${
                      isFlagged ? 'palette-btn--flagged' : ''
                    }`}
                    aria-current={isCurrent ? 'step' : undefined}
                    aria-label={`Question ${idx + 1}: ${
                      isAnswered ? 'Answered' : 'Unanswered'
                    }${isFlagged ? ', Flagged for review' : ''}`}
                  >
                    <span className="palette-btn__num">{idx + 1}</span>
                    {isFlagged && <span className="palette-btn__flag" aria-hidden="true">⚑</span>}
                    {isAnswered && !isFlagged && <span className="palette-btn__check" aria-hidden="true">✓</span>}
                  </button>
                );
              })}
            </nav>

            <div className="sidebar-summary">
              <div className="sidebar-summary__item">
                <span className="text-secondary">Completed</span>
                <span className="font-semibold text-text">
                  {Math.round((answeredCount / (totalQuestions || 1)) * 100)}%
                </span>
              </div>
            </div>
          </div>
        </aside>
      </div>

      {/* Submit Confirmation Dialog Modal */}
      {showSubmitModal && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="modal-title">
          <div className="modal-content">
            <div className="modal-header">
              <div className="modal-header__title-row">
                <CheckCircle className="text-accent" size={24} aria-hidden="true" />
                <h2 id="modal-title" className="modal-title">
                  Submit Examination?
                </h2>
              </div>
              <button
                type="button"
                className="btn-icon"
                onClick={() => setShowSubmitModal(false)}
                disabled={isSubmitting}
                aria-label="Close dialog"
              >
                <X size={18} aria-hidden="true" />
              </button>
            </div>

            <div className="modal-body">
              <p className="text-secondary" style={{ marginBottom: '1.25rem' }}>
                Once submitted, your examination attempt will be finalized and your answers cannot be changed.
              </p>

              <div className="submit-stats-box">
                <div className="submit-stat">
                  <span className="submit-stat__num text-success">{answeredCount}</span>
                  <span className="submit-stat__label">Answered</span>
                </div>
                <div className="submit-stat">
                  <span className="submit-stat__num text-error">{unansweredCount}</span>
                  <span className="submit-stat__label">Unanswered</span>
                </div>
                <div className="submit-stat">
                  <span className="submit-stat__num text-accent">{flaggedCount}</span>
                  <span className="submit-stat__label">Marked for Review</span>
                </div>
              </div>

              {unansweredCount > 0 && (
                <div className="inline-warning" style={{ marginTop: '1rem' }}>
                  <AlertTriangle size={16} aria-hidden="true" />
                  <span>
                    You have <strong>{unansweredCount}</strong> unanswered questions. Unanswered questions will receive 0 marks.
                  </span>
                </div>
              )}

              {submitError && (
                <div className="inline-error" style={{ marginTop: '1rem' }} role="alert">
                  <AlertCircle className="inline-error__icon" aria-hidden="true" />
                  <span>{submitError}</span>
                </div>
              )}
            </div>

            <div className="modal-footer">
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => setShowSubmitModal(false)}
                disabled={isSubmitting}
              >
                Continue Exam
              </button>
              <button
                type="button"
                className="btn btn--primary"
                onClick={handleSubmit}
                disabled={isSubmitting}
                aria-busy={isSubmitting}
              >
                {isSubmitting ? (
                  <>
                    <LoadingSpinner size="sm" /> Submitting…
                  </>
                ) : (
                  'Confirm & Finalize'
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
