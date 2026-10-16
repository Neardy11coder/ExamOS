# ExamOS — Implementation Roadmap

**Version:** 0.2 · **Status:** Draft — Implementation Roadmap  
**Delivery model:** Solo developer; 2–4 weeks; ship a working end-to-end core early

## 1. Delivery strategy

Do not implement all modules in parallel or begin with animations. Build an end-to-end vertical slice, then harden the critical state paths, then add the academic lab modules and the optional ML component. Keep the application runnable after every milestone.

### Scope guardrails

- **Core always wins:** if schedule slips, reduce styling/polish before reducing reliability or removing the OS/DBMS demonstration modules.
- Keep the initial question type to single-correct MCQ.
- Use one backend, one PostgreSQL instance, and one React app.
- No proctoring, mobile app, LLM chatbot, microservices, queue or cloud requirement.
- Add test cases with each service, especially lifecycle and transaction logic.

## 2. Milestones and tasks

### Milestone 0 — Repository and environment (0.5–1 day)

1. Create repository and add `AGENTS.md`, `README.md`, and docs.
2. Scaffold React/TypeScript frontend and FastAPI backend.
3. Configure PostgreSQL connection through environment variables.
4. Configure Alembic and a single initial migration workflow.
5. Add lint/test scripts and `.env.example` with placeholders only.
6. Confirm the application starts locally and database connectivity works.

**Exit criteria:** clean checkout can start frontend/backend/database using documented commands; no credentials committed.

### Milestone 1 — Core examination workflow (Days 2–5)

1. User table, password hashing, login/logout, role checks and faculty bootstrap command.
2. Question/topic bank authoring with options and validations.
3. Draft exam creation and question association.
4. Publish transaction creates immutable snapshots.
5. Student exam catalogue and explicit start attempt.
6. Student question UI: selection, navigation, mark for review.
7. Basic submit/scoring/result screen.
8. Backend tests for role access, no answer-key leakage, snapshots and score calculation.

**Exit criteria:** faculty publishes an exam; student completes and submits it; result matches hand calculation. Published assessment content cannot be mutated.

### Milestone 2 — Reliability and concurrency (Days 6–9)

1. DB-generated `started_at` and persisted deadline.
2. Save service with attempt-first lock ordering, answer revision and mutation ID.
3. UI debounce/save status and bounded retry behavior.
4. Recovery endpoint/UI for saved answers, review flags, revisions and remaining time.
5. One finalization service for student submit, lazy expiry and optional sweep.
6. Atomic terminal state + score and idempotent repeated responses.
7. Tests for deadline boundary, stale saves, multi-tab conflict, duplicate starts/submits, save-vs-finalize and backend restart.

**Exit criteria:** acknowledged save survives refresh/restart; refresh does not add time; terminal result does not change under duplicate/concurrent triggers.

### Milestone 3 — OS and DBMS demonstration modules (Days 10–14)

**OS scheduler**
1. Implement pure FCFS, Round Robin and non-preemptive Priority algorithms.
2. Add hand-computed test cases and invariants.
3. Add job input form, result table and Gantt timeline.

**Database Performance Lab**
4. Create isolated lab schema and deterministic seeded datasets.
5. Define approved SELECT query scenarios for selective lookup, join and aggregation.
6. Add indexed and non-indexed benchmark variants with equivalent seeded content.
7. Execute real plans/timings; persist run metadata and handle errors/timeouts.
8. Build result view with measured values and caveats.

**Exit criteria:** scheduler metrics match the reference tests; lab runs approved scenarios on isolated data, displays actual plans/timings, and cannot execute user-supplied SQL.

### Milestone 4 — ML, analytics and demo polish (Days 15–20)

1. Seed fixed topic taxonomy.
2. Create a small, labelled question-topic CSV with at least 20 examples/topic as a starting target.
3. Add reproducible training/evaluation scripts and model artifact metadata.
4. Add suggestion endpoint, confidence threshold, fallback and faculty override.
5. Add deterministic topic-performance analytics with small-sample labels.
6. Create a useful demo seed script and clear empty/error/loading states.
7. Run full test suite from clean checkout; record environment, limitations and actual benchmark/model metrics.
8. Prepare PBL demonstration script and screenshots.

**Exit criteria:** classifier can be absent without breaking the app; actual evaluation report exists; all priority acceptance scenarios can be shown live.

### Buffer / refinement (Days 21–28 if available)

- Fix defects found during end-to-end demos.
- Improve layout, responsive table behavior and accessible labels.
- Add comparison view for scheduling algorithms.
- Improve DB benchmark plots/plan explanations.
- Optional deployment only after local setup and correctness are stable.

## 3. If only two weeks are available

Suggested compressed schedule:

| Days | Focus |
|---|---|
| 1 | Repository, DB, auth bootstrap, initial schema |
| 2–4 | Questions, exams, publication snapshot, student workflow |
| 5–7 | Timing, autosave/recovery, transactional finalization |
| 8–9 | OS scheduler + tests |
| 10–11 | DB benchmark lab minimal scenarios |
| 12 | ML topic suggestion (or model fallback plumbing + small evaluated baseline) |
| 13 | Regression/security testing and setup cleanup |
| 14 | Demo run-through, report, bug fixing |

If schedule gets tight, implement the smallest genuine version of every differentiating feature before making any module visually elaborate. A simple but real DB lab is better than a polished fake chart. A small classifier with transparent limitations is better than fabricated AI performance.

## 4. Task-tracking convention

Use one issue/task at a time. Suggested labels:

- `M1-core`, `M2-reliability`, `M3-os-db-labs`, `M4-ml-polish`
- `backend`, `frontend`, `database`, `testing`, `docs`
- `blocked`, `bug`, `viva-demo`

Every task should state requirement IDs, files likely affected, acceptance conditions, and tests to run. Do not mix large unrelated refactors with feature delivery.

## 5. Demonstration readiness checklist

- [ ] Faculty account can sign in without public role escalation.
- [ ] Faculty creates a question bank and publishes an exam.
- [ ] Student starts, answers, navigates, marks review and submits.
- [ ] Correct option does not leak during an active attempt.
- [ ] Refresh restores acknowledged answer state and does not add time.
- [ ] Deadline after disconnection results in expiry on next relevant access.
- [ ] Duplicate submission returns same result.
- [ ] Stale/multi-tab save produces a visible conflict rather than silent overwrite.
- [ ] FCFS, Round Robin, Priority show correct metrics and Gantt segments.
- [ ] DB lab outputs actual plan/timing against controlled dataset variants.
- [ ] Classifier proposes or gracefully falls back; faculty can override.
- [ ] All commands in setup doc work from clean checkout.

## 6. Status table

Keep this table up to date during implementation:

| Milestone | Status | Evidence / commit | Known blockers |
|---|---|---|---|
| M0 Environment | Not started | — | — |
| M1 Core exam | Not started | — | — |
| M2 Reliability | Not started | — | — |
| M3 OS + DB labs | Not started | — | — |
| M4 ML + polish | Not started | — | — |

**Document Status:** Draft — Implementation Roadmap
