# ExamOS — Codex / Coding-Agent Build Prompts

**Version:** 0.1 · **Status:** Ready-to-use implementation prompts  
**Read first:** root `AGENTS.md`, `README.md`, and all core design docs

These prompts are intentionally staged. Use one prompt at a time and inspect/test the changes before proceeding. Do not ask a coding agent to implement the whole platform in one enormous change.

## Prompt 0 — Repository inspection and implementation plan

```text
You are implementing ExamOS in this repository. Before writing code, read AGENTS.md, README.md, and docs/00_PROJECT_BRIEF.md through docs/12_CODEX_BUILD_PROMPTS.md. Pay special attention to docs/01_REQUIREMENTS.md Appendix A, docs/02_SYSTEM_ARCHITECTURE.md, docs/03_DATABASE_DESIGN.md, docs/04_API_CONTRACT.md, docs/08_TESTING_STRATEGY.md and docs/09_IMPLEMENTATION_ROADMAP.md.

Inspect the current repository and report:
1. Which required files/folders already exist.
2. Current Git status and existing tests/commands.
3. Any contradictions between actual code and documentation.
4. A bounded task plan for Milestone 0 only.

Do not build the entire application yet. Do not change project requirements or architecture. Do not claim a command/test works until it has been run. Wait for my approval before broad scaffolding if the repository already contains code.
```

## Prompt 1 — Milestone 0: scaffold and local environment

```text
Implement Milestone 0 from docs/09_IMPLEMENTATION_ROADMAP.md only. Scaffold a React + TypeScript + Vite + Tailwind frontend and a FastAPI + SQLAlchemy + Alembic backend. Configure PostgreSQL through environment variables, an explicit settings module, health endpoint, clean app startup, and a documented local test command. Add .env.example with placeholders only, .gitignore, and minimal setup instructions.

Use the simplest maintainable structure in docs/02_SYSTEM_ARCHITECTURE.md. Do not implement exam functionality yet. Do not add microservices, Redis, Celery, arbitrary SQL endpoints, external AI services, or unnecessary libraries. Do not commit secrets. Run and report the actual checks you performed. Update docs/10_SETUP_AND_HANDOVER.md with verified commands and limitations. Stop after Milestone 0.
```

## Prompt 2 — Milestone 1A: authentication, question bank and exam drafts

```text
Implement the next smallest vertical slice for Milestone 1, following docs/01_REQUIREMENTS.md Appendix A, docs/02_SYSTEM_ARCHITECTURE.md, docs/03_DATABASE_DESIGN.md and docs/04_API_CONTRACT.md. Add users, roles, topics, question bank, question options, exams and draft-management migrations/services/API/essential UI. Public registration must create STUDENT only; provision FACULTY_ADMIN only through the trusted bootstrap command. Enforce auth and role checks on the server. Validate exactly one correct MCQ option. Published content snapshots must be implemented in the next publication task; do not expose bank correct answers to student endpoints.

Write migrations and focused tests with PostgreSQL. Do not bypass Alembic by creating tables silently on startup. Do not implement the OS lab, DB lab or ML feature in this task. Report files changed, tests run and any remaining requirement gaps.
```

## Prompt 3 — Milestone 1B: publication snapshots and core student exam

```text
Implement exam publication snapshots and the basic student workflow only. Use docs/03_DATABASE_DESIGN.md and docs/04_API_CONTRACT.md. Publishing must atomically freeze question text, topic label, option text/correctness, marks and display order. Published exams remain immutable even after unpublishing; unpublishing blocks new attempts but leaves existing attempts valid.

Implement available-exam listing, explicit start, question navigation/selection/mark-for-review, single attempt per student/exam, submit, transaction-safe scoring, and result display. A start transaction must create an IN_PROGRESS attempt directly with persisted start/deadline and answer rows; do not persist CREATED. Never send correct-option metadata before finalization. Add tests for snapshots, duplicate start, answer-key leakage, scoring and student ownership. Do not claim recovery/concurrency is complete until Milestone 2.
```

## Prompt 4 — Milestone 2: timing, autosave, recovery and finalization

```text
Implement Milestone 2 reliability features as one or more small changes, following docs/02_SYSTEM_ARCHITECTURE.md, docs/03_DATABASE_DESIGN.md, docs/04_API_CONTRACT.md and docs/08_TESTING_STRATEGY.md.

Required invariants:
- PostgreSQL is the authoritative time source. Lock the attempt row, then obtain clock_timestamp(); the request is timely only if decision_time < deadline_at.
- Save and finalization paths lock attempt before answer.
- Answer mutations include expected_revision and mutation_id. A stale revision never silently overwrites newer data.
- An acknowledgement is sent only after commit.
- Lazy finalization is the expiry correctness path; an optional sweep is only a promptness aid.
- Terminal state, finalized_at and score commit atomically. Repeated submit returns the persisted outcome.
- Expiry, save and submit races settle into one durable result.

Build focused PostgreSQL tests for deadline equality, duplicate requests, multi-tab revision conflict, save-vs-finalize, duplicate finalization and backend restart after an acknowledged save. Do not add Redis/Celery or pretend time passage executes code. If existing code conflicts with the design, explain it before making a destructive change.
```

## Prompt 5 — Milestone 3A: OS scheduling simulator

```text
Implement only the faculty/admin OS scheduling simulator described in docs/06_OS_SCHEDULING_SIMULATOR.md. Keep algorithms pure and independent of live exam tables. Implement FCFS non-preemptive, Round Robin with the documented quantum-boundary rule, and non-preemptive Priority Scheduling where lower numeric value means higher priority. Preserve deterministic tie-breaking and represent idle intervals. Calculate the specified metrics and render a Gantt-style timeline plus metrics table.

Port the hand-verified examples in the spec into automated tests, then add edge/tie/invalid-input tests. The interface must state this is an educational simulation of abstract jobs, not kernel scheduling. Do not implement the DB lab in this task.
```

## Prompt 6 — Milestone 3B: database performance lab

```text
Implement only the controlled Database Performance Lab in docs/02_SYSTEM_ARCHITECTURE.md and docs/03_DATABASE_DESIGN.md. All operations must target the isolated examos_lab schema and predefined scenarios. Do not accept SQL, table names, schema names or arbitrary query fragments from the UI. Seed paired logically identical indexed and non-indexed variants with matching row counts/content checksum for selective lookup, JOIN and aggregation. Run real approved SELECT benchmarks and actual PostgreSQL EXPLAIN ANALYZE plans; store run metadata and report actual timings with repetition/summary details.

On error or timeout, show a sanitized failure and never substitute mock timings. Restrict endpoint access to FACULTY_ADMIN. Test that unknown scenario IDs are rejected and lab operations cannot change live exam rows.
```

## Prompt 7 — Milestone 4: ML topic classifier and analytics

```text
Implement the optional local classifier and deterministic analytics according to docs/07_AI_ML_DESIGN.md. Add a curated labelled dataset for the eight topic codes, fixed-seed stratified train/test split, TF-IDF + Logistic Regression pipeline, separate training/evaluation command, saved artifact and evaluation report. Report only metrics generated by the actual evaluation run. Suggestions are shown only if confidence meets the configured threshold; missing model, low confidence or inference errors must fall back to manual faculty topic selection without blocking question creation or exams.

Implement student/topic analytics using finalized attempts and frozen topic labels. Do not label deterministic statistics as ML and do not train on identifiable student answer data. Add tests for override/fallback and small-sample topic handling. Stop before optional deployment polish.
```

## Prompt 8 — Final integration audit

```text
Perform a requirements-based audit; do not add features automatically. Map each functional requirement/business rule from docs/01_REQUIREMENTS.md (including Appendix A) to implementation evidence and tests. Check: role isolation, correct-answer confidentiality, exam snapshot immutability, PostgreSQL migration reproducibility, persisted deadline and exclusive cutoff, answer revisions, lazy expiry, atomic idempotent finalization, scheduler metric correctness, isolated DB lab, real benchmark outputs, classifier fallback and clean setup.

Run the available test suites and report actual output. Produce a concise gap list with requirement IDs, severity, evidence and next action. Update docs/10_SETUP_AND_HANDOVER.md with verified commands, completed milestones, known issues, current Git commit and next tasks. Do not claim all requirements pass unless each has evidence.
```

## Agent working rule

Use one prompt, verify the result, commit the working state, then continue. If context/token limits become a problem, update `docs/10_SETUP_AND_HANDOVER.md` and start a fresh session with the handover prompt from that file. The new session must inspect the repository rather than relying only on pasted summaries.

**Document Status:** Ready-to-use coding-agent prompts
