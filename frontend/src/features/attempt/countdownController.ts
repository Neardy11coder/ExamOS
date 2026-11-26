/**
 * Authoritative countdown & lazy-expiry polling controller for AttemptWorkspacePage.
 *
 * Guarantees:
 * - Server-authoritative deadlines: never marks an attempt EXPIRED locally.
 * - Counts down smoothly using relative monotonic/wall-clock deltas anchored to
 *   the server's `remaining_seconds` (immune to client clock skew).
 * - When local countdown reaches 0, triggers an authoritative backend refresh.
 * - If backend still reports IN_PROGRESS with remaining_seconds === 0, schedules
 *   a controlled delayed refresh (~750–1000 ms) rather than getting stuck at 00:00
 *   or spinning in a tight loop.
 * - Surfaces non-retryable authorization/not-found refresh failures so the
 *   workspace can offer an explicit recovery action instead of silently stopping.
 * - Coalesces overlapping refresh triggers so at most one countdown refresh
 *   request is in flight at a time.
 * - Stops immediately on terminal state (SUBMITTED / EXPIRED) and cleans up all
 *   timers on dispose/unmount and React StrictMode remounts.
 */

import { type AttemptDetailRead } from '../../api/attempts';
import { ApiError } from '../../api/auth';

export interface CountdownRefreshError {
  status: number;
  message: string;
}

export interface CountdownControllerDeps {
  refreshAttempt: () => Promise<AttemptDetailRead | null>;
  onRemainingSecondsChange: (remainingSeconds: number | null) => void;
  onTerminalAttempt?: (attempt: AttemptDetailRead) => void;
  onRefreshError?: (error: CountdownRefreshError | null) => void;
  setTimeoutFn?: (cb: () => void, ms: number) => ReturnType<typeof setTimeout>;
  clearTimeoutFn?: (id: ReturnType<typeof setTimeout>) => void;
  nowFn?: () => number;
  expiryPollIntervalMs?: number;
  retryErrorIntervalMs?: number;
}

function isNonRetryableHttpError(err: unknown): boolean {
  return (
    err instanceof ApiError &&
    (err.status === 401 || err.status === 403 || err.status === 404)
  );
}

function toCountdownRefreshError(err: unknown): CountdownRefreshError {
  const status = err instanceof ApiError ? err.status : 0;
  const messages: Record<number, string> = {
    401: 'Your sign-in session could not be verified. Sign in again, then retry checking this examination.',
    403: 'You no longer have permission to access this examination attempt. Return to your available exams or contact your instructor.',
    404: 'This examination attempt could not be found. Return to your available exams.',
  };

  return {
    status,
    message:
      messages[status] ??
      'The examination status could not be verified. Retry the status check or return to your available exams.',
  };
}

interface InFlightRefresh {
  id: number;
  epoch: number;
  promise: Promise<void>;
}

export class AttemptCountdownController {
  private attemptId: string | null = null;
  private disposed = false;
  private terminal = false;
  private lifecycleEpoch = 0;
  private syncVersion = 0;
  private nextRefreshId = 0;

  private targetZeroMs: number | null = null;
  private lastEmittedSeconds: number | null = null;

  private tickTimer: ReturnType<typeof setTimeout> | null = null;
  private pollTimer: ReturnType<typeof setTimeout> | null = null;
  private activeRefresh: InFlightRefresh | null = null;

  private zeroPollCount = 0;
  private errorRetryCount = 0;

  private readonly refreshAttemptFn: CountdownControllerDeps['refreshAttempt'];
  private readonly onRemainingSecondsChange: CountdownControllerDeps['onRemainingSecondsChange'];
  private readonly onTerminalAttempt?: CountdownControllerDeps['onTerminalAttempt'];
  private readonly onRefreshError?: CountdownControllerDeps['onRefreshError'];
  private readonly setTimeoutFn: (cb: () => void, ms: number) => ReturnType<typeof setTimeout>;
  private readonly clearTimeoutFn: (id: ReturnType<typeof setTimeout>) => void;
  private readonly nowFn: () => number;
  private readonly customExpiryPollIntervalMs: number | undefined;
  private readonly retryErrorIntervalMs: number;

  constructor(deps: CountdownControllerDeps) {
    this.refreshAttemptFn = deps.refreshAttempt;
    this.onRemainingSecondsChange = deps.onRemainingSecondsChange;
    this.onTerminalAttempt = deps.onTerminalAttempt;
    this.onRefreshError = deps.onRefreshError;
    this.setTimeoutFn = deps.setTimeoutFn ?? ((cb, ms) => globalThis.setTimeout(cb, ms));
    this.clearTimeoutFn = deps.clearTimeoutFn ?? ((id) => globalThis.clearTimeout(id));
    this.nowFn = deps.nowFn ?? (() => Date.now());
    this.customExpiryPollIntervalMs = deps.expiryPollIntervalMs;
    this.retryErrorIntervalMs = deps.retryErrorIntervalMs ?? 1000;
  }

  /** Re-enables timer scheduling after React StrictMode remounts or reactivation. */
  activate(): void {
    if (!this.disposed) return;
    this.disposed = false;
    this.lifecycleEpoch += 1;
    this.activeRefresh = null;
  }

  /** Cancels all pending timers and invalidates stale in-flight callbacks. */
  dispose(): void {
    this.disposed = true;
    this.lifecycleEpoch += 1;
    this.activeRefresh = null;
    this.clearTimers();
  }

  /** Returns whether the controller has observed a terminal server status. */
  isTerminal(): boolean {
    return this.terminal;
  }

  /** Returns true when a countdown-driven refresh request is currently in flight. */
  isRefreshing(): boolean {
    return this.activeRefresh !== null;
  }

  /** Reconciles timer state from an authoritative server AttemptDetailRead payload. */
  syncFromAttempt(attempt: AttemptDetailRead): void {
    if (this.disposed) return;

    // Any successful authoritative response restores a verifiable attempt state.
    this.onRefreshError?.(null);

    if (this.attemptId !== attempt.attempt_id) {
      this.attemptId = attempt.attempt_id;
      this.terminal = false;
      this.zeroPollCount = 0;
      this.errorRetryCount = 0;
      this.lastEmittedSeconds = null;
    }

    this.syncVersion += 1;
    this.activeRefresh = null;
    this.clearTimers();

    if (attempt.status === 'SUBMITTED' || attempt.status === 'EXPIRED') {
      this.terminal = true;
      this.targetZeroMs = null;
      this.emitRemaining(0);
      this.onTerminalAttempt?.(attempt);
      return;
    }

    this.terminal = false;
    const secs = Math.max(0, Math.floor(attempt.remaining_seconds));

    if (secs > 0) {
      this.zeroPollCount = 0;
      this.errorRetryCount = 0;
      this.targetZeroMs = this.nowFn() + secs * 1000;
      this.emitRemaining(secs);
      this.scheduleNextTick(secs);
      return;
    }

    // Server returned IN_PROGRESS with remaining_seconds === 0:
    // keep status IN_PROGRESS locally and schedule a controlled delayed refresh.
    this.targetZeroMs = null;
    this.emitRemaining(0);
    this.scheduleExpiryRefresh(this.nextZeroPollDelayMs());
  }

  /**
   * Triggers a deduplicated backend refresh. Concurrent calls while a refresh
   * is already in flight within the same lifecycle epoch coalesce onto the active promise.
   */
  triggerRefresh(): Promise<void> {
    if (this.disposed || this.terminal) {
      return Promise.resolve();
    }
    if (this.activeRefresh && this.activeRefresh.epoch === this.lifecycleEpoch) {
      return this.activeRefresh.promise;
    }

    const epochAtStart = this.lifecycleEpoch;
    const syncVersionAtStart = this.syncVersion;
    const refreshId = ++this.nextRefreshId;

    const isStillCurrentOwner = (): boolean =>
      !this.disposed &&
      !this.terminal &&
      this.lifecycleEpoch === epochAtStart &&
      this.syncVersion === syncVersionAtStart &&
      this.activeRefresh?.id === refreshId;

    let settleOuter!: () => void;
    const outerPromise = new Promise<void>((resolve) => {
      settleOuter = resolve;
    });

    this.activeRefresh = {
      id: refreshId,
      epoch: epochAtStart,
      promise: outerPromise,
    };

    void (async () => {
      try {
        const data = await this.refreshAttemptFn();
        if (!isStillCurrentOwner()) {
          return;
        }
        this.errorRetryCount = 0;
        if (!data) {
          this.scheduleExpiryRefresh(this.nextZeroPollDelayMs());
          return;
        }
        this.syncFromAttempt(data);
      } catch (err: unknown) {
        if (!isStillCurrentOwner()) {
          return;
        }
        if (isNonRetryableHttpError(err)) {
          this.clearTimers();
          this.onRefreshError?.(toCountdownRefreshError(err));
          return;
        }
        this.errorRetryCount += 1;
        this.scheduleExpiryRefresh(this.nextErrorRetryDelayMs());
      } finally {
        if (this.activeRefresh?.id === refreshId) {
          this.activeRefresh = null;
        }
        settleOuter();
      }
    })();

    return outerPromise;
  }

  private scheduleNextTick(currentDisplayedSeconds: number): void {
    if (this.disposed || this.terminal || this.targetZeroMs === null) return;

    this.clearTickTimer();
    const epochAtSchedule = this.lifecycleEpoch;
    const syncVersionAtSchedule = this.syncVersion;
    const nowMs = this.nowFn();
    const nextTransitionAtMs = this.targetZeroMs - (currentDisplayedSeconds - 1) * 1000;
    const delayMs = Math.max(16, nextTransitionAtMs - nowMs);

    const timerId = this.setTimeoutFn(() => {
      if (this.tickTimer === timerId) {
        this.tickTimer = null;
      }
      if (
        this.disposed ||
        this.terminal ||
        this.lifecycleEpoch !== epochAtSchedule ||
        this.syncVersion !== syncVersionAtSchedule ||
        this.targetZeroMs === null
      ) {
        return;
      }

      const currentNow = this.nowFn();
      const remainingMs = this.targetZeroMs - currentNow;

      if (remainingMs <= 0) {
        this.targetZeroMs = null;
        this.emitRemaining(0);
        void this.triggerRefresh();
        return;
      }

      const nextSecs = Math.ceil(remainingMs / 1000);
      this.emitRemaining(nextSecs);
      this.scheduleNextTick(nextSecs);
    }, delayMs);
    this.tickTimer = timerId;
  }

  private scheduleExpiryRefresh(delayMs: number): void {
    if (this.disposed || this.terminal) return;

    this.clearPollTimer();
    const epochAtSchedule = this.lifecycleEpoch;
    const syncVersionAtSchedule = this.syncVersion;

    const timerId = this.setTimeoutFn(() => {
      if (this.pollTimer === timerId) {
        this.pollTimer = null;
      }
      if (
        this.disposed ||
        this.terminal ||
        this.lifecycleEpoch !== epochAtSchedule ||
        this.syncVersion !== syncVersionAtSchedule
      ) {
        return;
      }
      void this.triggerRefresh();
    }, delayMs);
    this.pollTimer = timerId;
  }

  private nextZeroPollDelayMs(): number {
    this.zeroPollCount += 1;
    if (this.customExpiryPollIntervalMs !== undefined) {
      return this.customExpiryPollIntervalMs;
    }
    // 750 ms for the first 4 polls near the deadline, then 1000 ms to avoid tight loops.
    return this.zeroPollCount <= 4 ? 750 : 1000;
  }

  private nextErrorRetryDelayMs(): number {
    const exponent = Math.min(3, Math.max(0, this.errorRetryCount - 1));
    return Math.min(5000, this.retryErrorIntervalMs * Math.pow(2, exponent));
  }

  private emitRemaining(seconds: number | null): void {
    if (this.lastEmittedSeconds === seconds) return;
    this.lastEmittedSeconds = seconds;
    this.onRemainingSecondsChange(seconds);
  }

  private clearTickTimer(): void {
    if (this.tickTimer !== null) {
      this.clearTimeoutFn(this.tickTimer);
      this.tickTimer = null;
    }
  }

  private clearPollTimer(): void {
    if (this.pollTimer !== null) {
      this.clearTimeoutFn(this.pollTimer);
      this.pollTimer = null;
    }
  }

  private clearTimers(): void {
    this.clearTickTimer();
    this.clearPollTimer();
  }
}
