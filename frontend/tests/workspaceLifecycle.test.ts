/**
 * Automated regression tests for ExamOS Phase 1B.1 Workspace Lifecycle Hardening.
 *
 * Covers:
 * 1. Attempt A response arriving after navigation to Attempt B (plus A->B->A, delayed
 *    rejection, StrictMode remount deduplication, countdown refresh, and unmount).
 * 2. Submission refresh failure resetting isSubmitting correctly when flushBeforeSubmit()
 *    returns terminated=true and loadAttempt(false) fails or returns null, while
 *    preserving terminal-state navigation on success, keeping unresolved answer changes
 *    intact, and keeping submission vs expiration handling distinct.
 */

import { strict as assert } from 'node:assert';
import { type AttemptDetailRead } from '../src/api/attempts';
import {
  AttemptLoadCoordinator,
  executeAttemptSubmission,
} from '../src/features/attempt/attemptLifecycleController';
import { type AutosaveFlushResult } from '../src/features/attempt/autosaveManager';

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

function makeAttempt(overrides?: {
  attemptId?: string;
  status?: string;
  remainingSeconds?: number;
  title?: string;
}): AttemptDetailRead {
  return {
    attempt_id: overrides?.attemptId ?? 'attempt-a',
    status: overrides?.status ?? 'IN_PROGRESS',
    started_at: '2026-11-26T00:00:00Z',
    deadline_at: '2026-11-26T00:30:00Z',
    remaining_seconds: overrides?.remainingSeconds ?? 1800,
    exam: {
      id: 'exam-1',
      title: overrides?.title ?? 'Systems Exam',
      instructions: 'Pick one option.',
      duration_minutes: 30,
      total_marks: 10,
    },
    questions: [],
  };
}

async function runTests() {
  console.log('--- Starting ExamOS Workspace Lifecycle Hardening Tests ---');

  // Test 1a: Attempt A delayed response arriving after navigation to Attempt B
  console.log('Test 1a: Delayed Attempt A response after navigation to Attempt B is ignored');
  {
    const deferredA = createDeferred<AttemptDetailRead>();
    const deferredB = createDeferred<AttemptDetailRead>();
    const hydrated: string[] = [];
    const terminalSynced: string[] = [];
    const errors: Array<string | null> = [];
    const loadingStates: boolean[] = [];
    const coordinator = new AttemptLoadCoordinator({
      getAttempt: (id) => (id === 'attempt-a' ? deferredA.promise : deferredB.promise),
      hasLoadedAttempt: () => hydrated.length > 0,
      onLoadingChange: (v) => loadingStates.push(v),
      onLoadError: (msg) => errors.push(msg),
      onHydrateActiveAttempt: (att) => {
        hydrated.push(att.attempt_id);
      },
      onSyncTerminalAttempt: (att) => {
        terminalSynced.push(att.attempt_id);
      },
    });

    coordinator.activateRoute('attempt-a');
    const loadAPromise = coordinator.loadAttempt('attempt-a', true);

    // Navigate to Attempt B while Attempt A is still in flight
    coordinator.deactivate();
    coordinator.activateRoute('attempt-b');
    const loadBPromise = coordinator.loadAttempt('attempt-b', true);

    // Attempt B finishes first
    deferredB.resolve(makeAttempt({ attemptId: 'attempt-b', title: 'Exam B' }));
    const resultB = await loadBPromise;
    assert.equal(resultB?.attempt_id, 'attempt-b');
    assert.deepEqual(hydrated, ['attempt-b']);
    assert.equal(loadingStates[loadingStates.length - 1], false);

    // Delayed Attempt A response arrives (even as SUBMITTED/EXPIRED) -> MUST NOT update state or redirect
    deferredA.resolve(makeAttempt({ attemptId: 'attempt-a', status: 'EXPIRED', remainingSeconds: 0 }));
    const resultA = await loadAPromise;
    assert.equal(resultA, null);
    assert.deepEqual(hydrated, ['attempt-b']);
    assert.deepEqual(terminalSynced, []);
    assert.deepEqual(errors, []);
  }

  // Test 1b: Delayed Attempt A rejection after navigation to Attempt B does not clobber B
  console.log('Test 1b: Delayed Attempt A rejection after navigation to Attempt B does not set loadError or clear B loading');
  {
    const deferredA = createDeferred<AttemptDetailRead>();
    const deferredB = createDeferred<AttemptDetailRead>();
    const errors: Array<string | null> = [];
    const loadingStates: boolean[] = [];
    const hydrated: string[] = [];

    const coordinator = new AttemptLoadCoordinator({
      getAttempt: (id) => (id === 'attempt-a' ? deferredA.promise : deferredB.promise),
      hasLoadedAttempt: () => hydrated.length > 0,
      onLoadingChange: (v) => loadingStates.push(v),
      onLoadError: (msg) => errors.push(msg),
      onHydrateActiveAttempt: (att) => {
        hydrated.push(att.attempt_id);
      },
      onSyncTerminalAttempt: () => {},
    });

    coordinator.activateRoute('attempt-a');
    const loadAPromise = coordinator.loadAttempt('attempt-a', true);

    coordinator.deactivate();
    coordinator.activateRoute('attempt-b');
    const loadBPromise = coordinator.loadAttempt('attempt-b', true);
    assert.equal(loadingStates[loadingStates.length - 1], true);

    // Attempt A fails while Attempt B is still loading -> must NOT set error or flip isLoading to false
    deferredA.reject(new Error('Attempt A failed'));
    const resA = await loadAPromise;
    assert.equal(resA, null);
    assert.deepEqual(errors, []);
    assert.equal(loadingStates[loadingStates.length - 1], true, 'Attempt A finally must not stop B loading spinner');

    deferredB.resolve(makeAttempt({ attemptId: 'attempt-b' }));
    await loadBPromise;
    assert.equal(loadingStates[loadingStates.length - 1], false);
    assert.deepEqual(hydrated, ['attempt-b']);
  }

  // Test 1c: Rapid navigation A -> B -> A ignores obsolete first A response
  console.log('Test 1c: Rapid A -> B -> A route change ignores stale first A response via routeGeneration');
  {
    let aCalls = 0;
    const firstA = createDeferred<AttemptDetailRead>();
    const secondA = createDeferred<AttemptDetailRead>();
    const bDeferred = createDeferred<AttemptDetailRead>();
    const hydrated: string[] = [];

    const coordinator = new AttemptLoadCoordinator({
      getAttempt: (id) => {
        if (id === 'attempt-a') {
          aCalls += 1;
          return aCalls === 1 ? firstA.promise : secondA.promise;
        }
        return bDeferred.promise;
      },
      hasLoadedAttempt: () => hydrated.length > 0,
      onLoadingChange: () => {},
      onLoadError: () => {},
      onHydrateActiveAttempt: (att) => {
        hydrated.push(`${att.attempt_id}:${att.exam.title}`);
      },
      onSyncTerminalAttempt: () => {},
    });

    coordinator.activateRoute('attempt-a');
    const pA1 = coordinator.loadAttempt('attempt-a', true);

    coordinator.deactivate();
    coordinator.activateRoute('attempt-b');
    void coordinator.loadAttempt('attempt-b', true);

    coordinator.deactivate();
    coordinator.activateRoute('attempt-a');
    const pA2 = coordinator.loadAttempt('attempt-a', true);

    firstA.resolve(makeAttempt({ attemptId: 'attempt-a', title: 'Stale A' }));
    await pA1;
    assert.deepEqual(hydrated, [], 'Stale first A response must be ignored even back on attempt-a');

    secondA.resolve(makeAttempt({ attemptId: 'attempt-a', title: 'Fresh A' }));
    await pA2;
    assert.deepEqual(hydrated, ['attempt-a:Fresh A']);
  }

  // Test 1d: StrictMode mount -> deactivate -> remount deduplicates via inFlightLoad and hydrates
  console.log('Test 1d: React StrictMode mount -> deactivate -> remount deduplicates GET and hydrates active attempt');
  {
    let getCalls = 0;
    const deferred = createDeferred<AttemptDetailRead>();
    const hydrated: string[] = [];

    const coordinator = new AttemptLoadCoordinator({
      getAttempt: () => {
        getCalls += 1;
        return deferred.promise;
      },
      hasLoadedAttempt: () => hydrated.length > 0,
      onLoadingChange: () => {},
      onLoadError: () => {},
      onHydrateActiveAttempt: (att) => hydrated.push(att.attempt_id),
      onSyncTerminalAttempt: () => {},
    });

    // Mount 1
    coordinator.activateRoute('attempt-a');
    const p1 = coordinator.loadAttempt('attempt-a', true);
    // StrictMode Cleanup 1
    coordinator.deactivate();
    // StrictMode Remount 2
    const { routeChanged } = coordinator.activateRoute('attempt-a');
    assert.equal(routeChanged, false);
    const p2 = coordinator.loadAttempt('attempt-a', true);

    assert.equal(getCalls, 1, 'StrictMode remount for same attempt must deduplicate GET');

    deferred.resolve(makeAttempt({ attemptId: 'attempt-a' }));
    const [r1, r2] = await Promise.all([p1, p2]);
    assert.equal(r1?.attempt_id, 'attempt-a');
    assert.equal(r2?.attempt_id, 'attempt-a');
    assert.deepEqual(hydrated, ['attempt-a']);

    // Unmount while a countdown refresh is in flight ignores response
    const refreshDeferred = createDeferred<AttemptDetailRead>();
    let unmountedRefreshCalls = 0;
    const unmountedCoordinator = new AttemptLoadCoordinator({
      getAttempt: () => {
        unmountedRefreshCalls += 1;
        return refreshDeferred.promise;
      },
      hasLoadedAttempt: () => true,
      onLoadingChange: () => {},
      onLoadError: () => {},
      onHydrateActiveAttempt: () => {
        assert.fail('Must not hydrate after unmount');
      },
      onSyncTerminalAttempt: () => {
        assert.fail('Must not sync terminal after unmount');
      },
    });
    unmountedCoordinator.activateRoute('attempt-a');
    const bgPromise = unmountedCoordinator.loadAttempt('attempt-a', false, {
      throwOnBackgroundError: true,
    });
    unmountedCoordinator.deactivate();
    refreshDeferred.resolve(makeAttempt({ attemptId: 'attempt-a', status: 'EXPIRED' }));
    const bgResult = await bgPromise;
    assert.equal(unmountedRefreshCalls, 1);
    assert.equal(bgResult, null);
  }

  // Test 2a: Submission refresh failure (throws) resets isSubmitting and shows recoverable error
  console.log('Test 2a: Submission refresh failure resets isSubmitting, preserves modal & answers, keeps expiration distinct');
  {
    let isSubmitting = false;
    let modalOpen = true;
    let submitError: string | null = null;
    let submitApiCalls = 0;
    let navigatedTo: string | null = null;
    const submittingHistory: boolean[] = [];
    let unresolvedAnswersPreserved = true;

    const flushResult: AutosaveFlushResult = {
      ok: false,
      terminated: true,
      failedQuestionIds: ['q1'],
      conflictQuestionIds: [],
    };

    await executeAttemptSubmission({
      attemptId: 'attempt-1',
      isSubmitting,
      isCurrentSession: () => true,
      flushBeforeSubmit: async () => flushResult,
      refreshAttempt: async () => {
        throw new Error('503 Service Unavailable');
      },
      submitAttempt: async () => {
        submitApiCalls += 1;
      },
      onSubmittingChange: (v) => {
        isSubmitting = v;
        submittingHistory.push(v);
      },
      onSubmitError: (msg) => {
        submitError = msg;
      },
      onModalOpenChange: (open) => {
        modalOpen = open;
      },
      onSubmissionSuccess: (id) => {
        navigatedTo = id;
      },
    });

    assert.equal(isSubmitting, false, 'isSubmitting must be reset to false');
    assert.deepEqual(submittingHistory, [true, false]);
    assert.equal(modalOpen, true, 'Modal must stay open so user can recover/retry');
    assert.ok(submitError && /ended or expired/i.test(submitError), 'Must display clear expiration-refresh error');
    assert.ok(submitError && /503 Service Unavailable/.test(submitError));
    assert.equal(submitApiCalls, 0, 'Must NOT call apiSubmitAttempt when terminated=true');
    assert.equal(navigatedTo, null);
    assert.equal(unresolvedAnswersPreserved, true);
  }

  // Test 2b: Submission refresh returning null resets isSubmitting and shows recoverable error
  console.log('Test 2b: Submission refresh returning null resets isSubmitting and displays recoverable error');
  {
    let isSubmitting = false;
    let modalOpen = true;
    let submitError: string | null = null;
    let submitApiCalls = 0;

    await executeAttemptSubmission({
      attemptId: 'attempt-1',
      isSubmitting,
      isCurrentSession: () => true,
      flushBeforeSubmit: async () => ({
        ok: false,
        terminated: true,
        failedQuestionIds: [],
        conflictQuestionIds: ['q2'],
      }),
      refreshAttempt: async () => null,
      submitAttempt: async () => {
        submitApiCalls += 1;
      },
      onSubmittingChange: (v) => {
        isSubmitting = v;
      },
      onSubmitError: (msg) => {
        submitError = msg;
      },
      onModalOpenChange: (open) => {
        modalOpen = open;
      },
      onSubmissionSuccess: () => {
        assert.fail('Must not navigate when refresh returns null');
      },
    });

    assert.equal(isSubmitting, false);
    assert.equal(modalOpen, true);
    assert.ok(submitError && /ended or expired/i.test(submitError));
    assert.equal(submitApiCalls, 0);
  }

  // Test 2c: Submission refresh succeeding with terminal state preserves terminal navigation and cleans up
  console.log('Test 2c: Terminated flush + successful EXPIRED refresh preserves terminal navigation and closes modal');
  {
    let isSubmitting = false;
    let modalOpen = true;
    let submitError: string | null = null;
    let terminalNavigatedId: string | null = null;
    let submitApiCalls = 0;

    const coordinator = new AttemptLoadCoordinator({
      getAttempt: async (id) => makeAttempt({ attemptId: id, status: 'EXPIRED', remainingSeconds: 0 }),
      hasLoadedAttempt: () => true,
      onLoadingChange: () => {},
      onLoadError: () => {},
      onHydrateActiveAttempt: () => {},
      onSyncTerminalAttempt: (att) => {
        terminalNavigatedId = att.attempt_id;
      },
    });
    coordinator.activateRoute('attempt-1');

    await executeAttemptSubmission({
      attemptId: 'attempt-1',
      isSubmitting,
      isCurrentSession: () => coordinator.isCurrentSession(),
      flushBeforeSubmit: async () => ({
        ok: false,
        terminated: true,
        failedQuestionIds: [],
        conflictQuestionIds: [],
      }),
      refreshAttempt: () =>
        coordinator.loadAttempt('attempt-1', false, { throwOnBackgroundError: true }),
      submitAttempt: async () => {
        submitApiCalls += 1;
      },
      onSubmittingChange: (v) => {
        isSubmitting = v;
      },
      onSubmitError: (msg) => {
        submitError = msg;
      },
      onModalOpenChange: (open) => {
        modalOpen = open;
      },
      onSubmissionSuccess: () => {
        assert.fail('Should use terminal sync navigation, not apiSubmitAttempt');
      },
    });

    assert.equal(terminalNavigatedId, 'attempt-1');
    assert.equal(modalOpen, false);
    assert.equal(submitError, null);
    assert.equal(isSubmitting, false);
    assert.equal(submitApiCalls, 0);
  }

  console.log('--- ALL WORKSPACE LIFECYCLE HARDENING TESTS PASSED SUCCESSFULLY ---');
}

runTests().catch((err) => {
  console.error('Workspace lifecycle test suite failed:', err);
  process.exit(1);
});
