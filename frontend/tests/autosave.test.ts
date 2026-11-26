/**
 * Automated unit and behavioral tests for ExamOS Phase 1A Autosave Reliability.
 *
 * Covers:
 * 1. Rapid selection of Option A followed by Option B (debounce & coalescing).
 * 2. Only the final intended selection being persisted (across debounce & in-flight edits).
 * 3. Two different questions saving independently.
 * 4. An older server response not reverting a newer optimistic selection.
 * 5. HTTP 409 reconciliation (backend error parsing, already-applied retry, genuine conflict).
 * 6. A failed save and explicit retry (server reconciliation before retry on ambiguous failure).
 * 7. Pending writes being flushed before exam submission.
 * 8. No accidental answer clearing when retrying.
 */

import { strict as assert } from 'node:assert';
import {
  apiSaveAnswer,
  RevisionConflictError,
  type AnswerSaveRequest,
  type AnswerSaveResponse,
  type AttemptDetailRead,
} from '../src/api/attempts';
import { ApiError } from '../src/api/auth';
import { AttemptAutosaveManager } from '../src/features/attempt/autosaveManager';
import { flushAttemptBeforeNavigation } from '../src/features/attempt/attemptLifecycleController';

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
  status?: string;
  q1Answer?: { selected_option_id: string | null; marked_for_review: boolean; revision: number };
  q2Answer?: { selected_option_id: string | null; marked_for_review: boolean; revision: number };
}): AttemptDetailRead {
  return {
    attempt_id: 'attempt-1',
    status: overrides?.status ?? 'IN_PROGRESS',
    started_at: '2026-11-26T00:00:00Z',
    deadline_at: '2026-11-26T00:30:00Z',
    remaining_seconds: 1800,
    exam: {
      id: 'exam-1',
      title: 'Systems Exam',
      instructions: 'Pick one option.',
      duration_minutes: 30,
      total_marks: 10,
    },
    questions: [
      {
        exam_question_id: 'q1',
        prompt: 'Question 1?',
        marks: 5,
        display_order: 1,
        options: [
          { id: 'q1-opt-a', text: 'Option A', display_order: 1 },
          { id: 'q1-opt-b', text: 'Option B', display_order: 2 },
          { id: 'q1-opt-c', text: 'Option C', display_order: 3 },
        ],
        answer: overrides?.q1Answer ?? {
          selected_option_id: null,
          marked_for_review: false,
          revision: 0,
        },
      },
      {
        exam_question_id: 'q2',
        prompt: 'Question 2?',
        marks: 5,
        display_order: 2,
        options: [
          { id: 'q2-opt-a', text: 'Option 2A', display_order: 1 },
          { id: 'q2-opt-b', text: 'Option 2B', display_order: 2 },
        ],
        answer: overrides?.q2Answer ?? {
          selected_option_id: null,
          marked_for_review: false,
          revision: 0,
        },
      },
    ],
  };
}

async function runTests() {
  console.log('--- Starting ExamOS Autosave Reliability Tests ---');

  // Test 1 & 2: Rapid selection of Option A followed by Option B -> only final intended selection persisted
  console.log('Test 1 & 2: Rapid selection Option A then Option B coalesces and persists only Option B');
  {
    const clock = new FakeClock();
    const saveCalls: Array<{ qId: string; payload: AnswerSaveRequest }> = [];
    let mutCounter = 0;

    const manager = new AttemptAutosaveManager({
      debounceMs: 300,
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      generateMutationId: () => `mut-${++mutCounter}`,
      getAttempt: async () => makeAttempt(),
      saveAnswer: async (_attId, qId, payload) => {
        saveCalls.push({ qId, payload });
        return {
          selected_option_id: payload.selected_option_id,
          marked_for_review: payload.marked_for_review,
          revision: payload.expected_revision + 1,
          saved_at: '2026-11-26T00:01:00Z',
        };
      },
    });

    manager.hydrateFromAttempt(makeAttempt());

    manager.selectOption('q1', 'q1-opt-a');
    assert.equal(manager.getSnapshot().q1.local.selected_option_id, 'q1-opt-a');
    assert.equal(manager.getSnapshot().q1.status, 'pending');

    await clock.advanceBy(100);
    assert.equal(saveCalls.length, 0, 'Should not send request before debounce elapses');

    manager.selectOption('q1', 'q1-opt-b');
    assert.equal(manager.getSnapshot().q1.local.selected_option_id, 'q1-opt-b');
    assert.equal(manager.getSnapshot().q1.status, 'pending');

    // 250ms after second click -> still debouncing (reset timer)
    await clock.advanceBy(250);
    assert.equal(saveCalls.length, 0, 'Debounce timer should have reset on second selection');

    // Remaining 50ms -> fires once with Option B only
    await clock.advanceBy(50);
    assert.equal(saveCalls.length, 1, 'Only one PUT should be sent');
    assert.equal(saveCalls[0].qId, 'q1');
    assert.equal(saveCalls[0].payload.selected_option_id, 'q1-opt-b');
    assert.equal(saveCalls[0].payload.expected_revision, 0);

    const snap = manager.getSnapshot().q1;
    assert.equal(snap.status, 'saved');
    assert.equal(snap.local.selected_option_id, 'q1-opt-b');
    assert.equal(snap.server.selected_option_id, 'q1-opt-b');
    assert.equal(snap.server.revision, 1);

    manager.dispose();
  }

  // Test 2b: Coalescing across an in-flight request (A in flight, rapid B then C -> only A then C sent)
  console.log('Test 2b: Rapid edits during an in-flight save coalesce and serialize revisions');
  {
    const clock = new FakeClock();
    const saveCalls: Array<{ payload: AnswerSaveRequest; deferred: Deferred<AnswerSaveResponse> }> = [];

    const manager = new AttemptAutosaveManager({
      debounceMs: 300,
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      getAttempt: async () => makeAttempt(),
      saveAnswer: (_attId, _qId, payload) => {
        const deferred = createDeferred<AnswerSaveResponse>();
        saveCalls.push({ payload, deferred });
        return deferred.promise;
      },
    });
    manager.hydrateFromAttempt(makeAttempt());

    manager.selectOption('q1', 'q1-opt-a');
    await clock.advanceBy(300);
    assert.equal(saveCalls.length, 1);
    assert.equal(saveCalls[0].payload.selected_option_id, 'q1-opt-a');
    assert.equal(saveCalls[0].payload.expected_revision, 0);
    assert.equal(manager.getSnapshot().q1.status, 'saving');

    // While A is in flight, rapidly click B then C
    manager.selectOption('q1', 'q1-opt-b');
    await clock.advanceBy(50);
    manager.selectOption('q1', 'q1-opt-c');
    await clock.advanceBy(350);

    // Must NOT send concurrent PUT with expected_revision=0
    assert.equal(saveCalls.length, 1, 'Must serialize per question and not send concurrent PUTs');
    assert.equal(manager.getSnapshot().q1.local.selected_option_id, 'q1-opt-c');

    // Resolve A (revision 0 -> 1)
    saveCalls[0].deferred.resolve({
      selected_option_id: 'q1-opt-a',
      marked_for_review: false,
      revision: 1,
      saved_at: '2026-11-26T00:01:01Z',
    });
    await flushMicrotasks();

    // Now C should be sent with expected_revision=1 (B was skipped/coalesced)
    assert.equal(saveCalls.length, 2);
    assert.equal(saveCalls[1].payload.selected_option_id, 'q1-opt-c');
    assert.equal(saveCalls[1].payload.expected_revision, 1);

    saveCalls[1].deferred.resolve({
      selected_option_id: 'q1-opt-c',
      marked_for_review: false,
      revision: 2,
      saved_at: '2026-11-26T00:01:02Z',
    });
    await flushMicrotasks();

    assert.equal(manager.getSnapshot().q1.status, 'saved');
    assert.equal(manager.getSnapshot().q1.server.revision, 2);
    assert.equal(manager.getSnapshot().q1.local.selected_option_id, 'q1-opt-c');

    manager.dispose();
  }

  // Test 3: Two different questions saving independently
  console.log('Test 3: Two different questions save independently');
  {
    const clock = new FakeClock();
    const q1Deferred = createDeferred<AnswerSaveResponse>();
    const q2Deferred = createDeferred<AnswerSaveResponse>();
    const calls: string[] = [];

    const manager = new AttemptAutosaveManager({
      debounceMs: 300,
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      getAttempt: async () => makeAttempt(),
      saveAnswer: (_attId, qId) => {
        calls.push(qId);
        return qId === 'q1' ? q1Deferred.promise : q2Deferred.promise;
      },
    });
    manager.hydrateFromAttempt(makeAttempt());

    manager.selectOption('q1', 'q1-opt-a');
    manager.selectOption('q2', 'q2-opt-b');
    await clock.advanceBy(300);

    assert.deepEqual(calls.sort(), ['q1', 'q2']);
    assert.equal(manager.getSnapshot().q1.status, 'saving');
    assert.equal(manager.getSnapshot().q2.status, 'saving');

    // Q2 finishes first while Q1 is still slow/in-flight
    q2Deferred.resolve({
      selected_option_id: 'q2-opt-b',
      marked_for_review: false,
      revision: 1,
      saved_at: '2026-11-26T00:01:00Z',
    });
    await flushMicrotasks();

    assert.equal(manager.getSnapshot().q2.status, 'saved');
    assert.equal(manager.getSnapshot().q2.server.revision, 1);
    assert.equal(manager.getSnapshot().q1.status, 'saving');

    q1Deferred.resolve({
      selected_option_id: 'q1-opt-a',
      marked_for_review: false,
      revision: 1,
      saved_at: '2026-11-26T00:01:01Z',
    });
    await flushMicrotasks();

    assert.equal(manager.getSnapshot().q1.status, 'saved');
    assert.equal(manager.getSnapshot().q1.server.revision, 1);

    manager.dispose();
  }

  // Test 4: Older server response does not revert newer optimistic selection
  console.log('Test 4: Slow earlier response never reverts newer optimistic selection');
  {
    const clock = new FakeClock();
    const firstSave = createDeferred<AnswerSaveResponse>();
    const secondSave = createDeferred<AnswerSaveResponse>();
    let callCount = 0;

    const manager = new AttemptAutosaveManager({
      debounceMs: 300,
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      getAttempt: async () => makeAttempt(),
      saveAnswer: () => {
        callCount += 1;
        return callCount === 1 ? firstSave.promise : secondSave.promise;
      },
    });
    manager.hydrateFromAttempt(makeAttempt());

    manager.selectOption('q1', 'q1-opt-a');
    await clock.advanceBy(300);
    assert.equal(callCount, 1);

    // Student selects Option B while Option A's request is still in flight
    manager.selectOption('q1', 'q1-opt-b');
    assert.equal(manager.getSnapshot().q1.local.selected_option_id, 'q1-opt-b');
    assert.equal(manager.getSnapshot().q1.status, 'pending');

    // Older server response for Option A arrives
    firstSave.resolve({
      selected_option_id: 'q1-opt-a',
      marked_for_review: false,
      revision: 1,
      saved_at: '2026-11-26T00:01:00Z',
    });
    await flushMicrotasks();

    // UI selection MUST still be Option B, and status must NOT be 'saved'
    assert.equal(
      manager.getSnapshot().q1.local.selected_option_id,
      'q1-opt-b',
      'Older Option A response must never revert newer Option B selection',
    );
    assert.notEqual(manager.getSnapshot().q1.status, 'saved');

    // Advance remaining debounce for Option B -> second save fires with expected_revision 1
    await clock.advanceBy(300);
    assert.equal(callCount, 2);

    secondSave.resolve({
      selected_option_id: 'q1-opt-b',
      marked_for_review: false,
      revision: 2,
      saved_at: '2026-11-26T00:01:02Z',
    });
    await flushMicrotasks();

    assert.equal(manager.getSnapshot().q1.local.selected_option_id, 'q1-opt-b');
    assert.equal(manager.getSnapshot().q1.server.revision, 2);
    assert.equal(manager.getSnapshot().q1.status, 'saved');

    manager.dispose();
  }

  // Test 5: HTTP 409 reconciliation (API parser + already-applied + genuine concurrent conflict)
  console.log('Test 5a: apiSaveAnswer extracts backend { error: { code: ANSWER_REVISION_CONFLICT } } into RevisionConflictError');
  {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async () =>
      new Response(
        JSON.stringify({
          error: {
            code: 'ANSWER_REVISION_CONFLICT',
            message: 'Stale answer revision.',
            details: {
              selected_option_id: 'q1-opt-c',
              marked_for_review: true,
              revision: 2,
              saved_at: '2026-11-26T00:02:00Z',
            },
          },
        }),
        { status: 409, headers: { 'Content-Type': 'application/json' } },
      )) as typeof fetch;

    try {
      await assert.rejects(
        () =>
          apiSaveAnswer(
            'attempt-1',
            'q1',
            { selected_option_id: 'q1-opt-b', marked_for_review: false, expected_revision: 1 },
            'csrf-token',
          ),
        (err: unknown) => {
          assert.ok(err instanceof RevisionConflictError, 'Must throw RevisionConflictError');
          assert.equal(err.canonicalState.selected_option_id, 'q1-opt-c');
          assert.equal(err.canonicalState.marked_for_review, true);
          assert.equal(err.canonicalState.revision, 2);
          return true;
        },
      );
    } finally {
      globalThis.fetch = originalFetch;
    }
  }

  console.log('Test 5b: HTTP 409 where canonical state already matches intended mutation at expected_revision+1 resolves as saved');
  {
    const clock = new FakeClock();
    const manager = new AttemptAutosaveManager({
      debounceMs: 300,
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      getAttempt: async () => makeAttempt(),
      saveAnswer: async () => {
        throw new RevisionConflictError('Stale revision', {
          selected_option_id: 'q1-opt-b',
          marked_for_review: false,
          revision: 1,
          saved_at: '2026-11-26T00:02:00Z',
        });
      },
    });
    manager.hydrateFromAttempt(makeAttempt());

    manager.selectOption('q1', 'q1-opt-b');
    await clock.advanceBy(300);

    const snap = manager.getSnapshot().q1;
    assert.equal(snap.status, 'saved');
    assert.equal(snap.server.revision, 1);
    assert.equal(snap.local.selected_option_id, 'q1-opt-b');

    manager.dispose();
  }

  console.log('Test 5c: HTTP 409 genuine concurrent modification preserves unsaved intent and allows explicit resolution');
  {
    const clock = new FakeClock();
    const saveCalls: AnswerSaveRequest[] = [];
    let shouldConflict = true;

    const manager = new AttemptAutosaveManager({
      debounceMs: 300,
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      getAttempt: async () => makeAttempt(),
      saveAnswer: async (_attId, _qId, payload) => {
        saveCalls.push(payload);
        if (shouldConflict) {
          throw new RevisionConflictError('Modified by another tab', {
            selected_option_id: 'q1-opt-c',
            marked_for_review: true,
            revision: 1,
            saved_at: '2026-11-26T00:02:00Z',
          });
        }
        return {
          selected_option_id: payload.selected_option_id,
          marked_for_review: payload.marked_for_review,
          revision: payload.expected_revision + 1,
          saved_at: '2026-11-26T00:02:05Z',
        };
      },
    });
    manager.hydrateFromAttempt(makeAttempt());

    // Student selects Option B locally
    manager.selectOption('q1', 'q1-opt-b');
    await clock.advanceBy(300);

    // Must enter 'conflict', preserve Option B locally, and NOT overwrite server Option C
    const conflictSnap = manager.getSnapshot().q1;
    assert.equal(conflictSnap.status, 'conflict');
    assert.equal(conflictSnap.local.selected_option_id, 'q1-opt-b', 'Latest unsaved intent must be preserved');
    assert.equal(conflictSnap.conflictServerState?.selected_option_id, 'q1-opt-c');
    assert.equal(conflictSnap.conflictServerState?.revision, 1);
    assert.equal(saveCalls.length, 1, 'Must not blindly overwrite another session');

    // Now student explicitly chooses "Save My Selection"
    shouldConflict = false;
    await manager.resolveConflictWithLocal('q1');

    assert.equal(saveCalls.length, 2);
    assert.equal(saveCalls[1].selected_option_id, 'q1-opt-b');
    assert.equal(saveCalls[1].expected_revision, 1);
    assert.equal(manager.getSnapshot().q1.status, 'saved');
    assert.equal(manager.getSnapshot().q1.server.revision, 2);

    // Also verify "Use Server Answer" path on another conflict
    shouldConflict = true;
    manager.selectOption('q1', 'q1-opt-a');
    await clock.advanceBy(300);
    assert.equal(manager.getSnapshot().q1.status, 'conflict');
    assert.equal(manager.getSnapshot().q1.local.selected_option_id, 'q1-opt-a');

    manager.resolveConflictWithServer('q1');
    const resolvedSnap = manager.getSnapshot().q1;
    assert.equal(resolvedSnap.status, 'saved');
    assert.equal(resolvedSnap.local.selected_option_id, 'q1-opt-c');
    assert.equal(resolvedSnap.local.marked_for_review, true);

    manager.dispose();
  }

  // Test 6: Failed save and safe explicit retry (reconcile via GET first)
  console.log('Test 6a: Ambiguous 5xx/network failure reconciles via GET before safe retry');
  {
    const clock = new FakeClock();
    const events: string[] = [];
    let failPut = true;

    const manager = new AttemptAutosaveManager({
      debounceMs: 300,
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      getAttempt: async () => {
        events.push('GET');
        // Server still at revision 0 -> original PUT did not commit
        return makeAttempt({
          q1Answer: { selected_option_id: null, marked_for_review: false, revision: 0 },
        });
      },
      saveAnswer: async (_attId, _qId, payload) => {
        events.push(`PUT:rev=${payload.expected_revision}:opt=${payload.selected_option_id}`);
        if (failPut) {
          throw new ApiError(502, 'Bad Gateway');
        }
        return {
          selected_option_id: payload.selected_option_id,
          marked_for_review: payload.marked_for_review,
          revision: payload.expected_revision + 1,
          saved_at: '2026-11-26T00:03:00Z',
        };
      },
    });
    manager.hydrateFromAttempt(makeAttempt());

    manager.selectOption('q1', 'q1-opt-b');
    await clock.advanceBy(300);

    assert.equal(manager.getSnapshot().q1.status, 'failed');
    assert.equal(manager.getSnapshot().q1.local.selected_option_id, 'q1-opt-b');
    assert.deepEqual(events, ['PUT:rev=0:opt=q1-opt-b']);

    // Explicit retry reconciles with GET first, then sends PUT
    failPut = false;
    await manager.retryQuestion('q1');

    assert.deepEqual(events, ['PUT:rev=0:opt=q1-opt-b', 'GET', 'PUT:rev=0:opt=q1-opt-b']);
    assert.equal(manager.getSnapshot().q1.status, 'saved');
    assert.equal(manager.getSnapshot().q1.server.revision, 1);

    manager.dispose();
  }

  console.log('Test 6b: Ambiguous failure where server actually committed resolves via GET without duplicate PUT');
  {
    const clock = new FakeClock();
    const events: string[] = [];

    const manager = new AttemptAutosaveManager({
      debounceMs: 300,
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      getAttempt: async () => {
        events.push('GET');
        // Server already committed Option B at revision 1 before response dropped
        return makeAttempt({
          q1Answer: { selected_option_id: 'q1-opt-b', marked_for_review: false, revision: 1 },
        });
      },
      saveAnswer: async (_attId, _qId, payload) => {
        events.push(`PUT:rev=${payload.expected_revision}`);
        throw new TypeError('NetworkError when attempting to fetch resource');
      },
    });
    manager.hydrateFromAttempt(makeAttempt());

    manager.selectOption('q1', 'q1-opt-b');
    await clock.advanceBy(300);
    assert.equal(manager.getSnapshot().q1.status, 'failed');

    await manager.retryQuestion('q1');
    assert.deepEqual(events, ['PUT:rev=0', 'GET'], 'Must NOT send duplicate PUT when GET confirms commit');
    assert.equal(manager.getSnapshot().q1.status, 'saved');
    assert.equal(manager.getSnapshot().q1.server.revision, 1);
    assert.equal(manager.getSnapshot().q1.local.selected_option_id, 'q1-opt-b');

    manager.dispose();
  }

  // Test 7: Pending writes flushed before exam submission
  console.log('Test 7: Pending debounced and in-flight writes are flushed before exam submission');
  {
    const clock = new FakeClock();
    const savedOrder: string[] = [];
    const q2Deferred = createDeferred<AnswerSaveResponse>();

    const manager = new AttemptAutosaveManager({
      debounceMs: 300,
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      getAttempt: async () => makeAttempt(),
      saveAnswer: async (_attId, qId, payload) => {
        if (qId === 'q2') {
          const res = await q2Deferred.promise;
          savedOrder.push(`q2:${payload.marked_for_review}`);
          return res;
        }
        savedOrder.push(`q1:${payload.selected_option_id}`);
        return {
          selected_option_id: payload.selected_option_id,
          marked_for_review: payload.marked_for_review,
          revision: payload.expected_revision + 1,
          saved_at: '2026-11-26T00:04:00Z',
        };
      },
    });
    manager.hydrateFromAttempt(makeAttempt());

    // Q2 is already in flight
    manager.toggleReview('q2');
    await clock.advanceBy(300);
    assert.equal(manager.getSnapshot().q2.status, 'saving');

    // Q1 is still inside the 300ms debounce window when student submits!
    manager.selectOption('q1', 'q1-opt-a');
    assert.equal(manager.getSnapshot().q1.status, 'pending');
    assert.equal(clock.pendingCount(), 1);

    const flushPromise = manager.flushBeforeSubmit();
    await flushMicrotasks();

    // Q1's debounced save should have flushed immediately without waiting 300ms
    assert.equal(clock.pendingCount(), 0);
    assert.ok(savedOrder.includes('q1:q1-opt-a'));

    // Finish Q2 in-flight save
    q2Deferred.resolve({
      selected_option_id: null,
      marked_for_review: true,
      revision: 1,
      saved_at: '2026-11-26T00:04:01Z',
    });

    const flushResult = await flushPromise;
    assert.equal(flushResult.ok, true);
    assert.equal(flushResult.terminated, false);
    assert.deepEqual(flushResult.failedQuestionIds, []);
    assert.deepEqual(flushResult.conflictQuestionIds, []);
    assert.equal(manager.getSnapshot().q1.status, 'saved');
    assert.equal(manager.getSnapshot().q2.status, 'saved');

    manager.dispose();
  }

  // Test 8: No accidental answer clearing when retrying
  console.log('Test 8: Retrying a failed save never toggles or clears the selected option');
  {
    const clock = new FakeClock();
    const sentPayloads: AnswerSaveRequest[] = [];
    let attemptNum = 0;

    const manager = new AttemptAutosaveManager({
      debounceMs: 300,
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      getAttempt: async () =>
        makeAttempt({
          q1Answer: { selected_option_id: null, marked_for_review: false, revision: 0 },
        }),
      saveAnswer: async (_attId, _qId, payload) => {
        attemptNum += 1;
        sentPayloads.push(payload);
        if (attemptNum <= 2) {
          throw new ApiError(500, 'Server temporarily unavailable');
        }
        return {
          selected_option_id: payload.selected_option_id,
          marked_for_review: payload.marked_for_review,
          revision: payload.expected_revision + 1,
          saved_at: '2026-11-26T00:05:00Z',
        };
      },
    });
    manager.hydrateFromAttempt(makeAttempt());

    // Select Option A
    manager.selectOption('q1', 'q1-opt-a');
    await clock.advanceBy(300);
    assert.equal(manager.getSnapshot().q1.status, 'failed');
    assert.equal(manager.getSnapshot().q1.local.selected_option_id, 'q1-opt-a');

    // First retry fails again -> Option A MUST NOT be toggled to null!
    await manager.retryQuestion('q1');
    assert.equal(manager.getSnapshot().q1.status, 'failed');
    assert.equal(
      manager.getSnapshot().q1.local.selected_option_id,
      'q1-opt-a',
      'Failed retry must never toggle/clear selected option',
    );

    // Second retry succeeds -> Option A is persisted, never null!
    await manager.retryQuestion('q1');
    assert.equal(manager.getSnapshot().q1.status, 'saved');
    assert.equal(manager.getSnapshot().q1.local.selected_option_id, 'q1-opt-a');
    assert.equal(manager.getSnapshot().q1.server.selected_option_id, 'q1-opt-a');
    assert.equal(sentPayloads.length, 3);
    for (const p of sentPayloads) {
      assert.equal(p.selected_option_id, 'q1-opt-a');
    }

    manager.dispose();
  }

  // Test 9 (Defect 1): Dirty question does not have server revision advanced by background refresh,
  // and subsequent PUT still triggers HTTP 409 conflict detection.
  console.log('Test 9: Dirty question preserves server revision across background refresh and detects 409');
  {
    const clock = new FakeClock();
    const saveCalls: Array<{ qId: string; payload: AnswerSaveRequest }> = [];
    let failQ1Once = true;

    const manager = new AttemptAutosaveManager({
      debounceMs: 300,
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      getAttempt: async () =>
        makeAttempt({
          q1Answer: { selected_option_id: null, marked_for_review: false, revision: 0 },
          // Another session edited q2 to Option B at revision 1!
          q2Answer: { selected_option_id: 'q2-opt-b', marked_for_review: true, revision: 1 },
        }),
      saveAnswer: async (_attId, qId, payload) => {
        saveCalls.push({ qId, payload });
        if (qId === 'q1' && failQ1Once) {
          failQ1Once = false;
          throw new ApiError(502, 'Bad Gateway');
        }
        if (qId === 'q2' && payload.expected_revision === 0) {
          throw new RevisionConflictError('Concurrent edit detected', {
            selected_option_id: 'q2-opt-b',
            marked_for_review: true,
            revision: 1,
            saved_at: '2026-11-26T00:06:00Z',
          });
        }
        return {
          selected_option_id: payload.selected_option_id,
          marked_for_review: payload.marked_for_review,
          revision: payload.expected_revision + 1,
          saved_at: '2026-11-26T00:06:01Z',
        };
      },
    });
    manager.hydrateFromAttempt(makeAttempt());

    // Q1 fails initially -> needsReconciliation = true
    manager.selectOption('q1', 'q1-opt-a');
    await clock.advanceBy(300);
    assert.equal(manager.getSnapshot().q1.status, 'failed');

    // Q2 has a dirty local edit pending in debounce (base revision 0)
    manager.selectOption('q2', 'q2-opt-a');
    assert.equal(manager.getSnapshot().q2.status, 'pending');
    assert.equal(manager.getSnapshot().q2.server.revision, 0);

    // Retrying Q1 triggers GET which sees Q2 at revision 1 on server
    await manager.retryQuestion('q1');
    assert.equal(manager.getSnapshot().q1.status, 'saved');

    // Q2 is dirty, so its server revision MUST remain 0 and local MUST remain Option A
    const q2BeforePut = manager.getSnapshot().q2;
    assert.equal(q2BeforePut.server.revision, 0, 'Dirty question server revision must not advance');
    assert.equal(q2BeforePut.local.selected_option_id, 'q2-opt-a');
    assert.equal(q2BeforePut.status, 'pending');

    // When Q2's debounce fires, it sends expected_revision=0 and receives HTTP 409
    await clock.advanceBy(300);
    const q2Call = saveCalls.find((c) => c.qId === 'q2');
    assert.ok(q2Call, 'Q2 PUT should be sent');
    assert.equal(q2Call.payload.expected_revision, 0, 'Q2 must send original expected_revision=0');

    const q2Conflict = manager.getSnapshot().q2;
    assert.equal(q2Conflict.status, 'conflict');
    assert.equal(q2Conflict.local.selected_option_id, 'q2-opt-a');
    assert.equal(q2Conflict.conflictServerState?.selected_option_id, 'q2-opt-b');
    assert.equal(q2Conflict.conflictServerState?.revision, 1);

    // Subsequent background hydrate must not overwrite existing conflictServerState or server rev
    manager.hydrateFromAttempt(
      makeAttempt({
        q1Answer: { selected_option_id: 'q1-opt-a', marked_for_review: false, revision: 1 },
        q2Answer: { selected_option_id: 'q2-opt-a', marked_for_review: false, revision: 2 },
      }),
    );
    const q2StillConflicted = manager.getSnapshot().q2;
    assert.equal(q2StillConflicted.status, 'conflict');
    assert.equal(q2StillConflicted.conflictServerState?.revision, 1);
    assert.equal(q2StillConflicted.conflictServerState?.selected_option_id, 'q2-opt-b');

    manager.dispose();
  }

  // Test 10 (Defect 1): Clean questions still accept legitimate background refreshes monotonically
  console.log('Test 10: Clean questions accept legitimate background refreshes monotonically');
  {
    const clock = new FakeClock();
    let failQ1Once = true;
    let serverQ2 = { selected_option_id: 'q2-opt-b' as string | null, marked_for_review: true, revision: 1 };

    const manager = new AttemptAutosaveManager({
      debounceMs: 300,
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      getAttempt: async () =>
        makeAttempt({
          q1Answer: { selected_option_id: null, marked_for_review: false, revision: 0 },
          q2Answer: serverQ2,
        }),
      saveAnswer: async (_attId, qId, payload) => {
        if (qId === 'q1' && failQ1Once) {
          failQ1Once = false;
          throw new ApiError(502, 'Bad Gateway');
        }
        return {
          selected_option_id: payload.selected_option_id,
          marked_for_review: payload.marked_for_review,
          revision: payload.expected_revision + 1,
          saved_at: '2026-11-26T00:07:00Z',
        };
      },
    });
    manager.hydrateFromAttempt(makeAttempt());

    // Q1 fails; Q2 remains completely clean ('idle', revision 0)
    manager.selectOption('q1', 'q1-opt-a');
    await clock.advanceBy(300);
    assert.equal(manager.getSnapshot().q2.status, 'idle');

    // Retry Q1 -> GET refreshes clean Q2 to revision 1
    await manager.retryQuestion('q1');
    const q2Snap = manager.getSnapshot().q2;
    assert.equal(q2Snap.server.revision, 1);
    assert.equal(q2Snap.server.selected_option_id, 'q2-opt-b');
    assert.equal(q2Snap.local.selected_option_id, 'q2-opt-b');
    assert.equal(q2Snap.local.marked_for_review, true);
    assert.equal(q2Snap.status, 'saved');

    // Stale lower revision (revision 0) in a later background hydrate must be ignored
    manager.hydrateFromAttempt(
      makeAttempt({
        q1Answer: { selected_option_id: 'q1-opt-a', marked_for_review: false, revision: 1 },
        q2Answer: { selected_option_id: null, marked_for_review: false, revision: 0 },
      }),
    );
    assert.equal(manager.getSnapshot().q2.server.revision, 1);
    assert.equal(manager.getSnapshot().q2.local.selected_option_id, 'q2-opt-b');

    manager.dispose();
  }

  // Test 11 (Defect 2): Retry GET detecting a conflict clears its debounce timer
  console.log('Test 11: Retry GET detecting a conflict clears debounce timer scheduled during GET');
  {
    const clock = new FakeClock();
    const getDeferred = createDeferred<AttemptDetailRead>();
    let putCount = 0;

    const manager = new AttemptAutosaveManager({
      debounceMs: 300,
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      getAttempt: () => getDeferred.promise,
      saveAnswer: async () => {
        putCount += 1;
        throw new ApiError(502, 'Bad Gateway');
      },
    });
    manager.hydrateFromAttempt(makeAttempt());

    manager.selectOption('q1', 'q1-opt-a');
    await clock.advanceBy(300);
    assert.equal(putCount, 1);
    assert.equal(manager.getSnapshot().q1.status, 'failed');

    // Start retry -> GET is in flight
    const retryPromise = manager.retryQuestion('q1');
    await flushMicrotasks();

    // Student edits Q1 while GET is in flight -> schedules a 300ms debounce timer
    manager.selectOption('q1', 'q1-opt-c');
    assert.equal(clock.pendingCount(), 1);
    assert.equal(manager.getSnapshot().q1.local.selected_option_id, 'q1-opt-c');

    // GET resolves with a concurrent edit from another session (Option B at revision 1)
    getDeferred.resolve(
      makeAttempt({
        q1Answer: { selected_option_id: 'q1-opt-b', marked_for_review: false, revision: 1 },
      }),
    );
    await retryPromise;

    assert.equal(clock.pendingCount(), 0, 'Debounce timer must be cleared when conflict is detected');
    const snap = manager.getSnapshot().q1;
    assert.equal(snap.status, 'conflict');
    assert.equal(snap.local.selected_option_id, 'q1-opt-c', 'Latest local edit must be preserved');
    assert.equal(snap.conflictServerState?.selected_option_id, 'q1-opt-b');

    // Advancing clock must NOT dispatch any background PUT
    await clock.advanceBy(500);
    assert.equal(putCount, 1, 'No background PUT after conflict');

    manager.dispose();
  }

  // Test 12 (Defect 2): Failed retry GET clears debounce timer and does not dispatch background PUT
  console.log('Test 12: Failed retry GET clears debounce timer and prevents unintended background PUT');
  {
    const clock = new FakeClock();
    const getDeferred = createDeferred<AttemptDetailRead>();
    let putCount = 0;
    let getCount = 0;

    const manager = new AttemptAutosaveManager({
      debounceMs: 300,
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      getAttempt: () => {
        getCount += 1;
        return getDeferred.promise;
      },
      saveAnswer: async () => {
        putCount += 1;
        throw new ApiError(502, 'Bad Gateway');
      },
    });
    manager.hydrateFromAttempt(makeAttempt());

    manager.selectOption('q1', 'q1-opt-a');
    await clock.advanceBy(300);
    assert.equal(putCount, 1);

    const retryPromise = manager.retryQuestion('q1');
    await flushMicrotasks();
    assert.equal(getCount, 1);

    // Edit during in-flight GET schedules debounce timer
    manager.selectOption('q1', 'q1-opt-c');
    assert.equal(clock.pendingCount(), 1);

    // GET fails
    getDeferred.reject(new TypeError('Failed to fetch'));
    await retryPromise;

    assert.equal(clock.pendingCount(), 0, 'Debounce timer must be cleared when reconciliation GET fails');
    const snap = manager.getSnapshot().q1;
    assert.equal(snap.status, 'failed');
    assert.equal(snap.local.selected_option_id, 'q1-opt-c', 'Latest local intent must be retained');

    // Advancing clock must NOT trigger an unexpected background retry GET or PUT
    await clock.advanceBy(1000);
    assert.equal(getCount, 1, 'No unexpected background GET');
    assert.equal(putCount, 1, 'No unexpected background PUT');

    manager.dispose();
  }

  // Test 13 (Defect 2): flushBeforeSubmit() settles promptly with clear failed/conflict result
  console.log('Test 13: flushBeforeSubmit settles deterministically with failed/conflict result without hanging');
  {
    // 13a: Reconciliation GET fails while flushBeforeSubmit is waiting on in-flight GET
    const clock = new FakeClock();
    const getDeferred = createDeferred<AttemptDetailRead>();

    const managerFail = new AttemptAutosaveManager({
      debounceMs: 300,
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      getAttempt: () => getDeferred.promise,
      saveAnswer: async () => {
        throw new ApiError(502, 'Bad Gateway');
      },
    });
    managerFail.hydrateFromAttempt(makeAttempt());

    managerFail.selectOption('q1', 'q1-opt-a');
    await clock.advanceBy(300);

    const retryPromise = managerFail.retryQuestion('q1');
    await flushMicrotasks();

    // Schedule debounce timer during GET, then call flushBeforeSubmit
    managerFail.selectOption('q1', 'q1-opt-c');
    const flushPromise = managerFail.flushBeforeSubmit();
    await flushMicrotasks();

    getDeferred.reject(new Error('Network offline'));
    await retryPromise;
    const failFlushResult = await flushPromise;

    assert.equal(clock.pendingCount(), 0);
    assert.equal(failFlushResult.ok, false);
    assert.equal(failFlushResult.terminated, false);
    assert.deepEqual(failFlushResult.failedQuestionIds, ['q1']);
    assert.deepEqual(failFlushResult.conflictQuestionIds, []);
    managerFail.dispose();

    // 13b: Reconciliation GET detects conflict while flushBeforeSubmit is waiting
    const clock2 = new FakeClock();
    const getDeferred2 = createDeferred<AttemptDetailRead>();

    const managerConflict = new AttemptAutosaveManager({
      debounceMs: 300,
      setTimeoutFn: clock2.setTimeout,
      clearTimeoutFn: clock2.clearTimeout,
      getAttempt: () => getDeferred2.promise,
      saveAnswer: async () => {
        throw new ApiError(502, 'Bad Gateway');
      },
    });
    managerConflict.hydrateFromAttempt(makeAttempt());

    managerConflict.selectOption('q1', 'q1-opt-a');
    await clock2.advanceBy(300);

    const retryPromise2 = managerConflict.retryQuestion('q1');
    await flushMicrotasks();

    managerConflict.selectOption('q1', 'q1-opt-c');
    const flushPromise2 = managerConflict.flushBeforeSubmit();
    await flushMicrotasks();

    getDeferred2.resolve(
      makeAttempt({
        q1Answer: { selected_option_id: 'q1-opt-b', marked_for_review: false, revision: 1 },
      }),
    );
    await retryPromise2;
    const conflictFlushResult = await flushPromise2;

    assert.equal(clock2.pendingCount(), 0);
    assert.equal(conflictFlushResult.ok, false);
    assert.equal(conflictFlushResult.terminated, false);
    assert.deepEqual(conflictFlushResult.failedQuestionIds, []);
    assert.deepEqual(conflictFlushResult.conflictQuestionIds, ['q1']);
    managerConflict.dispose();
  }

  // Test 14 (Defect 2): Newer local edit made during reconciliation is not overwritten and saves cleanly
  console.log('Test 14: Newer local edit made during reconciliation is preserved and saved with reconciled revision');
  {
    const clock = new FakeClock();
    const getDeferred = createDeferred<AttemptDetailRead>();
    const putPayloads: AnswerSaveRequest[] = [];
    let failFirstPut = true;

    const manager = new AttemptAutosaveManager({
      debounceMs: 300,
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      getAttempt: () => getDeferred.promise,
      saveAnswer: async (_attId, _qId, payload) => {
        putPayloads.push(payload);
        if (failFirstPut) {
          failFirstPut = false;
          throw new TypeError('Connection reset');
        }
        return {
          selected_option_id: payload.selected_option_id,
          marked_for_review: payload.marked_for_review,
          revision: payload.expected_revision + 1,
          saved_at: '2026-11-26T00:08:00Z',
        };
      },
    });
    manager.hydrateFromAttempt(makeAttempt());

    // Initial PUT for Option A fails ambiguously (expected_revision=0)
    manager.selectOption('q1', 'q1-opt-a');
    await clock.advanceBy(300);
    assert.equal(manager.getSnapshot().q1.status, 'failed');

    // Retry starts GET reconciliation
    const retryPromise = manager.retryQuestion('q1');
    await flushMicrotasks();

    // Student switches to Option C while GET is in flight
    manager.selectOption('q1', 'q1-opt-c');
    assert.equal(manager.getSnapshot().q1.local.selected_option_id, 'q1-opt-c');

    // GET reveals Option A actually committed on server (rev 1) before connection dropped
    getDeferred.resolve(
      makeAttempt({
        q1Answer: { selected_option_id: 'q1-opt-a', marked_for_review: false, revision: 1 },
      }),
    );
    await retryPromise;

    assert.equal(clock.pendingCount(), 0);
    assert.equal(putPayloads.length, 2);
    assert.equal(putPayloads[1].selected_option_id, 'q1-opt-c');
    assert.equal(putPayloads[1].expected_revision, 1);

    const finalSnap = manager.getSnapshot().q1;
    assert.equal(finalSnap.status, 'saved');
    assert.equal(finalSnap.local.selected_option_id, 'q1-opt-c');
    assert.equal(finalSnap.server.selected_option_id, 'q1-opt-c');
    assert.equal(finalSnap.server.revision, 2);

    manager.dispose();
  }

  // Test 15 (Review Finding): flushPendingWrites flushes pending questions without retrying failed ones
  console.log('Test 15: flushPendingWrites flushes ordinary pending writes without retrying failed questions');
  {
    const clock = new FakeClock();
    const events: string[] = [];

    const manager = new AttemptAutosaveManager({
      debounceMs: 300,
      setTimeoutFn: clock.setTimeout,
      clearTimeoutFn: clock.clearTimeout,
      getAttempt: async () => {
        events.push('GET');
        return makeAttempt({
          q1Answer: { selected_option_id: null, marked_for_review: false, revision: 0 },
          q2Answer: { selected_option_id: 'q2-opt-b', marked_for_review: false, revision: 1 },
        });
      },
      saveAnswer: async (_attId, qId, payload) => {
        events.push(`PUT:${qId}`);
        if (qId === 'q1') {
          throw new ApiError(502, 'Bad Gateway');
        }
        return {
          selected_option_id: payload.selected_option_id,
          marked_for_review: payload.marked_for_review,
          revision: payload.expected_revision + 1,
          saved_at: '2026-11-26T00:09:00Z',
        };
      },
    });
    manager.hydrateFromAttempt(makeAttempt());

    // Q1 failed
    manager.selectOption('q1', 'q1-opt-a');
    await clock.advanceBy(300);
    assert.equal(manager.getSnapshot().q1.status, 'failed');

    // Q2 has an ordinary pending debounced edit
    manager.selectOption('q2', 'q2-opt-b');
    assert.equal(manager.getSnapshot().q2.status, 'pending');

    // Opening submit modal flushes ordinary pending writes ONLY
    const modalFlush = await manager.flushPendingWrites();
    assert.deepEqual(events, ['PUT:q1', 'PUT:q2'], 'Must NOT trigger GET retry on failed Q1 when opening modal');
    assert.equal(modalFlush.ok, false);
    assert.deepEqual(modalFlush.failedQuestionIds, ['q1']);
    assert.equal(manager.getSnapshot().q2.status, 'saved');
    assert.equal(manager.getSnapshot().q1.status, 'failed');

    // Confirming submission calls flushBeforeSubmit(), which reconciles & retries Q1
    const confirmFlush = await manager.flushBeforeSubmit();
    assert.deepEqual(events, ['PUT:q1', 'PUT:q2', 'GET', 'PUT:q1']);
    assert.equal(confirmFlush.ok, false);
    assert.deepEqual(confirmFlush.failedQuestionIds, ['q1']);

    manager.dispose();
  }

  // Test 16 (Submission race): once submission locks input, no late edit can
  // enter after its question has already been visited by the flush operation.
  console.log('Test 16: Submission input lock prevents edits racing an in-progress flush');
  {
    const saveDeferred = createDeferred<AnswerSaveResponse>();
    const saveCalls: AnswerSaveRequest[] = [];
    const manager = new AttemptAutosaveManager({
      debounceMs: 300,
      getAttempt: async () => makeAttempt(),
      saveAnswer: async (_attId, _qId, payload) => {
        saveCalls.push(payload);
        return saveDeferred.promise;
      },
    });

    manager.hydrateFromAttempt(makeAttempt());
    manager.selectOption('q1', 'q1-opt-a');
    manager.setInputLocked(true);

    const flushPromise = manager.flushBeforeSubmit();
    await flushMicrotasks();
    assert.equal(saveCalls.length, 1, 'Flush should start the pending answer save');

    manager.selectOption('q1', 'q1-opt-b');
    manager.toggleReview('q1');
    assert.equal(
      manager.getSnapshot().q1.local.selected_option_id,
      'q1-opt-a',
      'Late selection must be rejected while submission is locked',
    );
    assert.equal(
      manager.getSnapshot().q1.local.marked_for_review,
      false,
      'Late review toggle must be rejected while submission is locked',
    );

    saveDeferred.resolve({
      selected_option_id: 'q1-opt-a',
      marked_for_review: false,
      revision: 1,
      saved_at: '2026-11-26T00:10:00Z',
    });
    const flushResult = await flushPromise;

    assert.equal(flushResult.ok, true);
    assert.deepEqual(flushResult.pendingQuestionIds, []);
    assert.equal(manager.hasUnacknowledgedChanges(), false);
    assert.equal(manager.getSnapshot().q1.server.selected_option_id, 'q1-opt-a');
    assert.equal(saveCalls.length, 1, 'No post-flush write should be scheduled');

    manager.dispose();
  }

  // Test 17 (SPA navigation): navigation preparation locks new edits and waits
  // for a pending answer to be acknowledged before allowing the route to proceed.
  console.log('Test 17: SPA navigation waits for pending answers and rejects late edits');
  {
    const saveDeferred = createDeferred<AnswerSaveResponse>();
    const manager = new AttemptAutosaveManager({
      debounceMs: 300,
      getAttempt: async () => makeAttempt(),
      saveAnswer: async () => saveDeferred.promise,
    });

    manager.hydrateFromAttempt(makeAttempt());
    manager.selectOption('q1', 'q1-opt-a');

    let navigationReady = false;
    const navigationFlush = flushAttemptBeforeNavigation(manager).then((result) => {
      navigationReady = result.ok;
      return result;
    });

    await flushMicrotasks();
    assert.equal(navigationReady, false, 'Navigation must wait while the save is in flight');
    manager.selectOption('q1', 'q1-opt-b');
    assert.equal(
      manager.getSnapshot().q1.local.selected_option_id,
      'q1-opt-a',
      'A new answer must not be accepted after navigation starts draining saves',
    );

    saveDeferred.resolve({
      selected_option_id: 'q1-opt-a',
      marked_for_review: false,
      revision: 1,
      saved_at: '2026-11-26T00:11:00Z',
    });
    const result = await navigationFlush;

    assert.equal(result.ok, true);
    assert.equal(result.pendingQuestionIds?.length, 0);
    assert.equal(navigationReady, true);
    assert.equal(manager.hasUnacknowledgedChanges(), false);
    manager.dispose();
  }

  console.log('--- ALL AUTOSAVE RELIABILITY TESTS PASSED SUCCESSFULLY ---');
}

runTests().catch((err) => {
  console.error('Autosave test suite failed:', err);
  process.exit(1);
});
