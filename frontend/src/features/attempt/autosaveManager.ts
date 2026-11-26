/**
 * Per-question serialized autosave manager for AttemptWorkspacePage.
 *
 * Guarantees:
 * - At most one save or reconciliation request per question in flight at a time.
 * - Independent saving across different questions.
 * - Per-question debouncing (~300 ms) coalescing rapid edits into the latest state.
 * - Strict separation between optimistic local UI state and server-confirmed state
 *   (slow server responses never overwrite newer local selections).
 * - Safe HTTP 409 reconciliation distinguishing already-applied retries/stale
 *   responses from genuine concurrent modifications in another session.
 * - Safe failure recovery: ambiguous network/5xx failures reconcile with server
 *   state via GET before issuing a new PUT, never retrying with a stale revision
 *   and never toggling or clearing the student's selected option.
 * - Flush-before-submit and clean timer lifecycle management.
 */

import {
  type AnswerSaveRequest,
  type AnswerSaveResponse,
  type AttemptDetailRead,
  RevisionConflictError,
} from '../../api/attempts';
import { ApiError } from '../../api/auth';

export type QuestionSaveStatus =
  | 'idle'
  | 'pending'
  | 'saving'
  | 'saved'
  | 'failed'
  | 'conflict';

export interface AnswerSnapshot {
  selected_option_id: string | null;
  marked_for_review: boolean;
}

export interface ServerAnswerSnapshot extends AnswerSnapshot {
  revision: number;
  saved_at?: string;
}

export interface QuestionAutosaveView {
  questionId: string;
  local: AnswerSnapshot;
  server: ServerAnswerSnapshot;
  status: QuestionSaveStatus;
  errorMessage: string | null;
  conflictServerState: ServerAnswerSnapshot | null;
}

export interface AutosaveFlushResult {
  ok: boolean;
  terminated: boolean;
  failedQuestionIds: string[];
  conflictQuestionIds: string[];
  /** Questions that are still pending/in-flight or differ from server-confirmed state. */
  pendingQuestionIds?: string[];
}

export interface AutosaveManagerDeps {
  saveAnswer: (
    attemptId: string,
    examQuestionId: string,
    payload: AnswerSaveRequest,
  ) => Promise<AnswerSaveResponse>;
  getAttempt: (attemptId: string) => Promise<AttemptDetailRead>;
  generateMutationId?: () => string;
  setTimeoutFn?: (cb: () => void, ms: number) => ReturnType<typeof setTimeout>;
  clearTimeoutFn?: (id: ReturnType<typeof setTimeout>) => void;
  debounceMs?: number;
  onAttemptTerminated?: (reasonCode: string) => void;
  onStateChange?: (views: Record<string, QuestionAutosaveView>) => void;
}

interface AttemptedMutation extends AnswerSnapshot {
  expected_revision: number;
  mutation_id: string;
}

interface InternalQuestionEntry {
  questionId: string;
  local: AnswerSnapshot;
  server: ServerAnswerSnapshot;
  status: QuestionSaveStatus;
  errorMessage: string | null;
  conflictServerState: ServerAnswerSnapshot | null;
  inFlight: boolean;
  debounceTimer: ReturnType<typeof setTimeout> | null;
  flushWaiters: Array<() => void>;
  needsReconciliation: boolean;
  lastAttemptedMutation: AttemptedMutation | null;
  queuedWhileInFlight: boolean;
}

function defaultGenerateMutationId(): string {
  if (typeof globalThis.crypto?.randomUUID === 'function') {
    return globalThis.crypto.randomUUID();
  }
  return `mut-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function sameAnswer(a: AnswerSnapshot, b: AnswerSnapshot): boolean {
  return (
    a.selected_option_id === b.selected_option_id &&
    a.marked_for_review === b.marked_for_review
  );
}

function isTerminalAttemptCode(code: string | undefined): boolean {
  return code === 'ATTEMPT_EXPIRED' || code === 'ATTEMPT_NOT_ACTIVE';
}

export class AttemptAutosaveManager {
  private attemptId: string | null = null;
  private attemptActive = false;
  private disposed = false;
  private inputLocked = false;
  private entries = new Map<string, InternalQuestionEntry>();

  private readonly saveAnswerFn: AutosaveManagerDeps['saveAnswer'];
  private readonly getAttemptFn: AutosaveManagerDeps['getAttempt'];
  private readonly generateMutationId: () => string;
  private readonly setTimeoutFn: (cb: () => void, ms: number) => ReturnType<typeof setTimeout>;
  private readonly clearTimeoutFn: (id: ReturnType<typeof setTimeout>) => void;
  private readonly debounceMs: number;
  private readonly onAttemptTerminated?: (reasonCode: string) => void;
  private readonly onStateChange?: (views: Record<string, QuestionAutosaveView>) => void;

  constructor(deps: AutosaveManagerDeps) {
    this.saveAnswerFn = deps.saveAnswer;
    this.getAttemptFn = deps.getAttempt;
    this.generateMutationId = deps.generateMutationId ?? defaultGenerateMutationId;
    this.setTimeoutFn = deps.setTimeoutFn ?? ((cb, ms) => globalThis.setTimeout(cb, ms));
    this.clearTimeoutFn = deps.clearTimeoutFn ?? ((id) => globalThis.clearTimeout(id));
    this.debounceMs = deps.debounceMs ?? 300;
    this.onAttemptTerminated = deps.onAttemptTerminated;
    this.onStateChange = deps.onStateChange;
  }

  /** Re-enables timer/callback emission after React StrictMode remounts. */
  activate(): void {
    this.disposed = false;
  }

  /** Prevents new local answer mutations while reviewing or submitting an attempt. */
  setInputLocked(locked: boolean): void {
    this.inputLocked = locked;
  }

  /** Cancels all pending timers and resolves waiters on unmount or termination. */
  dispose(): void {
    this.disposed = true;
    for (const entry of this.entries.values()) {
      this.clearEntryTimer(entry);
      this.resolveEntryWaiters(entry);
    }
  }

  /** Initializes or refreshes per-question state from an authoritative GET attempt payload. */
  hydrateFromAttempt(attempt: AttemptDetailRead): void {
    const isNewAttempt = this.attemptId !== attempt.attempt_id;
    this.attemptId = attempt.attempt_id;
    this.attemptActive = attempt.status === 'IN_PROGRESS';

    if (isNewAttempt) {
      for (const entry of this.entries.values()) {
        this.clearEntryTimer(entry);
        this.resolveEntryWaiters(entry);
      }
      this.entries.clear();
    }

    if (!this.attemptActive) {
      for (const entry of this.entries.values()) {
        this.clearEntryTimer(entry);
      }
    }

    for (const q of attempt.questions) {
      const serverSnapshot: ServerAnswerSnapshot = {
        selected_option_id: q.answer.selected_option_id,
        marked_for_review: q.answer.marked_for_review,
        revision: q.answer.revision,
      };

      const existing = this.entries.get(q.exam_question_id);
      if (!existing) {
        this.entries.set(q.exam_question_id, {
          questionId: q.exam_question_id,
          local: {
            selected_option_id: serverSnapshot.selected_option_id,
            marked_for_review: serverSnapshot.marked_for_review,
          },
          server: serverSnapshot,
          status: 'idle',
          errorMessage: null,
          conflictServerState: null,
          inFlight: false,
          debounceTimer: null,
          flushWaiters: [],
          needsReconciliation: false,
          lastAttemptedMutation: null,
          queuedWhileInFlight: false,
        });
      } else {
        this.applyBackgroundServerRefresh(existing, serverSnapshot);
      }
    }

    this.emitChange();
  }

  getSnapshot(): Record<string, QuestionAutosaveView> {
    const out: Record<string, QuestionAutosaveView> = {};
    for (const [qId, entry] of this.entries.entries()) {
      out[qId] = {
        questionId: entry.questionId,
        local: { ...entry.local },
        server: { ...entry.server },
        status: entry.status,
        errorMessage: entry.errorMessage,
        conflictServerState: entry.conflictServerState
          ? { ...entry.conflictServerState }
          : null,
      };
    }
    return out;
  }

  hasUnacknowledgedChanges(): boolean {
    for (const entry of this.entries.values()) {
      if (
        entry.inFlight ||
        entry.debounceTimer !== null ||
        entry.status === 'pending' ||
        entry.status === 'saving' ||
        entry.status === 'failed' ||
        entry.status === 'conflict' ||
        !sameAnswer(entry.local, entry.server)
      ) {
        return true;
      }
    }
    return false;
  }

  /**
   * Selects an option (or toggles it off to null if already selected) and
   * schedules a debounced serialized save.
   */
  selectOption(questionId: string, optionId: string): void {
    const entry = this.entries.get(questionId);
    if (!entry || !this.attemptActive || this.disposed || this.inputLocked) return;

    const nextSelected =
      entry.local.selected_option_id === optionId ? null : optionId;
    this.updateLocalIntent(entry, {
      selected_option_id: nextSelected,
      marked_for_review: entry.local.marked_for_review,
    });
  }

  /**
   * Toggles the marked-for-review flag and schedules a debounced serialized save.
   */
  toggleReview(questionId: string): void {
    const entry = this.entries.get(questionId);
    if (!entry || !this.attemptActive || this.disposed || this.inputLocked) return;

    this.updateLocalIntent(entry, {
      selected_option_id: entry.local.selected_option_id,
      marked_for_review: !entry.local.marked_for_review,
    });
  }

  /**
   * Explicitly retries a failed save (reconciling with the server first if
   * the previous failure outcome was ambiguous). Never toggles or clears local selection.
   */
  async retryQuestion(questionId: string): Promise<void> {
    const entry = this.entries.get(questionId);
    if (!entry || !this.attemptActive || this.disposed || this.inputLocked) return;

    if (entry.inFlight) {
      await this.waitForEntryIdle(entry);
      return;
    }

    if (entry.status === 'conflict') {
      return;
    }

    if (entry.status === 'failed' || !sameAnswer(entry.local, entry.server)) {
      this.clearEntryTimer(entry);
      await this.executeSave(questionId);
    }
  }

  /**
   * Resolves a conflict by keeping the student's latest local selection and
   * saving it against the latest known server revision.
   */
  async resolveConflictWithLocal(questionId: string): Promise<void> {
    const entry = this.entries.get(questionId);
    if (!entry || !this.attemptActive || this.disposed || this.inputLocked) return;
    if (entry.status !== 'conflict' || entry.inFlight) return;

    this.clearEntryTimer(entry);
    entry.conflictServerState = null;
    entry.errorMessage = null;
    entry.needsReconciliation = false;
    entry.lastAttemptedMutation = null;

    if (sameAnswer(entry.local, entry.server)) {
      entry.status = 'saved';
      this.emitChange();
      return;
    }

    entry.status = 'pending';
    this.emitChange();
    await this.executeSave(questionId);
  }

  /**
   * Resolves a conflict by discarding local unsaved changes and adopting the
   * canonical server answer.
   */
  resolveConflictWithServer(questionId: string): void {
    const entry = this.entries.get(questionId);
    if (!entry || !this.attemptActive || this.disposed || this.inputLocked) return;
    if (entry.status !== 'conflict' || entry.inFlight) return;

    this.clearEntryTimer(entry);
    entry.local = {
      selected_option_id: entry.server.selected_option_id,
      marked_for_review: entry.server.marked_for_review,
    };
    entry.conflictServerState = null;
    entry.errorMessage = null;
    entry.needsReconciliation = false;
    entry.lastAttemptedMutation = null;
    entry.status = entry.server.revision > 0 ? 'saved' : 'idle';
    this.emitChange();
  }

  /**
   * Flushes any debounced or in-flight write for a single question (e.g., when
   * navigating away to another question). Does not force-overwrite conflicts.
   */
  async flushQuestion(questionId: string): Promise<void> {
    const entry = this.entries.get(questionId);
    if (!entry || !this.attemptActive || this.disposed) return;
    if (entry.status === 'conflict' || entry.status === 'failed') return;

    if (entry.inFlight) {
      if (entry.debounceTimer !== null) {
        this.clearEntryTimer(entry);
        entry.queuedWhileInFlight = true;
      }
      await this.waitForEntryIdle(entry);
      return;
    }

    if (entry.debounceTimer !== null) {
      this.clearEntryTimer(entry);
      await this.executeSave(questionId);
    } else if (!sameAnswer(entry.local, entry.server)) {
      await this.executeSave(questionId);
    }
  }

  /**
   * Flushes ordinary pending/in-flight writes without retrying previously failed
   * questions or forcing conflicts (used when opening the submit review modal).
   */
  async flushPendingWrites(): Promise<AutosaveFlushResult> {
    return this.flushEntries({ retryFailed: false });
  }

  /**
   * Flushes all pending debounced writes, awaits all in-flight saves, and
   * safely retries any failed saves (with server reconciliation) before exam submission.
   */
  async flushBeforeSubmit(): Promise<AutosaveFlushResult> {
    return this.flushEntries({ retryFailed: true });
  }

  private async flushEntries(options: {
    retryFailed: boolean;
  }): Promise<AutosaveFlushResult> {
    const terminatedResult: AutosaveFlushResult = {
      ok: false,
      terminated: true,
      failedQuestionIds: [],
      conflictQuestionIds: [],
      pendingQuestionIds: [],
    };

    if (!this.attemptActive) return terminatedResult;

    // A failed save gets one explicit retry per flush operation. Persistent
    // failures are reported instead of being retried in a tight loop.
    const retriedFailed = new Set<string>();
    const maxPasses = Math.max(2, this.entries.size + 1);

    for (let pass = 0; pass < maxPasses; pass += 1) {
      const workPromises: Array<Promise<void>> = [];

      for (const entry of this.entries.values()) {
        if (entry.status === 'conflict') continue;

        if (entry.status === 'failed') {
          if (!options.retryFailed || retriedFailed.has(entry.questionId)) continue;
          retriedFailed.add(entry.questionId);
        }

        if (entry.inFlight) {
          if (entry.debounceTimer !== null) {
            this.clearEntryTimer(entry);
            entry.queuedWhileInFlight = true;
          }
          workPromises.push(this.waitForEntryIdle(entry));
          continue;
        }

        if (
          entry.debounceTimer !== null ||
          entry.status === 'failed' ||
          !sameAnswer(entry.local, entry.server)
        ) {
          this.clearEntryTimer(entry);
          workPromises.push(this.executeSave(entry.questionId));
        }
      }

      if (workPromises.length === 0) break;
      await Promise.all(workPromises);

      if (!this.attemptActive) return terminatedResult;

      // Do another pass only for non-terminal work that remains unsettled.
      // This also makes the success condition independent of the initial Map
      // iteration snapshot if a queued save was created while a request ran.
      const unsettled = Array.from(this.entries.values()).some((entry) =>
        entry.status !== 'failed' &&
        entry.status !== 'conflict' &&
        (entry.inFlight ||
          entry.debounceTimer !== null ||
          entry.status === 'pending' ||
          entry.status === 'saving' ||
          !sameAnswer(entry.local, entry.server)),
      );
      if (!unsettled) break;
    }

    if (!this.attemptActive) return terminatedResult;

    const failedQuestionIds: string[] = [];
    const conflictQuestionIds: string[] = [];
    const pendingQuestionIds: string[] = [];

    for (const entry of this.entries.values()) {
      if (entry.status === 'failed') {
        failedQuestionIds.push(entry.questionId);
      } else if (entry.status === 'conflict') {
        conflictQuestionIds.push(entry.questionId);
      } else if (
        entry.inFlight ||
        entry.debounceTimer !== null ||
        entry.status === 'pending' ||
        entry.status === 'saving' ||
        !sameAnswer(entry.local, entry.server)
      ) {
        pendingQuestionIds.push(entry.questionId);
      }
    }

    return {
      ok:
        failedQuestionIds.length === 0 &&
        conflictQuestionIds.length === 0 &&
        pendingQuestionIds.length === 0,
      terminated: false,
      failedQuestionIds,
      conflictQuestionIds,
      pendingQuestionIds,
    };
  }

  // -------------------------------------------------------------------------
  // Internal state machine
  // -------------------------------------------------------------------------

  private updateLocalIntent(
    entry: InternalQuestionEntry,
    nextLocal: AnswerSnapshot,
  ): void {
    entry.local = nextLocal;
    entry.errorMessage = null;

    // While in conflict, preserve the conflict banner and server comparison
    // while keeping the student's latest unsaved intent in `entry.local`.
    if (entry.status === 'conflict') {
      this.emitChange();
      return;
    }

    // If local reverted back to server state before anything went in flight
    // (and no previous ambiguous failure needs reconciliation), skip unnecessary write.
    if (
      !entry.inFlight &&
      !entry.needsReconciliation &&
      sameAnswer(entry.local, entry.server)
    ) {
      this.clearEntryTimer(entry);
      entry.status = entry.server.revision > 0 ? 'saved' : 'idle';
      this.emitChange();
      return;
    }

    entry.status = 'pending';
    this.clearEntryTimer(entry);

    if (this.debounceMs <= 0) {
      this.emitChange();
      void this.executeSave(entry.questionId);
      return;
    }

    entry.debounceTimer = this.setTimeoutFn(() => {
      entry.debounceTimer = null;
      if (this.disposed || !this.attemptActive) {
        this.resolveEntryWaiters(entry);
        return;
      }
      if (entry.inFlight) {
        entry.queuedWhileInFlight = true;
        return;
      }
      void this.executeSave(entry.questionId);
    }, this.debounceMs);

    this.emitChange();
  }

  private async executeSave(questionId: string): Promise<void> {
    const entry = this.entries.get(questionId);
    if (!entry || !this.attemptId || !this.attemptActive || this.disposed) {
      if (entry) this.resolveEntryWaiters(entry);
      return;
    }

    this.clearEntryTimer(entry);

    if (entry.inFlight) {
      entry.queuedWhileInFlight = true;
      await this.waitForEntryIdle(entry);
      return;
    }

    if (entry.status === 'conflict') {
      this.resolveEntryWaiters(entry);
      return;
    }

    // If an earlier request failed ambiguously (network/5xx), reconcile with
    // the server via GET before issuing a new PUT with a potentially stale revision.
    if (entry.needsReconciliation) {
      const shouldContinueToPut = await this.reconcileBeforeRetry(entry);
      if (!shouldContinueToPut || this.disposed || !this.attemptActive) {
        if (this.disposed || !this.attemptActive) {
          this.clearEntryTimer(entry);
          entry.queuedWhileInFlight = false;
        }
        if (!entry.inFlight && entry.debounceTimer === null) {
          this.resolveEntryWaiters(entry);
        }
        return;
      }
    }

    this.clearEntryTimer(entry);

    if (sameAnswer(entry.local, entry.server)) {
      entry.status = entry.server.revision > 0 ? 'saved' : 'idle';
      entry.errorMessage = null;
      entry.lastAttemptedMutation = null;
      this.resolveEntryWaiters(entry);
      this.emitChange();
      return;
    }

    const payloadToSend: AttemptedMutation = {
      selected_option_id: entry.local.selected_option_id,
      marked_for_review: entry.local.marked_for_review,
      expected_revision: entry.server.revision,
      mutation_id: this.generateMutationId(),
    };

    entry.inFlight = true;
    entry.queuedWhileInFlight = false;
    entry.lastAttemptedMutation = payloadToSend;
    entry.status = 'saving';
    entry.errorMessage = null;
    entry.conflictServerState = null;
    this.emitChange();

    let needsFollowUpSave = false;

    try {
      const resp = await this.saveAnswerFn(this.attemptId, questionId, {
        selected_option_id: payloadToSend.selected_option_id,
        marked_for_review: payloadToSend.marked_for_review,
        expected_revision: payloadToSend.expected_revision,
        mutation_id: payloadToSend.mutation_id,
      });

      if (this.disposed) return;

      // Update ONLY server-confirmed state; never overwrite newer `entry.local`!
      entry.server = {
        selected_option_id: resp.selected_option_id,
        marked_for_review: resp.marked_for_review,
        revision: resp.revision,
        saved_at: resp.saved_at,
      };
      entry.lastAttemptedMutation = null;
      entry.needsReconciliation = false;

      if (sameAnswer(entry.local, entry.server)) {
        entry.status = 'saved';
        entry.errorMessage = null;
        entry.conflictServerState = null;
      } else {
        // Student made a newer local edit while this PUT was in flight.
        entry.status = 'pending';
        if (entry.queuedWhileInFlight || entry.debounceTimer === null) {
          needsFollowUpSave = true;
        }
      }
    } catch (err: unknown) {
      if (this.disposed) return;

      if (err instanceof ApiError && isTerminalAttemptCode(err.code)) {
        this.handleAttemptTerminated(err.code ?? 'ATTEMPT_EXPIRED');
        return;
      }

      if (
        err instanceof RevisionConflictError ||
        (err instanceof ApiError && err.status === 409)
      ) {
        const followUp = await this.handleConflictError(entry, payloadToSend, err);
        needsFollowUpSave = followUp;
      } else {
        // Network failure, 5xx, or other error: preserve local intent, require
        // server reconciliation before retrying so we don't send a stale revision.
        entry.needsReconciliation = true;
        entry.lastAttemptedMutation = payloadToSend;
        entry.status = 'failed';
        entry.errorMessage =
          err instanceof Error ? err.message : 'Save failed. Please retry.';
      }
    } finally {
      entry.inFlight = false;
      if (needsFollowUpSave && !this.disposed && this.attemptActive) {
        await this.executeSave(questionId);
      } else {
        if (!entry.inFlight && entry.debounceTimer === null) {
          this.resolveEntryWaiters(entry);
        }
        if (!this.disposed) {
          this.emitChange();
        }
      }
    }
  }

  /**
   * Fetches canonical server state before retrying an ambiguously failed save.
   * Returns `true` if a follow-up PUT is needed and safe; `false` if already
   * applied, conflicted, or reconciliation itself failed.
   */
  private async reconcileBeforeRetry(
    entry: InternalQuestionEntry,
  ): Promise<boolean> {
    if (!this.attemptId) return false;

    const prevAttempted = entry.lastAttemptedMutation;
    entry.inFlight = true;
    entry.status = 'saving';
    entry.errorMessage = null;
    this.emitChange();

    try {
      const attempt = await this.getAttemptFn(this.attemptId);
      if (this.disposed || this.entries.get(entry.questionId) !== entry) {
        this.clearEntryTimer(entry);
        entry.queuedWhileInFlight = false;
        return false;
      }

      if (attempt.status !== 'IN_PROGRESS') {
        this.handleAttemptTerminated(
          attempt.status === 'EXPIRED' ? 'ATTEMPT_EXPIRED' : 'ATTEMPT_NOT_ACTIVE',
        );
        return false;
      }

      const canonicalQ = attempt.questions.find(
        (q) => q.exam_question_id === entry.questionId,
      );
      if (!canonicalQ) {
        this.clearEntryTimer(entry);
        entry.queuedWhileInFlight = false;
        entry.status = 'failed';
        entry.errorMessage = 'Question could not be found in attempt state.';
        this.emitChange();
        return false;
      }

      const canonical: ServerAnswerSnapshot = {
        selected_option_id: canonicalQ.answer.selected_option_id,
        marked_for_review: canonicalQ.answer.marked_for_review,
        revision: canonicalQ.answer.revision,
      };
      entry.server = canonical;
      entry.needsReconciliation = false;

      // Also refresh non-dirty sibling questions opportunistically.
      for (const q of attempt.questions) {
        if (q.exam_question_id === entry.questionId) continue;
        const sibling = this.entries.get(q.exam_question_id);
        if (sibling) {
          this.applyBackgroundServerRefresh(sibling, {
            selected_option_id: q.answer.selected_option_id,
            marked_for_review: q.answer.marked_for_review,
            revision: q.answer.revision,
          });
        }
      }

      // Case 1: Canonical server state already matches our latest local intent.
      if (sameAnswer(canonical, entry.local)) {
        this.clearEntryTimer(entry);
        entry.queuedWhileInFlight = false;
        entry.lastAttemptedMutation = null;
        entry.conflictServerState = null;
        entry.errorMessage = null;
        entry.status = canonical.revision > 0 ? 'saved' : 'idle';
        this.emitChange();
        return false;
      }

      const prevExpectedRev = prevAttempted?.expected_revision ?? canonical.revision;

      // Case 2: Server revision did not advance -> previous PUT never committed.
      if (canonical.revision === prevExpectedRev) {
        entry.lastAttemptedMutation = null;
        return true;
      }

      // Case 3: Server revision advanced by 1 to match our earlier attempted
      // mutation, while the student subsequently made a newer local edit.
      if (
        prevAttempted &&
        canonical.revision === prevExpectedRev + 1 &&
        sameAnswer(canonical, prevAttempted)
      ) {
        entry.lastAttemptedMutation = null;
        return true;
      }

      // Case 4: Another session modified this question to a different state.
      this.clearEntryTimer(entry);
      entry.lastAttemptedMutation = null;
      entry.queuedWhileInFlight = false;
      entry.status = 'conflict';
      entry.conflictServerState = { ...canonical };
      entry.errorMessage =
        'Another session modified this question while your save was pending. Choose whether to keep your selection or use the server answer.';
      this.emitChange();
      return false;
    } catch (err: unknown) {
      if (this.disposed) return false;
      if (err instanceof ApiError && isTerminalAttemptCode(err.code)) {
        this.handleAttemptTerminated(err.code ?? 'ATTEMPT_EXPIRED');
        return false;
      }
      this.clearEntryTimer(entry);
      entry.needsReconciliation = true;
      entry.queuedWhileInFlight = false;
      entry.status = 'failed';
      entry.errorMessage =
        err instanceof Error
          ? err.message
          : 'Unable to verify server state. Please retry.';
      this.emitChange();
      return false;
    } finally {
      entry.inFlight = false;
    }
  }

  /**
   * Handles HTTP 409 conflict responses. Distinguishes already-committed
   * retries/stale responses from genuine concurrent edits in another session.
   * Returns true if a follow-up save for a newer local edit should run next.
   */
  private async handleConflictError(
    entry: InternalQuestionEntry,
    payloadToSend: AttemptedMutation,
    err: unknown,
  ): Promise<boolean> {
    let canonical: ServerAnswerSnapshot | null = null;

    if (err instanceof RevisionConflictError) {
      canonical = {
        selected_option_id: err.canonicalState.selected_option_id,
        marked_for_review: err.canonicalState.marked_for_review,
        revision: err.canonicalState.revision,
        saved_at: err.canonicalState.saved_at,
      };
    } else if (this.attemptId) {
      // Fallback: fetch canonical server state if 409 lacked canonical details.
      try {
        const attempt = await this.getAttemptFn(this.attemptId);
        if (this.disposed) return false;
        if (attempt.status !== 'IN_PROGRESS') {
          this.handleAttemptTerminated(
            attempt.status === 'EXPIRED' ? 'ATTEMPT_EXPIRED' : 'ATTEMPT_NOT_ACTIVE',
          );
          return false;
        }
        const canonicalQ = attempt.questions.find(
          (q) => q.exam_question_id === entry.questionId,
        );
        if (canonicalQ) {
          canonical = {
            selected_option_id: canonicalQ.answer.selected_option_id,
            marked_for_review: canonicalQ.answer.marked_for_review,
            revision: canonicalQ.answer.revision,
          };
        }
      } catch (fetchErr: unknown) {
        if (fetchErr instanceof ApiError && isTerminalAttemptCode(fetchErr.code)) {
          this.handleAttemptTerminated(fetchErr.code ?? 'ATTEMPT_EXPIRED');
          return false;
        }
        this.clearEntryTimer(entry);
        entry.queuedWhileInFlight = false;
        entry.needsReconciliation = true;
        entry.status = 'failed';
        entry.errorMessage =
          fetchErr instanceof Error
            ? fetchErr.message
            : 'Conflict occurred and server state could not be verified.';
        return false;
      }
    }

    if (!canonical) {
      this.clearEntryTimer(entry);
      entry.queuedWhileInFlight = false;
      entry.needsReconciliation = true;
      entry.status = 'failed';
      entry.errorMessage =
        err instanceof Error ? err.message : 'Revision conflict occurred.';
      return false;
    }

    entry.server = canonical;
    entry.needsReconciliation = false;

    // 1. Stale retry of an operation that already committed at expected_revision + 1
    //    and still matches the student's current intended selection.
    if (
      canonical.revision === payloadToSend.expected_revision + 1 &&
      sameAnswer(canonical, entry.local)
    ) {
      this.clearEntryTimer(entry);
      entry.queuedWhileInFlight = false;
      entry.lastAttemptedMutation = null;
      entry.conflictServerState = null;
      entry.errorMessage = null;
      entry.status = 'saved';
      return false;
    }

    // 2. Earlier mutation already committed at expected_revision + 1, and student
    //    has since made a newer local selection in this tab.
    if (
      canonical.revision === payloadToSend.expected_revision + 1 &&
      sameAnswer(canonical, payloadToSend) &&
      !sameAnswer(canonical, entry.local)
    ) {
      entry.lastAttemptedMutation = null;
      entry.conflictServerState = null;
      entry.errorMessage = null;
      entry.status = 'pending';
      return entry.queuedWhileInFlight || entry.debounceTimer === null;
    }

    // 3. Genuine concurrent modification from another session:
    //    Preserve user's latest unsaved intent (`entry.local`) and surface conflict!
    this.clearEntryTimer(entry);
    entry.queuedWhileInFlight = false;
    entry.lastAttemptedMutation = null;
    entry.status = 'conflict';
    entry.conflictServerState = { ...canonical };
    entry.errorMessage =
      'Another session modified this question on the server. Your unsaved selection is preserved—choose whether to save your selection or use the server answer.';
    return false;
  }

  private applyBackgroundServerRefresh(
    entry: InternalQuestionEntry,
    serverSnapshot: ServerAnswerSnapshot,
  ): void {
    const isDirty =
      entry.inFlight ||
      entry.debounceTimer !== null ||
      entry.queuedWhileInFlight ||
      entry.needsReconciliation ||
      entry.status === 'pending' ||
      entry.status === 'saving' ||
      entry.status === 'failed' ||
      entry.status === 'conflict' ||
      !sameAnswer(entry.local, entry.server);

    // Never advance server revision or overwrite local/conflict state for dirty questions.
    // Preserving the original server revision ensures the pending PUT still triggers
    // HTTP 409 conflict detection if another session modified this question.
    if (isDirty) {
      return;
    }

    if (serverSnapshot.revision < entry.server.revision) {
      return;
    }

    entry.server = {
      ...serverSnapshot,
      saved_at: serverSnapshot.saved_at ?? entry.server.saved_at,
    };
    entry.local = {
      selected_option_id: serverSnapshot.selected_option_id,
      marked_for_review: serverSnapshot.marked_for_review,
    };
    if (serverSnapshot.revision > 0 && entry.status === 'idle') {
      entry.status = 'saved';
    }
  }

  private handleAttemptTerminated(reasonCode: string): void {
    this.attemptActive = false;
    for (const entry of this.entries.values()) {
      this.clearEntryTimer(entry);
      this.resolveEntryWaiters(entry);
    }
    this.emitChange();
    this.onAttemptTerminated?.(reasonCode);
  }

  private clearEntryTimer(entry: InternalQuestionEntry): void {
    if (entry.debounceTimer !== null) {
      this.clearTimeoutFn(entry.debounceTimer);
      entry.debounceTimer = null;
    }
  }

  private waitForEntryIdle(entry: InternalQuestionEntry): Promise<void> {
    if (!entry.inFlight && entry.debounceTimer === null && !entry.queuedWhileInFlight) {
      return Promise.resolve();
    }
    return new Promise((resolve) => {
      entry.flushWaiters.push(resolve);
    });
  }

  private resolveEntryWaiters(entry: InternalQuestionEntry): void {
    if (entry.flushWaiters.length === 0) return;
    const waiters = entry.flushWaiters.splice(0, entry.flushWaiters.length);
    for (const resolve of waiters) {
      resolve();
    }
  }

  private emitChange(): void {
    if (!this.disposed && this.onStateChange) {
      this.onStateChange(this.getSnapshot());
    }
  }
}
