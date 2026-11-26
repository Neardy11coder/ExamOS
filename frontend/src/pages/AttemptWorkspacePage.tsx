/**
 * Active Examination Workspace — /attempts/:attemptId (M1-STUD-UI-1).
 *
 * Responsibilities:
 * - Loads authoritative attempt state via GET /api/v1/attempts/{attempt_id}.
 * - Renders exam metadata, numbered question navigation palette, and question prompt.
 * - Handles question selection without exposing correctness keys.
 * - Manages answer autosave via AttemptAutosaveManager (per-question serialized queue,
 *   300 ms debounce, optimistic UI vs server-confirmed state separation, safe 409 & failure reconciliation).
 * - Displays per-question save indicators: 'pending', 'saving', 'saved', 'failed', 'conflict'.
 * - Displays non-colour question palette status: Current (bold/indicator), Answered (✓), Unanswered (•), Review (⚑).
 * - Implements countdown timer based on server remaining_seconds and deadline_at.
 * - On 0 countdown, auto-triggers authoritative refresh, locking workspace if status transitions to EXPIRED.
 * - Handles optimistic concurrency (409 ANSWER_REVISION_CONFLICT) by preserving user intent and offering explicit resolution.
 * - Provides submit confirmation modal with counts of answered/unanswered/flagged questions and flushes pending saves.
 * - Submits via POST /api/v1/attempts/{attempt_id}/submit and redirects to /attempts/{attempt_id}/result.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useBlocker, useNavigate, useParams } from 'react-router-dom';
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
  RotateCcw,
  Send,
  X,
} from 'lucide-react';
import {
  apiGetAttempt,
  apiSaveAnswer,
  apiSubmitAttempt,
  type AttemptDetailRead,
  type StudentQuestionRead,
} from '../api/attempts';
import {
  AttemptAutosaveManager,
  type QuestionAutosaveView,
  type QuestionSaveStatus,
} from '../features/attempt/autosaveManager';
import {
  AttemptLoadCoordinator,
  executeAttemptSubmission,
  flushAttemptBeforeNavigation,
} from '../features/attempt/attemptLifecycleController';
import {
  AttemptCountdownController,
  type CountdownRefreshError,
} from '../features/attempt/countdownController';
import { useAuth } from '../contexts/AuthContext';
import { LoadingSpinner } from '../components/ui';

export function AttemptWorkspacePage() {
  const { attemptId } = useParams<{ attemptId: string }>();
  const { csrfToken } = useAuth();
  const navigate = useNavigate();

  const [attempt, setAttempt] = useState<AttemptDetailRead | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Active question index
  const [currentIndex, setCurrentIndex] = useState(0);

  // Per-question autosave view state (optimistic local state, server state, status, conflict details)
  const [autosaveViews, setAutosaveViews] = useState<Record<string, QuestionAutosaveView>>({});

  // Countdown seconds remaining and terminal refresh failures that need user action.
  const [remainingSeconds, setRemainingSeconds] = useState<number | null>(null);
  const [countdownRefreshError, setCountdownRefreshError] =
    useState<CountdownRefreshError | null>(null);

  // Submit modal
  const [showSubmitModal, setShowSubmitModal] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [navigationSaveError, setNavigationSaveError] = useState<string | null>(null);
  const submittingRef = useRef(false);
  const workspaceLockedRef = useRef(false);
  const navigationBypassRef = useRef(false);
  const navigationFlushInProgressRef = useRef(false);
  const workspaceHeaderRef = useRef<HTMLElement | null>(null);
  const workspaceBodyRef = useRef<HTMLDivElement | null>(null);
  const submitDialogRef = useRef<HTMLDivElement | null>(null);

  // Keep fresh references for async callbacks & timers
  const csrfTokenRef = useRef<string | null>(csrfToken);
  csrfTokenRef.current = csrfToken;

  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;

  const isMountedRef = useRef(false);
  const hasInitializedRouteRef = useRef(false);
  const attemptRef = useRef<AttemptDetailRead | null>(null);
  attemptRef.current = attempt;

  const loadCoordinatorRef = useRef<AttemptLoadCoordinator | null>(null);
  const autosaveManagerRef = useRef<AttemptAutosaveManager | null>(null);
  const countdownControllerRef = useRef<AttemptCountdownController | null>(null);

  const setWorkspaceLocked = (locked: boolean) => {
    workspaceLockedRef.current = locked;
    autosaveManagerRef.current?.setInputLocked(locked);
  };

  const loadAttemptRef = useRef<
    (
      isInitial?: boolean,
      options?: { throwOnBackgroundError?: boolean },
    ) => Promise<AttemptDetailRead | null>
  >(async () => null);

  const createAutosaveManager = useCallback(
    () =>
      new AttemptAutosaveManager({
        saveAnswer: (attId, qId, payload) =>
          apiSaveAnswer(attId, qId, payload, csrfTokenRef.current),
        getAttempt: (attId) => apiGetAttempt(attId),
        onAttemptTerminated: () => {
          if (loadCoordinatorRef.current?.isCurrentSession()) {
            void loadAttemptRef.current(false);
          }
        },
        onStateChange: (views) => {
          setAutosaveViews(views);
        },
      }),
    [],
  );

  if (!autosaveManagerRef.current) {
    autosaveManagerRef.current = createAutosaveManager();
  }

  if (!countdownControllerRef.current) {
    countdownControllerRef.current = new AttemptCountdownController({
      refreshAttempt: () =>
        loadAttemptRef.current(false, { throwOnBackgroundError: true }),
      onRemainingSecondsChange: (secs) => {
        if (isMountedRef.current) {
          setRemainingSeconds(secs);
        }
      },
      onRefreshError: (error) => {
        if (isMountedRef.current) {
          setCountdownRefreshError(error);
        }
      },
      onTerminalAttempt: (terminalAttempt) => {
        if (!isMountedRef.current) return;
        autosaveManagerRef.current?.dispose();
        setAttempt(terminalAttempt);
        setRemainingSeconds(0);
        navigationBypassRef.current = true;
        navigateRef.current(`/attempts/${terminalAttempt.attempt_id}/result`, {
          replace: true,
        });
      },
    });
  }

  if (!loadCoordinatorRef.current) {
    loadCoordinatorRef.current = new AttemptLoadCoordinator({
      getAttempt: (attId) => apiGetAttempt(attId),
      hasLoadedAttempt: () => attemptRef.current !== null,
      onLoadingChange: setIsLoading,
      onLoadError: setLoadError,
      onHydrateActiveAttempt: (data) => {
        autosaveManagerRef.current?.hydrateFromAttempt(data);
        setAttempt(data);
        countdownControllerRef.current?.syncFromAttempt(data);
      },
      onSyncTerminalAttempt: (data) => {
        countdownControllerRef.current?.syncFromAttempt(data);
      },
    });
  }

  // -------------------------------------------------------------------------
  // 1. Authoritative Attempt Loader & Route Lifecycle Management
  // -------------------------------------------------------------------------
  const loadAttempt = useCallback(
    (
      isInitial = false,
      options?: { throwOnBackgroundError?: boolean },
    ): Promise<AttemptDetailRead | null> =>
      loadCoordinatorRef.current!.loadAttempt(attemptId, isInitial, options),
    [attemptId],
  );

  loadAttemptRef.current = loadAttempt;

  useEffect(() => {
    const coordinator = loadCoordinatorRef.current!;
    const countdownController = countdownControllerRef.current!;

    isMountedRef.current = true;
    const { routeChanged } = coordinator.activateRoute(attemptId);

    if (!hasInitializedRouteRef.current) {
      hasInitializedRouteRef.current = true;
    } else if (routeChanged) {
      // Switching to a different attempt route: replace autosaveManager so any
      // in-flight writes from the previous attempt remain permanently disposed,
      // and clear previous attempt UI state before loading the new attempt.
      autosaveManagerRef.current = createAutosaveManager();
      attemptRef.current = null;
      setAttempt(null);
      setLoadError(null);
      setCurrentIndex(0);
      setAutosaveViews({});
      setRemainingSeconds(null);
      setCountdownRefreshError(null);
      setShowSubmitModal(false);
      setIsSubmitting(false);
      submittingRef.current = false;
      workspaceLockedRef.current = false;
      navigationBypassRef.current = false;
      navigationFlushInProgressRef.current = false;
      setSubmitError(null);
      setNavigationSaveError(null);
      setIsLoading(true);
    }

    const activeAutosaveManager = autosaveManagerRef.current!;
    activeAutosaveManager.activate();
    countdownController.activate();
    void loadAttempt(true);

    return () => {
      isMountedRef.current = false;
      coordinator.deactivate();
      autosaveManagerRef.current?.dispose();
      countdownController.dispose();
    };
  }, [attemptId, createAutosaveManager, loadAttempt]);

  // Block SPA route changes while an active attempt has unacknowledged answers.
  const navigationBlocker = useBlocker(({ currentLocation, nextLocation }) => {
    const locationChanges =
      currentLocation.pathname !== nextLocation.pathname ||
      currentLocation.search !== nextLocation.search ||
      currentLocation.hash !== nextLocation.hash;
    if (!locationChanges || navigationBypassRef.current) return false;
    if (submittingRef.current) return true;
    if (attemptRef.current?.status !== 'IN_PROGRESS') return false;

    const manager = autosaveManagerRef.current;
    if (!manager?.hasUnacknowledgedChanges()) return false;

    // Lock synchronously in the blocker callback so no new answer can slip in
    // between the route transition and the asynchronous flush effect.
    setWorkspaceLocked(true);
    return true;
  });
  const navigationBlockerRef = useRef(navigationBlocker);
  navigationBlockerRef.current = navigationBlocker;
  const navigationBlockerState = navigationBlocker.state;

  useEffect(() => {
    if (navigationBlockerState !== 'blocked') {
      navigationFlushInProgressRef.current = false;
      return;
    }
    if (navigationFlushInProgressRef.current) return;

    const activeBlocker = navigationBlockerRef.current;
    if (submittingRef.current) {
      setNavigationSaveError(
        'Navigation was stopped because submission is in progress. Stay on this page until the submission finishes.',
      );
      if (activeBlocker.state === 'blocked') activeBlocker.reset();
      return;
    }

    const manager = autosaveManagerRef.current;
    if (!manager) {
      if (activeBlocker.state === 'blocked') activeBlocker.reset();
      return;
    }

    navigationFlushInProgressRef.current = true;
    let effectActive = true;

    void flushAttemptBeforeNavigation(manager)
      .then((result) => {
        if (!effectActive) return;
        const currentBlocker = navigationBlockerRef.current;
        if (currentBlocker.state !== 'blocked') return;

        if (result.ok || result.terminated) {
          currentBlocker.proceed();
          return;
        }

        const issues: string[] = [];
        if (result.failedQuestionIds.length > 0) {
          issues.push(`${result.failedQuestionIds.length} failed save(s)`);
        }
        if (result.conflictQuestionIds.length > 0) {
          issues.push(`${result.conflictQuestionIds.length} conflict(s)`);
        }
        if ((result.pendingQuestionIds?.length ?? 0) > 0) {
          issues.push(`${result.pendingQuestionIds!.length} unsettled save(s)`);
        }
        setNavigationSaveError(
          `Navigation was stopped because ${issues.join(' and ') || 'some answers'} could not be confirmed on the server. Retry or resolve the save issue, then navigate again. Your exam remains open.`,
        );
        setWorkspaceLocked(false);
        currentBlocker.reset();
      })
      .catch((error: unknown) => {
        if (!effectActive) return;
        setWorkspaceLocked(false);
        const currentBlocker = navigationBlockerRef.current;
        if (currentBlocker.state === 'blocked') {
          const detail = error instanceof Error ? error.message : 'Unknown save error.';
          setNavigationSaveError(
            `Navigation was stopped because pending answers could not be saved (${detail}). Retry the save before leaving.`,
          );
          currentBlocker.reset();
        }
      })
      .finally(() => {
        navigationFlushInProgressRef.current = false;
      });

    return () => {
      effectActive = false;
    };
  }, [navigationBlockerState]);

  // Warn before unloading tab/window if unacknowledged changes exist
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      const manager = autosaveManagerRef.current;
      if (
        attempt?.status === 'IN_PROGRESS' &&
        manager &&
        manager.hasUnacknowledgedChanges()
      ) {
        void manager.flushBeforeSubmit();
        e.preventDefault();
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [attempt?.status]);

  useEffect(() => {
    const backgroundNodes = [workspaceHeaderRef.current, workspaceBodyRef.current];
    for (const node of backgroundNodes) {
      if (!node) continue;
      if (showSubmitModal) {
        node.setAttribute('inert', '');
        node.setAttribute('aria-hidden', 'true');
      } else {
        node.removeAttribute('inert');
        node.removeAttribute('aria-hidden');
      }
    }
  }, [showSubmitModal]);

  useEffect(() => {
    if (!showSubmitModal) return;

    const previouslyFocused =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = submitDialogRef.current;
    const focusableSelector =
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';
    const getFocusable = () =>
      dialog
        ? Array.from(dialog.querySelectorAll<HTMLElement>(focusableSelector))
        : [];

    const firstFocusable = getFocusable()[0];
    (firstFocusable ?? dialog)?.focus();

    const handleDialogKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        if (!submittingRef.current) handleCloseSubmitModal();
        return;
      }
      if (event.key !== 'Tab') return;

      const focusable = getFocusable();
      if (focusable.length === 0) {
        event.preventDefault();
        dialog?.focus();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleDialogKeyDown);
    return () => {
      document.removeEventListener('keydown', handleDialogKeyDown);
      if (previouslyFocused?.isConnected) previouslyFocused.focus();
    };
  }, [showSubmitModal]);

  // -------------------------------------------------------------------------
  // 3. Question Navigation & Computed Stats
  // -------------------------------------------------------------------------
  const questions: StudentQuestionRead[] = useMemo(() => {
    const rawQuestions = attempt?.questions ?? [];
    return rawQuestions.map((q) => {
      const view = autosaveViews[q.exam_question_id];
      if (!view) return q;
      return {
        ...q,
        answer: {
          selected_option_id: view.local.selected_option_id,
          marked_for_review: view.local.marked_for_review,
          revision: view.server.revision,
        },
      };
    });
  }, [attempt, autosaveViews]);

  const currentQuestion: StudentQuestionRead | undefined = questions[currentIndex];

  const totalQuestions = questions.length;
  const answeredCount = questions.filter((q) => q.answer.selected_option_id !== null).length;
  const flaggedCount = questions.filter((q) => q.answer.marked_for_review).length;
  const unansweredCount = totalQuestions - answeredCount;

  const saveSummary = useMemo(() => {
    let pending = 0;
    let saving = 0;
    let failed = 0;
    let conflict = 0;
    const unresolvedQuestions: Array<{
      index: number;
      questionId: string;
      status: 'failed' | 'conflict';
    }> = [];

    questions.forEach((q, index) => {
      const status = autosaveViews[q.exam_question_id]?.status ?? 'idle';
      if (status === 'pending') pending += 1;
      else if (status === 'saving') saving += 1;
      else if (status === 'failed') {
        failed += 1;
        unresolvedQuestions.push({
          index,
          questionId: q.exam_question_id,
          status: 'failed',
        });
      } else if (status === 'conflict') {
        conflict += 1;
        unresolvedQuestions.push({
          index,
          questionId: q.exam_question_id,
          status: 'conflict',
        });
      }
    });

    return {
      pending,
      saving,
      failed,
      conflict,
      unacknowledged: pending + saving + failed + conflict,
      unresolvedQuestions,
    };
  }, [questions, autosaveViews]);

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
  // 4. Durable Answer Saving & Navigation Flushing
  // -------------------------------------------------------------------------
  const navigateToQuestion = (nextIndex: number) => {
    if (workspaceLockedRef.current || nextIndex === currentIndex) return;
    if (currentQuestion && attempt?.status === 'IN_PROGRESS') {
      void autosaveManagerRef.current?.flushQuestion(currentQuestion.exam_question_id);
    }
    setCurrentIndex(nextIndex);
  };

  const handleSelectOption = (optionId: string) => {
    if (workspaceLockedRef.current || !currentQuestion || attempt?.status !== 'IN_PROGRESS') return;
    autosaveManagerRef.current?.selectOption(currentQuestion.exam_question_id, optionId);
  };

  const handleToggleReview = () => {
    if (workspaceLockedRef.current || !currentQuestion || attempt?.status !== 'IN_PROGRESS') return;
    autosaveManagerRef.current?.toggleReview(currentQuestion.exam_question_id);
  };

  const handleRetrySave = (qId: string) => {
    if (workspaceLockedRef.current || attempt?.status !== 'IN_PROGRESS') return;
    void autosaveManagerRef.current?.retryQuestion(qId);
  };

  const handleResolveConflictLocal = (qId: string) => {
    if (workspaceLockedRef.current || attempt?.status !== 'IN_PROGRESS') return;
    void autosaveManagerRef.current?.resolveConflictWithLocal(qId);
  };

  const handleResolveConflictServer = (qId: string) => {
    if (workspaceLockedRef.current || attempt?.status !== 'IN_PROGRESS') return;
    autosaveManagerRef.current?.resolveConflictWithServer(qId);
  };

  // -------------------------------------------------------------------------
  // 5. Final Submission
  // -------------------------------------------------------------------------
  const handleOpenSubmitModal = () => {
    if (workspaceLockedRef.current || attempt?.status !== 'IN_PROGRESS') return;
    setWorkspaceLocked(true);
    setSubmitError(null);
    setShowSubmitModal(true);
    void autosaveManagerRef.current?.flushPendingWrites();
  };

  const handleCloseSubmitModal = () => {
    if (submittingRef.current) return;
    setWorkspaceLocked(false);
    setShowSubmitModal(false);
  };

  const handleSubmit = async () => {
    const manager = autosaveManagerRef.current;
    const coordinator = loadCoordinatorRef.current;
    if (!manager || !coordinator || submittingRef.current || !coordinator.isCurrentSession()) return;

    // The ref closes the double-click window before React commits state updates.
    submittingRef.current = true;
    setWorkspaceLocked(true);
    const sessionToken = coordinator.captureSession();
    await executeAttemptSubmission({
      attemptId,
      isSubmitting: false,
      isCurrentSession: () => coordinator.isSessionActive(sessionToken),
      flushBeforeSubmit: () => manager.flushBeforeSubmit(),
      refreshAttempt: () =>
        coordinator.loadAttempt(attemptId, false, {
          throwOnBackgroundError: true,
        }),
      submitAttempt: (id) => apiSubmitAttempt(id, {}, csrfTokenRef.current),
      onSubmittingChange: (value) => {
        submittingRef.current = value;
        setIsSubmitting(value);
      },
      onSubmitError: setSubmitError,
      onModalOpenChange: (open) => {
        setShowSubmitModal(open);
        if (!open) setWorkspaceLocked(false);
      },
      onSubmissionSuccess: (id) => {
        countdownControllerRef.current?.dispose();
        manager.dispose();
        navigationBypassRef.current = true;
        navigateRef.current(`/attempts/${id}/result`, { replace: true });
      },
    });
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
  const activeQView = currentQuestion ? autosaveViews[currentQuestion.exam_question_id] : undefined;
  const activeQSaveStatus: QuestionSaveStatus = activeQView?.status ?? 'idle';
  const activeQSaveError = activeQView?.errorMessage ?? null;
  const activeQConflictServer = activeQView?.conflictServerState ?? null;
  const serverConflictOptionText =
    activeQConflictServer && currentQuestion
      ? activeQConflictServer.selected_option_id === null
        ? 'Unanswered'
        : currentQuestion.options.find((o) => o.id === activeQConflictServer.selected_option_id)
            ?.text ?? 'Unknown option'
      : null;

  return (
    <div className="workspace-layout">
      {/* Workspace Top Bar */}
      <header
        ref={workspaceHeaderRef}
        className="workspace-header"
        role="banner"
      >
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
            onClick={handleOpenSubmitModal}
            disabled={isSubmitting}
          >
            <Send className="btn__icon" aria-hidden="true" /> Finish & Submit
          </button>
        </div>
      </header>

      {/* Main Workspace Body */}
      <div ref={workspaceBodyRef} className="workspace-body">
        {/* Left Side: Question Pane */}
        <main className="workspace-question-pane" id="main-content">
          {countdownRefreshError && (
            <div
              className="inline-error workspace-save-alert"
              role="alert"
              aria-live="assertive"
            >
              <AlertCircle className="inline-error__icon" aria-hidden="true" />
              <div style={{ flex: 1 }}>
                <p style={{ margin: 0 }}>{countdownRefreshError.message}</p>
                <div className="save-banner-actions">
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    onClick={() => void countdownControllerRef.current?.triggerRefresh()}
                  >
                    <RotateCcw size={13} aria-hidden="true" /> Retry status check
                  </button>
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    onClick={() => navigateRef.current('/exams/available')}
                  >
                    Return to Available Exams
                  </button>
                </div>
              </div>
            </div>
          )}

          {navigationSaveError && (
            <div className="inline-warning workspace-save-alert" role="alert">
              <AlertTriangle size={18} style={{ flexShrink: 0 }} aria-hidden="true" />
              <div style={{ flex: 1 }}>
                <span>{navigationSaveError}</span>
                <div className="save-banner-actions">
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    onClick={() => setNavigationSaveError(null)}
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            </div>
          )}

          {(saveSummary.failed > 0 || saveSummary.conflict > 0) && (
            <div
              className={saveSummary.failed > 0 ? 'inline-error workspace-save-alert' : 'inline-warning workspace-save-alert'}
              role="status"
              aria-live="polite"
            >
              <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: '0.125rem' }} aria-hidden="true" />
              <div style={{ flex: 1 }}>
                <span>
                  Unresolved save issues across your exam:{' '}
                  {saveSummary.failed > 0 && <strong>{saveSummary.failed} failed</strong>}
                  {saveSummary.failed > 0 && saveSummary.conflict > 0 && ', '}
                  {saveSummary.conflict > 0 && <strong>{saveSummary.conflict} conflict(s)</strong>}.
                </span>
                <div className="save-banner-actions">
                  {saveSummary.unresolvedQuestions.map((item) => (
                    <button
                      key={item.questionId}
                      type="button"
                      className="btn btn--ghost btn--sm"
                      onClick={() => navigateToQuestion(item.index)}
                    >
                      Q{item.index + 1} ({item.status === 'failed' ? 'Failed' : 'Conflict'})
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

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
                    {activeQSaveStatus === 'pending' && (
                      <span className="save-status save-status--pending">
                        <Clock size={13} aria-hidden="true" /> Pending save…
                      </span>
                    )}
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
                      <span className="save-status-actions">
                        <span className="save-status save-status--failed">
                          <AlertTriangle size={13} aria-hidden="true" /> Save failed
                        </span>
                        <button
                          type="button"
                          className="btn btn--ghost btn--sm"
                          onClick={() => handleRetrySave(currentQuestion.exam_question_id)}
                        >
                          <RotateCcw size={12} aria-hidden="true" /> Retry
                        </button>
                      </span>
                    )}
                    {activeQSaveStatus === 'conflict' && (
                      <span className="save-status save-status--conflict">
                        <AlertTriangle size={13} aria-hidden="true" /> Conflict
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

              {activeQSaveStatus === 'failed' && activeQSaveError && (
                <div className="inline-error" style={{ marginBottom: '1rem' }} role="alert">
                  <AlertCircle className="inline-error__icon" aria-hidden="true" />
                  <div style={{ flex: 1 }}>
                    <span>{activeQSaveError}</span>
                    <div className="save-banner-actions">
                      <button
                        type="button"
                        className="btn btn--ghost btn--sm"
                        onClick={() => handleRetrySave(currentQuestion.exam_question_id)}
                      >
                        <RotateCcw size={13} aria-hidden="true" /> Retry Save
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {activeQSaveStatus === 'conflict' && activeQConflictServer && (
                <div className="inline-warning" style={{ marginBottom: '1rem', alignItems: 'flex-start' }} role="alert">
                  <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: '0.125rem' }} aria-hidden="true" />
                  <div style={{ flex: 1 }}>
                    <p style={{ margin: 0 }}>
                      {activeQSaveError ??
                        'Another session modified this question on the server. Your unsaved selection is preserved.'}
                    </p>
                    <p style={{ margin: '0.35rem 0 0', fontSize: '0.8125rem' }}>
                      Server answer (rev {activeQConflictServer.revision}):{' '}
                      <strong>{serverConflictOptionText}</strong>
                      {activeQConflictServer.marked_for_review ? ' · Marked for review' : ''}
                    </p>
                    <div className="save-banner-actions">
                      <button
                        type="button"
                        className="btn btn--primary btn--sm"
                        onClick={() => handleResolveConflictLocal(currentQuestion.exam_question_id)}
                      >
                        Save My Selection
                      </button>
                      <button
                        type="button"
                        className="btn btn--ghost btn--sm"
                        onClick={() => handleResolveConflictServer(currentQuestion.exam_question_id)}
                      >
                        Use Server Answer
                      </button>
                    </div>
                  </div>
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
                  onClick={() => navigateToQuestion(Math.max(0, currentIndex - 1))}
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
                  onClick={() => navigateToQuestion(Math.min(totalQuestions - 1, currentIndex + 1))}
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
                const qSaveStatus = autosaveViews[q.exam_question_id]?.status ?? 'idle';
                const hasFailed = qSaveStatus === 'failed';
                const hasConflict = qSaveStatus === 'conflict';

                return (
                  <button
                    key={q.exam_question_id}
                    type="button"
                    onClick={() => navigateToQuestion(idx)}
                    className={`palette-btn ${
                      isCurrent ? 'palette-btn--current' : ''
                    } ${isAnswered ? 'palette-btn--answered' : 'palette-btn--unanswered'} ${
                      isFlagged ? 'palette-btn--flagged' : ''
                    } ${hasFailed ? 'palette-btn--failed' : ''} ${
                      hasConflict ? 'palette-btn--conflict' : ''
                    }`}
                    aria-current={isCurrent ? 'step' : undefined}
                    aria-label={`Question ${idx + 1}: ${
                      isAnswered ? 'Answered' : 'Unanswered'
                    }${isFlagged ? ', Flagged for review' : ''}${
                      hasFailed ? ', Save failed' : hasConflict ? ', Save conflict' : ''
                    }`}
                  >
                    <span className="palette-btn__num">{idx + 1}</span>
                    {(hasFailed || hasConflict) && (
                      <span className="palette-btn__issue" aria-hidden="true">!</span>
                    )}
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
          <div ref={submitDialogRef} className="modal-content" tabIndex={-1}>
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
                onClick={handleCloseSubmitModal}
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

              {saveSummary.unacknowledged > 0 && (
                <div className="inline-warning" style={{ marginTop: '1rem' }} role="status">
                  <AlertTriangle size={16} aria-hidden="true" />
                  <span>
                    {saveSummary.failed > 0 || saveSummary.conflict > 0 ? (
                      <>
                        You have <strong>{saveSummary.failed}</strong> failed save(s) and{' '}
                        <strong>{saveSummary.conflict}</strong> conflict(s). Scoring uses only server-saved answers.
                      </>
                    ) : (
                      <>
                        Saving <strong>{saveSummary.pending + saveSummary.saving}</strong> pending answer change(s)…
                      </>
                    )}
                  </span>
                </div>
              )}

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
                onClick={handleCloseSubmitModal}
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
