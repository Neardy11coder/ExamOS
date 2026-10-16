# ExamOS — Testing Strategy

**Version:** 0.2 · **Status:** Draft — Test Strategy

## 1. Testing goals

Testing prioritizes correctness of saved answers and final results, authorization, the deadline boundary, concurrent updates, and the two educational lab modules. UI polish and broad visual automation are secondary to reliable business logic.

## 2. Test layers

| Layer | Tool/approach | Purpose |
|---|---|---|
| Pure unit tests | Pytest | Scoring, time-boundary helpers, analytics calculations, OS scheduling algorithms, input validation. |
| Service tests | Pytest + test PostgreSQL | Transactions, snapshots, start, save, recovery, finalization, access checks. |
| API tests | FastAPI test client with PostgreSQL test database | Status codes, validation, error envelope, auth/role and payload security. |
| Concurrency tests | Multiple DB sessions/threads against PostgreSQL | Simultaneous start/save/submit/expiry and stale revision handling. |
| Migration tests | Fresh disposable PostgreSQL database | Rebuild schema from Alembic migrations and load seed data. |
| Frontend tests | Lightweight component tests where time allows | Save status, protected routes, countdown display, revision conflict, unavailable ML state. |
| Manual E2E | Browser checklist | Full student/faculty flows and live demos. |
| Lab measurement | Actual PostgreSQL executions | Real `EXPLAIN ANALYZE` plans and timing measurements; no fabricated results. |
| ML evaluation | Reproducible held-out evaluation script | Dataset summary, precision/recall/F1, confusion matrix. |

Critical concurrency and transaction tests must run against PostgreSQL; SQLite is not an adequate substitute for its lock/plan semantics.

## 3. Requirement-oriented test cases

### Authentication and permissions

- Invalid credentials return generic failure.
- Student registration cannot choose `FACULTY_ADMIN`.
- Student cannot read/modify another student's attempt, answer, result or analytics.
- Student cannot call faculty management/lab endpoints.
- Faculty cannot start or alter a student's active attempt.
- Correct answer metadata never appears in any active student payload.
- Expired or missing auth is rejected.

### Examination publication and snapshots

- Empty exam cannot publish.
- Questions need 2+ options and exactly one correct option.
- Publication freezes prompt, options, marks, topic and order atomically.
- Failed publish leaves no partial snapshots and exam is not published.
- Editing the bank later does not change published snapshot or historic result.
- Unpublishing blocks new starts but active attempts continue.

### Start, deadline and lifecycle

- Start creates one `IN_PROGRESS` attempt with server/database timestamps and one answer row per frozen question.
- Two concurrent starts for the same student/exam yield one attempt.
- Refresh/re-login does not alter deadline.
- A request at `deadline_at - epsilon` is treated as timely; at `deadline_at` or after is expired. Use a controlled clock/DB timestamp setup instead of sleeping in tests.
- Client-supplied time, score or state is ignored/rejected.
- A late save triggers/observes expiry and cannot change answers.

### Autosave/recovery

- Accepted save increments revision and is acknowledged only after commit.
- Same mutation ID retry is idempotent.
- Wrong expected revision returns canonical state and does not overwrite.
- Save from an unauthorized student/question/option is rejected.
- Two tabs using same expected revision: one update wins; the stale one receives a conflict.
- Save racing with finalization has a serializable outcome: saved-before-finalization or rejected-after; never partial state.
- Backend restart after acknowledged save preserves response.
- Database failure is not acknowledged as saved.
- Recovery restores saved answers/review flags and persisted deadline; unsaved edits are not falsely represented as durable.

### Submission and expiry

- Correct score equals sum of marks for correct saved choices; unanswered/wrong contributes zero.
- Empty and partially answered attempts can be finalized.
- Duplicate submit returns same status/score/finalization timestamp.
- Submit racing with lazy expiry/periodic sweep commits one terminal outcome.
- Fault injected before final commit leaves active state and no partial score.
- Expiry on faculty attempt list, result list and analytics scope is consistent; aggregates never count overdue active attempts as finalized results.
- Terminal attempts cannot be edited or re-scored.

### OS simulator

- Unit-test the reference cases in `06_OS_SCHEDULING_SIMULATOR.md` exactly.
- Add tests for same-time arrivals, idle gaps, Round Robin quantum-boundary arrivals, completion exactly at quantum, single-job workloads, tie-breakers and invalid values.
- Assert all invariants: work conservation, no overlap, burst sums, metric formulas and deterministic output.
- Confirm scheduler module imports no live data models/services.

### Database Performance Lab

- Unauthorized access denied.
- Unknown scenario and invalid size/seed/repetition are rejected.
- UI request cannot provide SQL/table/schema names.
- Seeded indexed/no-index variants have matching content checksum/row counts.
- Returned plan/timings originate from actual PostgreSQL commands.
- Failed or timed-out run displays an error; no hard-coded sample is presented as a fresh measurement.
- Lab reset/write only touches lab schema.
- Capture run metadata and display measurement caveats.

### ML and analytics

- Dataset loader validates columns and topic labels.
- Train/test split is stratified and reproducible with a fixed seed.
- Evaluation report is created from held-out predictions.
- Missing artifact, load exception, inference exception and low confidence all use manual fallback.
- Faculty override is stored.
- Topic analytics count only finalized attempt question rows and use snapshot labels.
- Topics with fewer than three questions are not ranked; equal eligible extremes display all ties.
- Analytics UI uses cautious, exam-specific wording.

## 4. Test data and fixtures

Use a disposable PostgreSQL database for tests with:

- One faculty user and at least two students.
- One draft and one published exam.
- Questions covering all major types of input validation, although only single-correct MCQs are supported.
- Exam snapshots with different marks/topics/options.
- Attempts in active, submitted and expired states, constructed through service/test helpers rather than by bypassing all invariants indiscriminately.
- Isolated lab data variants.

Never run tests that alter data against a real/demo database that matters. Make the test database URL explicit and fail fast if it points to a non-test database.

## 5. Deterministic time testing

Keep deadline logic behind a small decision function/service boundary, but the final authoritative time must come from PostgreSQL at transaction decision time. Tests can set `deadline_at` deliberately in the past/future or use an injected database test helper that controls test fixtures. For the exact equality boundary, test at or after stored deadline with a controlled transaction setup. Do not use long `sleep()` calls in tests.

## 6. Test execution commands

The setup document will define the concrete command names once files exist. The intended minimum is:

- One command for backend unit/integration tests.
- One command for frontend checks/tests.
- One command for ML evaluation.
- One command or script to seed local demo data.

Record command, environment and outcome in `docs/10_SETUP_AND_HANDOVER.md`. Report tests as passed only if they ran and passed.

## 7. Performance measurement

Performance targets are provisional. Document CPU/RAM/OS, PostgreSQL version, data sizes, query, index configuration, repetition count and summary method. For the DB lab, actual query plans and timing outputs are the evidence. For API timing, measure a defined profile rather than relying on a single manual request. Do not make hardware-independent claims.

## 8. Release gate

Do not consider the core workflow demo-ready until:

- Full student happy path works.
- Role isolation and answer-key protection are tested.
- Acknowledged answer survives refresh and backend restart.
- Deadline/expiry behavior is consistent.
- Duplicate/concurrent finalization results in one stable score.
- Schedulers pass hand-computed tests.
- Database lab runs approved queries against isolated data and displays actual measurements.
- ML can be disabled without breaking exam/question workflows.
- Clean local setup instructions have been followed from scratch.

**Document Status:** Draft — Test Strategy
