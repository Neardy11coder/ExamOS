/**
 * Automated unit and behavioral tests for ExamOS Phase 1B Countdown & Expiry Reliability.
 *
 * Covers:
 * 1. Countdown reaching zero triggers an authoritative API refresh.
 * 2. IN_PROGRESS + remaining_seconds === 0 schedules a controlled delayed refresh (500–1000 ms).
 * 3. EXPIRED triggers the terminal workflow.
 * 4. SUBMITTED triggers the result workflow.
 * 5. Terminal attempts stop polling completely.
 * 6. Multiple simultaneous countdown refresh requests are prevented.
 * 7. Timer cleanup works on disposal/unmount (including mid-refresh disposal).
 * 8. React StrictMode mount -> unmount -> remount does not create duplicate persistent polling loops.
 * 9. Server reconciliation when server returns positive remaining_seconds after local zero.
 * 10. Transient refresh errors retry without leaving countdown stuck at 00:00.
 */

import { strict as assert } from 'node:assert';
import { type AttemptDetailRead } from '../src/api/attempts';
import { ApiError } from '../src/api/auth';
import { AttemptCountdownController } from '../src/features/attempt/countdownController';

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (err: unknown) => void;
}

function createDeferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (err: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

class FakeClock {
  private nextId = 1;
  private timers = new Map<number, { runAt: number; cb: () => void }>();
  public now = 0;

  setTimeout = (cb: () => void, ms: number): ReturnType<typeof setTimeout> => {
    const id = this.nextId++;
    this.timers.set(id, { runAt: this.now + ms, cb });
    return id as unknown as ReturnType<typeof setTimeout>;
  };

  clearTimeout = (id: ReturnType<typeof setTimeout>): void => {
    this.timers.delete(id as unknown as number);
  };

  async advanceBy(ms: number): Promise<void> {
    const target = this.now + ms;
    while (true) {
      let nextEntry: [number, { runAt: number; cb: () => void }] | null = null;
      for (const entry of this.timers.entries()) {
        if (entry[1].runAt <= target) {
          if (!nextEntry || entry[1].runAt < nextEntry[1].runAt) {
            nextEntry = entry;
          }
        }
      }
      if (!nextEntry) break;
      const [id, timer] = nextEntry;
      this.timers.delete(id);
      this.now = timer.runAt;
      timer.cb();
      await flushMicrotasks();
    }
    this.now = target;
  }

  pendingCount(): number {
    return this.timers.size;
  }
}

async function flushMicrotasks(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

function makeAttempt(overrides?: {
  attemptId?: string;
  status?: string;
  remainingSeconds?: number;
}): AttemptDetailRead {
  return {
    attempt_id: overrides?.attemptId ?? 'attempt-1',
    status: overrides?.status ?? 'IN_PROGRESS',
    started_at: '2026-11-26T00:00:00Z',
    deadline_at: '2026-11-26T00:30:00Z',
    remaining_seconds: overrides?.remainingSeconds ?? 3,
    exam: {
      id: 'exam-1',
      title: 'Systems Exam',
      instructions: 'Pick one option.',
      duration_minutes: 30,
      total_marks: 10,
    },
    questions: [],
  };
}

async function runTests() {
  console.log('--- Starting ExamOS Countdown & Expiry Reliability Tests ---');

  // Test 1: Countdown reaching zero triggers an API refresh
  console.log('Test 1: Countdown reaching zero triggers an API refresh');
  {
    const clock = new FakeClock();
    const observedSeconds: Array<number | null> = [];
    let refreshCalls = 0;

    const controller = new AttemptCountdownController({
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      nowFn: () => clock.now,
      refreshAttempt: async () => {
        refreshCalls += 1;
        return makeAttempt({ status: 'EXPIRED', remainingSeconds: 0 });
      },
      onRemainingSecondsChange: (secs) => observedSeconds.push(secs),
    });

    controller.activate();
    controller.syncFromAttempt(makeAttempt({ status: 'IN_PROGRESS', remainingSeconds: 3 }));
    assert.deepEqual(observedSeconds, [3]);
    assert.equal(refreshCalls, 0);

    await clock.advanceBy(1000);
    assert.deepEqual(observedSeconds, [3, 2]);
    assert.equal(refreshCalls, 0);

    await clock.advanceBy(1000);
    assert.deepEqual(observedSeconds, [3, 2, 1]);
    assert.equal(refreshCalls, 0);

    await clock.advanceBy(1000);
    assert.deepEqual(observedSeconds, [3, 2, 1, 0]);
    assert.equal(refreshCalls, 1);

    controller.dispose();
  }

  // Test 2: IN_PROGRESS + remaining_seconds = 0 triggers controlled delayed refresh (not tight loop)
  console.log('Test 2: IN_PROGRESS + remaining_seconds = 0 triggers controlled delayed refresh');
  {
    const clock = new FakeClock();
    let refreshCalls = 0;
    const terminalEvents: string[] = [];

    const controller = new AttemptCountdownController({
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      nowFn: () => clock.now,
      refreshAttempt: async () => {
        refreshCalls += 1;
        if (refreshCalls < 3) {
          return makeAttempt({ status: 'IN_PROGRESS', remainingSeconds: 0 });
        }
        return makeAttempt({ status: 'EXPIRED', remainingSeconds: 0 });
      },
      onRemainingSecondsChange: () => {},
      onTerminalAttempt: (att) => terminalEvents.push(att.status),
    });

    controller.activate();
    controller.syncFromAttempt(makeAttempt({ status: 'IN_PROGRESS', remainingSeconds: 1 }));

    // Reach 0 at t=1000 -> immediate refresh #1 returns IN_PROGRESS + 0
    await clock.advanceBy(1000);
    assert.equal(refreshCalls, 1);
    assert.deepEqual(terminalEvents, []);
    assert.equal(controller.isTerminal(), false);

    // Must NOT spin tightly before 750ms
    await clock.advanceBy(500);
    assert.equal(refreshCalls, 1);

    // At +750ms total -> refresh #2 returns IN_PROGRESS + 0
    await clock.advanceBy(250);
    assert.equal(refreshCalls, 2);
    assert.deepEqual(terminalEvents, []);

    // At +750ms again -> refresh #3 returns EXPIRED
    await clock.advanceBy(750);
    assert.equal(refreshCalls, 3);
    assert.deepEqual(terminalEvents, ['EXPIRED']);
    assert.equal(controller.isTerminal(), true);
    assert.equal(clock.pendingCount(), 0);

    controller.dispose();
  }

  // Test 3: EXPIRED triggers terminal workflow and stops polling
  console.log('Test 3: EXPIRED triggers terminal workflow and stops polling');
  {
    const clock = new FakeClock();
    let refreshCalls = 0;
    const terminalStatuses: string[] = [];
    const observedSeconds: Array<number | null> = [];

    const controller = new AttemptCountdownController({
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      nowFn: () => clock.now,
      refreshAttempt: async () => {
        refreshCalls += 1;
        return makeAttempt({ status: 'EXPIRED', remainingSeconds: 0 });
      },
      onRemainingSecondsChange: (s) => observedSeconds.push(s),
      onTerminalAttempt: (att) => terminalStatuses.push(att.status),
    });

    controller.activate();
    controller.syncFromAttempt(makeAttempt({ status: 'IN_PROGRESS', remainingSeconds: 1 }));
    await clock.advanceBy(1000);

    assert.equal(refreshCalls, 1);
    assert.deepEqual(terminalStatuses, ['EXPIRED']);
    assert.deepEqual(observedSeconds, [1, 0]);
    assert.equal(controller.isTerminal(), true);
    assert.equal(clock.pendingCount(), 0);

    // Advancing 60 seconds more must not trigger any further polling
    await clock.advanceBy(60_000);
    assert.equal(refreshCalls, 1);
  }

  // Test 4: SUBMITTED triggers result workflow and stops polling
  console.log('Test 4: SUBMITTED triggers result workflow and stops polling');
  {
    const clock = new FakeClock();
    let refreshCalls = 0;
    const terminalStatuses: string[] = [];

    const controller = new AttemptCountdownController({
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      nowFn: () => clock.now,
      refreshAttempt: async () => {
        refreshCalls += 1;
        return makeAttempt({ status: 'SUBMITTED', remainingSeconds: 0 });
      },
      onRemainingSecondsChange: () => {},
      onTerminalAttempt: (att) => terminalStatuses.push(att.status),
    });

    controller.activate();
    controller.syncFromAttempt(makeAttempt({ status: 'IN_PROGRESS', remainingSeconds: 1 }));
    await clock.advanceBy(1000);

    assert.equal(refreshCalls, 1);
    assert.deepEqual(terminalStatuses, ['SUBMITTED']);
    assert.equal(controller.isTerminal(), true);
    assert.equal(clock.pendingCount(), 0);

    await clock.advanceBy(60_000);
    assert.equal(refreshCalls, 1);
  }

  // Test 5: Initial terminal attempt does not start polling
  console.log('Test 5: Terminal attempts do not continue polling');
  {
    const clock = new FakeClock();
    let refreshCalls = 0;
    const terminalStatuses: string[] = [];

    const controller = new AttemptCountdownController({
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      nowFn: () => clock.now,
      refreshAttempt: async () => {
        refreshCalls += 1;
        return makeAttempt({ status: 'EXPIRED', remainingSeconds: 0 });
      },
      onRemainingSecondsChange: () => {},
      onTerminalAttempt: (att) => terminalStatuses.push(att.status),
    });

    controller.activate();
    controller.syncFromAttempt(makeAttempt({ status: 'EXPIRED', remainingSeconds: 0 }));
    assert.deepEqual(terminalStatuses, ['EXPIRED']);
    assert.equal(clock.pendingCount(), 0);

    // Explicit triggerRefresh on terminal controller is a no-op
    await controller.triggerRefresh();
    await clock.advanceBy(10_000);
    assert.equal(refreshCalls, 0);
  }

  // Test 6: Multiple simultaneous countdown refresh requests are prevented
  console.log('Test 6: Multiple simultaneous countdown refresh requests are prevented');
  {
    const clock = new FakeClock();
    const deferred = createDeferred<AttemptDetailRead>();
    let refreshCalls = 0;

    const controller = new AttemptCountdownController({
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      nowFn: () => clock.now,
      refreshAttempt: () => {
        refreshCalls += 1;
        return deferred.promise;
      },
      onRemainingSecondsChange: () => {},
    });

    controller.activate();
    controller.syncFromAttempt(makeAttempt({ status: 'IN_PROGRESS', remainingSeconds: 1 }));

    await clock.advanceBy(1000);
    assert.equal(refreshCalls, 1);
    assert.equal(controller.isRefreshing(), true);

    // Concurrent triggerRefresh calls must coalesce onto the in-flight request
    const p1 = controller.triggerRefresh();
    const p2 = controller.triggerRefresh();
    assert.equal(refreshCalls, 1);

    deferred.resolve(makeAttempt({ status: 'EXPIRED', remainingSeconds: 0 }));
    await Promise.all([p1, p2]);
    assert.equal(refreshCalls, 1);
    assert.equal(controller.isRefreshing(), false);
    assert.equal(controller.isTerminal(), true);
  }

  // Test 7: Timer cleanup works on disposal/unmount (including in-flight refresh)
  console.log('Test 7: Timer cleanup works on disposal/unmount');
  {
    const clock = new FakeClock();
    const deferred = createDeferred<AttemptDetailRead>();
    let refreshCalls = 0;
    const terminalEvents: string[] = [];

    const controller = new AttemptCountdownController({
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      nowFn: () => clock.now,
      refreshAttempt: () => {
        refreshCalls += 1;
        return deferred.promise;
      },
      onRemainingSecondsChange: () => {},
      onTerminalAttempt: (att) => terminalEvents.push(att.status),
    });

    controller.activate();
    controller.syncFromAttempt(makeAttempt({ status: 'IN_PROGRESS', remainingSeconds: 5 }));
    assert.equal(clock.pendingCount(), 1);

    // Dispose while tick timer is active -> clears timer
    controller.dispose();
    assert.equal(clock.pendingCount(), 0);
    await clock.advanceBy(10_000);
    assert.equal(refreshCalls, 0);

    // Re-activate, hit zero so refresh is in-flight, then dispose before response arrives
    controller.activate();
    controller.syncFromAttempt(makeAttempt({ status: 'IN_PROGRESS', remainingSeconds: 1 }));
    await clock.advanceBy(1000);
    assert.equal(refreshCalls, 1);

    controller.dispose();
    deferred.resolve(makeAttempt({ status: 'IN_PROGRESS', remainingSeconds: 0 }));
    await flushMicrotasks();

    // Disposed controller must NOT schedule follow-up polls or invoke callbacks
    assert.equal(clock.pendingCount(), 0);
    assert.deepEqual(terminalEvents, []);
  }

  // Test 8: React StrictMode mount -> unmount -> remount does not create duplicate polling loops
  console.log('Test 8: React StrictMode does not create duplicate persistent polling loops');
  {
    const clock = new FakeClock();
    let refreshCalls = 0;
    const observedSeconds: Array<number | null> = [];

    const controller = new AttemptCountdownController({
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      nowFn: () => clock.now,
      refreshAttempt: async () => {
        refreshCalls += 1;
        if (refreshCalls < 2) {
          return makeAttempt({ status: 'IN_PROGRESS', remainingSeconds: 0 });
        }
        return makeAttempt({ status: 'EXPIRED', remainingSeconds: 0 });
      },
      onRemainingSecondsChange: (s) => observedSeconds.push(s),
    });

    // StrictMode Mount 1
    controller.activate();
    controller.syncFromAttempt(makeAttempt({ status: 'IN_PROGRESS', remainingSeconds: 2 }));
    assert.equal(clock.pendingCount(), 1);

    // StrictMode Cleanup 1
    controller.dispose();
    assert.equal(clock.pendingCount(), 0);

    // StrictMode Remount 2
    controller.activate();
    controller.syncFromAttempt(makeAttempt({ status: 'IN_PROGRESS', remainingSeconds: 2 }));
    assert.equal(clock.pendingCount(), 1, 'Only one active timer must exist after StrictMode remount');

    await clock.advanceBy(1000);
    assert.equal(clock.pendingCount(), 1);
    await clock.advanceBy(1000);
    assert.equal(refreshCalls, 1, 'Zero reached once -> only 1 refresh call');

    await clock.advanceBy(750);
    assert.equal(refreshCalls, 2);
    assert.equal(controller.isTerminal(), true);
    assert.equal(clock.pendingCount(), 0);
    assert.deepEqual(observedSeconds, [2, 1, 0]);
  }

  // Test 9: Server reconciliation when server returns positive remaining_seconds after local zero
  console.log('Test 9: Reconciles countdown when server still has positive remaining_seconds');
  {
    const clock = new FakeClock();
    const observedSeconds: Array<number | null> = [];
    let refreshCalls = 0;

    const controller = new AttemptCountdownController({
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      nowFn: () => clock.now,
      refreshAttempt: async () => {
        refreshCalls += 1;
        if (refreshCalls === 1) {
          // Server says 2 seconds remain
          return makeAttempt({ status: 'IN_PROGRESS', remainingSeconds: 2 });
        }
        return makeAttempt({ status: 'EXPIRED', remainingSeconds: 0 });
      },
      onRemainingSecondsChange: (s) => observedSeconds.push(s),
    });

    controller.activate();
    controller.syncFromAttempt(makeAttempt({ status: 'IN_PROGRESS', remainingSeconds: 1 }));

    // Hits 0 at t=1000 -> server says 2s remaining
    await clock.advanceBy(1000);
    assert.equal(refreshCalls, 1);
    assert.deepEqual(observedSeconds, [1, 0, 2]);

    // Counts down 2 -> 1 -> 0 and refreshes again
    await clock.advanceBy(2000);
    assert.equal(refreshCalls, 2);
    assert.equal(controller.isTerminal(), true);
    assert.deepEqual(observedSeconds, [1, 0, 2, 1, 0]);
  }

  // Test 10: Transient refresh error retries without getting stuck; 401 stops polling
  console.log('Test 10: Transient refresh error retries cleanly and 401 stops polling');
  {
    const clock = new FakeClock();
    let refreshCalls = 0;

    const controller = new AttemptCountdownController({
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      nowFn: () => clock.now,
      retryErrorIntervalMs: 1000,
      refreshAttempt: async () => {
        refreshCalls += 1;
        if (refreshCalls === 1) {
          throw new ApiError(503, 'Service unavailable');
        }
        return makeAttempt({ status: 'EXPIRED', remainingSeconds: 0 });
      },
      onRemainingSecondsChange: () => {},
    });

    controller.activate();
    controller.syncFromAttempt(makeAttempt({ status: 'IN_PROGRESS', remainingSeconds: 1 }));

    await clock.advanceBy(1000);
    assert.equal(refreshCalls, 1);
    assert.equal(clock.pendingCount(), 1, 'Transient 503 must schedule a retry');

    await clock.advanceBy(1000);
    assert.equal(refreshCalls, 2);
    assert.equal(controller.isTerminal(), true);
    assert.equal(clock.pendingCount(), 0);

    // Non-retryable authorization/not-found responses stop automatic polling
    // but must surface an actionable message instead of silently leaving 00:00.
    const nonRetryableCases = [
      {
        status: 401,
        expectedMessage: 'Your sign-in session could not be verified.',
      },
      {
        status: 403,
        expectedMessage: 'You no longer have permission to access this examination attempt.',
      },
      {
        status: 404,
        expectedMessage: 'This examination attempt could not be found.',
      },
    ];

    for (const testCase of nonRetryableCases) {
      const authClock = new FakeClock();
      let authFailCalls = 0;
      let shouldFail = true;
      const refreshErrors: Array<{ status: number; message: string } | null> = [];
      const authController = new AttemptCountdownController({
        setTimeoutFn: authClock.setTimeout,
        clearTimeoutFn: authClock.clearTimeout,
        nowFn: () => authClock.now,
        refreshAttempt: async () => {
          authFailCalls += 1;
          if (shouldFail) {
            throw new ApiError(testCase.status, 'Request could not be authorized.');
          }
          return makeAttempt({ status: 'IN_PROGRESS', remainingSeconds: 5 });
        },
        onRemainingSecondsChange: () => {},
        onRefreshError: (error) => refreshErrors.push(error),
      });

      authController.activate();
      authController.syncFromAttempt(
        makeAttempt({ status: 'IN_PROGRESS', remainingSeconds: 1 }),
      );
      await authClock.advanceBy(1000);

      assert.equal(authFailCalls, 1);
      assert.equal(authClock.pendingCount(), 0);
      const surfacedError = refreshErrors[refreshErrors.length - 1];
      assert.ok(surfacedError, `HTTP ${testCase.status} must surface a refresh error`);
      assert.equal(surfacedError.status, testCase.status);
      assert.ok(surfacedError.message.startsWith(testCase.expectedMessage));

      if (testCase.status === 401) {
        // After the user restores authentication, a successful manual check
        // must clear the message and resume the authoritative countdown.
        shouldFail = false;
        await authController.triggerRefresh();
        assert.equal(authFailCalls, 2);
        assert.equal(refreshErrors[refreshErrors.length - 1], null);
        assert.equal(authClock.pendingCount(), 1);
      }

      authController.dispose();
    }
  }

  // Test 11 (Fix 3): dispose -> activate while an old refresh is pending
  console.log('Test 11: dispose -> activate while an old refresh is pending starts a fresh refresh and ignores old result');
  {
    const clock = new FakeClock();
    const oldDeferred = createDeferred<AttemptDetailRead>();
    const newDeferred = createDeferred<AttemptDetailRead>();
    let refreshCalls = 0;
    const observedSeconds: Array<number | null> = [];
    const terminalEvents: string[] = [];

    const controller = new AttemptCountdownController({
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      nowFn: () => clock.now,
      refreshAttempt: () => {
        refreshCalls += 1;
        return refreshCalls === 1 ? oldDeferred.promise : newDeferred.promise;
      },
      onRemainingSecondsChange: (s) => observedSeconds.push(s),
      onTerminalAttempt: (att) => terminalEvents.push(`${att.attempt_id}:${att.status}`),
    });

    controller.activate();
    controller.syncFromAttempt(makeAttempt({ attemptId: 'attempt-a', status: 'IN_PROGRESS', remainingSeconds: 1 }));
    await clock.advanceBy(1000);
    assert.equal(refreshCalls, 1);
    assert.equal(controller.isRefreshing(), true);

    // Dispose and immediately reactivate while old refresh is still pending
    controller.dispose();
    assert.equal(controller.isRefreshing(), false);
    controller.activate();
    assert.equal(controller.isRefreshing(), false);

    // Reactivated controller must issue a brand-new refresh, not coalesce onto the disposed one
    const newRefreshPromise = controller.triggerRefresh();
    assert.equal(refreshCalls, 2);
    assert.equal(controller.isRefreshing(), true);

    // Old pending refresh resolves with EXPIRED for attempt-a -> MUST be ignored completely
    oldDeferred.resolve(makeAttempt({ attemptId: 'attempt-a', status: 'EXPIRED', remainingSeconds: 0 }));
    await flushMicrotasks();

    assert.deepEqual(terminalEvents, [], 'Old refresh from disposed epoch must not fire terminal callback');
    assert.equal(controller.isTerminal(), false);
    assert.equal(controller.isRefreshing(), true, 'Old refresh must not disturb new in-flight refresh');

    // New refresh resolves with active attempt-b state
    newDeferred.resolve(makeAttempt({ attemptId: 'attempt-b', status: 'IN_PROGRESS', remainingSeconds: 5 }));
    await newRefreshPromise;

    assert.equal(controller.isRefreshing(), false);
    assert.equal(observedSeconds[observedSeconds.length - 1], 5);
    assert.equal(clock.pendingCount(), 1);
    controller.dispose();
  }

  // Test 12 (Fix 3): Old refresh rejection does not disturb newer synchronized state
  console.log('Test 12: Old refresh rejection arriving after newer server sync does not disturb timers or retry count');
  {
    const clock = new FakeClock();
    const staleDeferred = createDeferred<AttemptDetailRead>();
    let refreshCalls = 0;
    const observedSeconds: Array<number | null> = [];

    const controller = new AttemptCountdownController({
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      nowFn: () => clock.now,
      retryErrorIntervalMs: 1000,
      refreshAttempt: () => {
        refreshCalls += 1;
        if (refreshCalls === 1) return staleDeferred.promise;
        return Promise.resolve(makeAttempt({ status: 'EXPIRED', remainingSeconds: 0 }));
      },
      onRemainingSecondsChange: (s) => observedSeconds.push(s),
    });

    controller.activate();
    controller.syncFromAttempt(makeAttempt({ status: 'IN_PROGRESS', remainingSeconds: 1 }));
    await clock.advanceBy(1000);
    assert.equal(refreshCalls, 1);

    // Newer server state is synchronized while refresh #1 is still in flight
    controller.syncFromAttempt(makeAttempt({ status: 'IN_PROGRESS', remainingSeconds: 10 }));
    assert.equal(observedSeconds[observedSeconds.length - 1], 10);
    assert.equal(clock.pendingCount(), 1);
    assert.equal(controller.isRefreshing(), false);

    // Stale refresh #1 rejects with 401 (which would clearTimers() if unguarded)
    staleDeferred.reject(new ApiError(401, 'Unauthorized'));
    await flushMicrotasks();

    // Newer 10s countdown timer must still be alive and counting down normally
    assert.equal(clock.pendingCount(), 1, 'Stale 401 rejection must not clear newer tick timer');
    await clock.advanceBy(1000);
    assert.equal(observedSeconds[observedSeconds.length - 1], 9);

    // Also verify stale transient 503 rejection does not schedule a rogue retry poll
    const stale503 = createDeferred<AttemptDetailRead>();
    let calls503 = 0;
    const obs503: Array<number | null> = [];
    const ctrl503 = new AttemptCountdownController({
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      nowFn: () => clock.now,
      retryErrorIntervalMs: 1000,
      refreshAttempt: () => {
        calls503 += 1;
        if (calls503 === 1) return stale503.promise;
        return Promise.resolve(makeAttempt({ status: 'EXPIRED', remainingSeconds: 0 }));
      },
      onRemainingSecondsChange: (s) => obs503.push(s),
    });

    ctrl503.activate();
    ctrl503.syncFromAttempt(makeAttempt({ status: 'IN_PROGRESS', remainingSeconds: 1 }));
    await clock.advanceBy(1000);
    assert.equal(calls503, 1);

    ctrl503.syncFromAttempt(makeAttempt({ status: 'IN_PROGRESS', remainingSeconds: 10 }));
    stale503.reject(new ApiError(503, 'Bad Gateway'));
    await flushMicrotasks();

    // Advancing 1000ms must tick 10 -> 9 ONLY, without triggering a rogue error-retry refresh
    await clock.advanceBy(1000);
    assert.equal(calls503, 1, 'Stale 503 rejection must not schedule a retry refresh');
    assert.equal(obs503[obs503.length - 1], 9);
    ctrl503.dispose();
    controller.dispose();
  }

  // Test 13 (Fix 3): Old promise finally block does not clear a newer refresh promise
  console.log('Test 13: Old refresh settling/finally block must not clear newer active refresh');
  {
    const clock = new FakeClock();
    const firstDeferred = createDeferred<AttemptDetailRead>();
    const secondDeferred = createDeferred<AttemptDetailRead>();
    let refreshCalls = 0;

    const controller = new AttemptCountdownController({
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      nowFn: () => clock.now,
      refreshAttempt: () => {
        refreshCalls += 1;
        return refreshCalls === 1 ? firstDeferred.promise : secondDeferred.promise;
      },
      onRemainingSecondsChange: () => {},
    });

    controller.activate();
    const p1 = controller.triggerRefresh();
    assert.equal(refreshCalls, 1);
    assert.equal(controller.isRefreshing(), true);

    // Cycle dispose -> activate and start a newer refresh while first is still pending
    controller.dispose();
    controller.activate();
    const p2 = controller.triggerRefresh();
    assert.equal(refreshCalls, 2);
    assert.equal(controller.isRefreshing(), true);

    // Settle old refresh (both its catch and finally will execute)
    firstDeferred.reject(new Error('Network dropped'));
    await p1;
    await flushMicrotasks();

    // Newer refresh #2 MUST still be tracked as in-flight and deduplicate concurrent calls
    assert.equal(
      controller.isRefreshing(),
      true,
      'Old finally block must NOT clear newer refreshInFlight',
    );
    const coalescedP2 = controller.triggerRefresh();
    assert.equal(refreshCalls, 2, 'Concurrent call must coalesce onto newer refresh #2');

    secondDeferred.resolve(makeAttempt({ status: 'EXPIRED', remainingSeconds: 0 }));
    await Promise.all([p2, coalescedP2]);
    assert.equal(controller.isRefreshing(), false);
    assert.equal(controller.isTerminal(), true);
  }

  console.log('--- ALL COUNTDOWN & EXPIRY RELIABILITY TESTS PASSED SUCCESSFULLY ---');
}

runTests().catch((err) => {
  console.error('Countdown test suite failed:', err);
  process.exit(1);
});
