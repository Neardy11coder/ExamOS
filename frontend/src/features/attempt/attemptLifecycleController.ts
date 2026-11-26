/**
 * Route-safe attempt loading and submission lifecycle helpers for AttemptWorkspacePage.
 *
 * Guarantees:
 * - Delayed GET /attempts/{id} responses (or rejections) for Attempt A never mutate
 *   state, hydrate autosave, sync countdown, or clear in-flight tracking after the
 *   active route changes to Attempt B or the workspace unmounts.
 * - Preserves inFlightLoad deduplication per (attemptId, routeGeneration) across
 *   concurrent triggers and React StrictMode mount -> cleanup -> remount cycles.
 * - Ensures handleSubmit() always recovers isSubmitting and displays a clear,
 *   recoverable error if flushBeforeSubmit() detects termination and the follow-up
 *   refresh fails or returns null, without discarding unresolved changes or conflating
 *   expiration with submission.
 */

import { type AttemptDetailRead } from '../../api/attempts';
import { type AttemptAutosaveManager, type AutosaveFlushResult } from './autosaveManager';

export interface AttemptLoadCoordinatorDeps {
  getAttempt: (attemptId: string) => Promise<AttemptDetailRead>;
  hasLoadedAttempt: () => boolean;
  onLoadingChange: (isLoading: boolean) => void;
  onLoadError: (message: string | null) => void;
  onHydrateActiveAttempt: (attempt: AttemptDetailRead) => void;
  onSyncTerminalAttempt: (attempt: AttemptDetailRead) => void;
}

export interface LoadAttemptOptions {
  throwOnBackgroundError?: boolean;
}

export interface SessionToken {
  attemptId: string | undefined;
  generation: number;
}

export class AttemptLoadCoordinator {
  private mounted = false;
  private activeAttemptId: string | undefined = undefined;
  private routeGeneration = 0;
  private inFlightLoad: {
    attemptId: string;
    generation: number;
    promise: Promise<AttemptDetailRead | null>;
  } | null = null;

  private readonly deps: AttemptLoadCoordinatorDeps;

  constructor(deps: AttemptLoadCoordinatorDeps) {
    this.deps = deps;
  }

  /**
   * Marks the workspace active for `attemptId`. Advances `routeGeneration` and
   * detaches any previous in-flight load whenever the route attemptId changes,
   * while preserving deduplication across React StrictMode remounts for the
   * same attemptId.
   */
  activateRoute(attemptId: string | undefined): { routeChanged: boolean } {
    this.mounted = true;
    const routeChanged = this.activeAttemptId !== attemptId;
    if (routeChanged) {
      this.activeAttemptId = attemptId;
      this.routeGeneration += 1;
      this.inFlightLoad = null;
    }
    return { routeChanged };
  }

  /** Marks the workspace unmounted/inactive so pending responses are ignored. */
  deactivate(): void {
    this.mounted = false;
  }

  captureSession(): SessionToken {
    return {
      attemptId: this.activeAttemptId,
      generation: this.routeGeneration,
    };
  }

  isCurrentSession(): boolean {
    return this.mounted && this.activeAttemptId !== undefined;
  }

  isSessionActive(token: SessionToken): boolean {
    return (
      this.mounted &&
      token.attemptId !== undefined &&
      this.activeAttemptId === token.attemptId &&
      this.routeGeneration === token.generation
    );
  }

  private isCurrentRequest(attemptId: string, generation: number): boolean {
    return (
      this.mounted &&
      this.activeAttemptId === attemptId &&
      this.routeGeneration === generation
    );
  }

  async loadAttempt(
    attemptId: string | undefined,
    isInitial = false,
    options?: LoadAttemptOptions,
  ): Promise<AttemptDetailRead | null> {
    if (!attemptId) return null;

    const generation = this.routeGeneration;
    if (!this.isCurrentRequest(attemptId, generation)) {
      return null;
    }

    if (isInitial) {
      this.deps.onLoadingChange(true);
    }

    const existing = this.inFlightLoad;
    if (
      existing &&
      existing.attemptId === attemptId &&
      existing.generation === generation
    ) {
      try {
        const data = await existing.promise;
        if (!this.isCurrentRequest(attemptId, generation)) {
          return null;
        }
        return data;
      } catch (err: unknown) {
        if (
          options?.throwOnBackgroundError &&
          this.isCurrentRequest(attemptId, generation) &&
          this.deps.hasLoadedAttempt()
        ) {
          throw err;
        }
        return null;
      } finally {
        if (isInitial && this.isCurrentRequest(attemptId, generation)) {
          this.deps.onLoadingChange(false);
        }
      }
    }

    const requestPromise = (async (): Promise<AttemptDetailRead | null> => {
      const data = await this.deps.getAttempt(attemptId);
      if (!this.isCurrentRequest(attemptId, generation)) {
        return null;
      }

      if (data.status === 'SUBMITTED' || data.status === 'EXPIRED') {
        this.deps.onSyncTerminalAttempt(data);
        return data;
      }

      this.deps.onHydrateActiveAttempt(data);
      return data;
    })();

    this.inFlightLoad = { attemptId, generation, promise: requestPromise };

    try {
      return await requestPromise;
    } catch (err: unknown) {
      if (!this.isCurrentRequest(attemptId, generation)) {
        return null;
      }
      if (isInitial || !this.deps.hasLoadedAttempt()) {
        const msg = err instanceof Error ? err.message : 'Failed to load attempt.';
        this.deps.onLoadError(msg);
      }
      if (options?.throwOnBackgroundError && this.deps.hasLoadedAttempt()) {
        throw err;
      }
      return null;
    } finally {
      if (this.inFlightLoad?.promise === requestPromise) {
        this.inFlightLoad = null;
      }
      if (isInitial && this.isCurrentRequest(attemptId, generation)) {
        this.deps.onLoadingChange(false);
      }
    }
  }
}

/**
 * Locks answer mutations before leaving an active attempt, then waits for all
 * pending writes. The caller may proceed only when every write is acknowledged.
 * On failure, input is unlocked so the student can retry or resolve conflicts.
 */
export async function flushAttemptBeforeNavigation(
  manager: AttemptAutosaveManager,
): Promise<AutosaveFlushResult> {
  manager.setInputLocked(true);
  try {
    const result = await manager.flushPendingWrites();
    if (!result.ok) manager.setInputLocked(false);
    return result;
  } catch (error: unknown) {
    manager.setInputLocked(false);
    throw error;
  }
}

export interface AttemptSubmissionDeps {
  attemptId: string | undefined;
  isSubmitting: boolean;
  isCurrentSession: () => boolean;
  flushBeforeSubmit: () => Promise<AutosaveFlushResult>;
  refreshAttempt: () => Promise<AttemptDetailRead | null>;
  submitAttempt: (attemptId: string) => Promise<unknown>;
  onSubmittingChange: (isSubmitting: boolean) => void;
  onSubmitError: (message: string | null) => void;
  onModalOpenChange: (open: boolean) => void;
  onSubmissionSuccess: (attemptId: string) => void;
}

/**
 * Executes the flush -> verify -> submit workflow with guaranteed loading-state
 * recovery and distinct expiration vs submission error handling.
 */
export async function executeAttemptSubmission(
  deps: AttemptSubmissionDeps,
): Promise<void> {
  if (!deps.attemptId || deps.isSubmitting || !deps.isCurrentSession()) {
    return;
  }

  deps.onSubmittingChange(true);
  deps.onSubmitError(null);

  try {
    const flushResult = await deps.flushBeforeSubmit();
    if (!deps.isCurrentSession()) return;

    if (flushResult.terminated) {
      let refreshed: AttemptDetailRead | null = null;
      try {
        refreshed = await deps.refreshAttempt();
      } catch (refreshErr: unknown) {
        if (!deps.isCurrentSession()) return;
        const detail =
          refreshErr instanceof Error ? refreshErr.message : 'Unable to reach server.';
        deps.onSubmitError(
          `Your examination session has ended or expired, and refreshing the final result failed (${detail}). Please retry to load your outcome.`,
        );
        return;
      }

      if (!deps.isCurrentSession()) return;

      if (!refreshed) {
        deps.onSubmitError(
          'Your examination session has ended or expired, but its final status could not be loaded. Please retry to load your outcome.',
        );
        return;
      }

      if (refreshed.status === 'SUBMITTED' || refreshed.status === 'EXPIRED') {
        deps.onModalOpenChange(false);
        return;
      }

      deps.onSubmitError(
        'Pending answer saves were interrupted while your attempt is still active. Please review your answers and try submitting again.',
      );
      return;
    }

    if (!flushResult.ok) {
      const issues: string[] = [];
      if (flushResult.failedQuestionIds.length > 0) {
        issues.push(`${flushResult.failedQuestionIds.length} failed save(s)`);
      }
      if (flushResult.conflictQuestionIds.length > 0) {
        issues.push(`${flushResult.conflictQuestionIds.length} unresolved conflict(s)`);
      }
      if ((flushResult.pendingQuestionIds?.length ?? 0) > 0) {
        issues.push(`${flushResult.pendingQuestionIds!.length} unsettled save(s)`);
      }
      deps.onSubmitError(
        `Cannot submit while there are ${issues.join(' and ')}. Please retry or resolve them first so your answers are persisted.`,
      );
      return;
    }

    await deps.submitAttempt(deps.attemptId);
    if (!deps.isCurrentSession()) return;

    deps.onModalOpenChange(false);
    deps.onSubmissionSuccess(deps.attemptId);
  } catch (err: unknown) {
    if (!deps.isCurrentSession()) return;
    const msg =
      err instanceof Error ? err.message : 'Submission failed. Please try again.';
    deps.onSubmitError(msg);
  } finally {
    if (deps.isCurrentSession()) {
      deps.onSubmittingChange(false);
    }
  }
}
