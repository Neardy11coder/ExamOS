# ExamOS — Setup, Operations and Handover

**Version:** 0.8 · **Status:** M3-DB-1 Complete — Isolated Database Lab Foundation
**Purpose:** A single place to make the repository reproducible and enable work to continue after an agent/context change.

> Commands in this document have been executed and verified. Each entry records the actual result.

## 1. Prerequisites

Install a current supported version of:

- Git
- Node.js LTS with npm
- Python supported by the selected FastAPI/scikit-learn dependencies
- PostgreSQL, or Docker with Docker Compose
- A code editor and browser

Choose dependency versions during scaffolding and pin them in lock/requirements files. Do not copy unverified version numbers from this document.

## 2. Environment configuration

Create local `.env` files from `.env.example`; never commit real values. Expected settings include:

```dotenv
APP_ENV=development
APP_SECRET_KEY=PLACEHOLDER_GENERATE_RANDOM_SECRET_KEY

# PostgreSQL Server & Roles
POSTGRES_ADMIN_USER=examos_admin
POSTGRES_ADMIN_PASSWORD=PLACEHOLDER_ADMIN_PASSWORD
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5433

POSTGRES_MIGRATOR_USER=examos_migrator
POSTGRES_MIGRATOR_PASSWORD=PLACEHOLDER_MIGRATOR_PASSWORD

POSTGRES_APP_USER=examos_app
POSTGRES_APP_PASSWORD=PLACEHOLDER_APP_PASSWORD

POSTGRES_TEST_USER=examos_test_runner
POSTGRES_TEST_PASSWORD=PLACEHOLDER_TEST_PASSWORD

POSTGRES_PROVISIONER_USER=examos_provisioner
POSTGRES_PROVISIONER_PASSWORD=PLACEHOLDER_PROVISIONER_PASSWORD

# Authoritative Connection Strings
DATABASE_URL=postgresql+psycopg://examos_app:PLACEHOLDER_APP_PASSWORD@127.0.0.1:5433/examos
MIGRATION_DATABASE_URL=postgresql+psycopg://examos_migrator:PLACEHOLDER_MIGRATOR_PASSWORD@127.0.0.1:5433/examos
TEST_DATABASE_URL=postgresql+psycopg://examos_test_runner:PLACEHOLDER_TEST_PASSWORD@127.0.0.1:5433/examos_test
PROVISIONER_DATABASE_URL=postgresql+psycopg://examos_provisioner:PLACEHOLDER_PROVISIONER_PASSWORD@127.0.0.1:5433/examos

# Frontend & Session
FRONTEND_ORIGIN=http://localhost:5173
AUTH_TOKEN_TTL_MINUTES=480
COOKIE_SECURE=false
CSRF_ENABLED=true

# Domain Boundaries
MAX_EXAM_DURATION_MINUTES=240
MAX_QUESTIONS_PER_EXAM=100
MAX_OPTIONS_PER_QUESTION=6
MAX_SCHEDULER_JOBS=50
DBLAB_MAX_DATASET_SIZE=large
DBLAB_DEFAULT_REPETITIONS=5
ML_MODEL_PATH=../ml/artifacts/topic_classifier.joblib
ML_CONFIDENCE_THRESHOLD=0.55
EXPIRED_ATTEMPT_SWEEP_SECONDS=60

# Initial Faculty Bootstrap Credentials
SEED_FACULTY_EMAIL=faculty@examos.local
SEED_FACULTY_PASSWORD=PLACEHOLDER_FACULTY_PASSWORD
```

These are illustrative development defaults, not secure production settings. Validate all settings at startup. Generate a strong random application secret locally. `COOKIE_SECURE=false` is only for local HTTP; HTTPS deployment must enable secure cookies. Dedicated least-privilege roles (`examos_migrator`, `examos_app`, `examos_test_runner`, `examos_provisioner`) are enforced across their respective workflows.

## 3. Local startup sequence

All commands below have been verified on the current scaffold.

### Start PostgreSQL (Docker Compose)

```powershell
# From workspace root — uses project-scoped name to avoid conflicts
docker compose -p examos-dev-20261016 up -d
# Verify healthy:
docker compose -p examos-dev-20261016 ps
```

PostgreSQL 16 binds to `127.0.0.1:5433`. The `database/init-db.sh` script bootstraps roles and databases on first start.

### Backend

```powershell
# From workspace root
python -m venv backend\.venv
backend\.venv\Scripts\pip install -r backend\requirements.txt

# Run migrations (from backend/ directory)
cd backend
.venv\Scripts\python -m alembic upgrade head

# Start dev server (from workspace root)
backend\.venv\Scripts\uvicorn app.main:app --reload --app-dir backend
```

### Frontend

```powershell
# From frontend/ directory
npm install
npm run dev
```

### Tests

```powershell
# From workspace root — requires container running
backend\.venv\Scripts\python -m pytest backend\tests\ -v
```

Do not start the app in a state where it silently creates tables from ORM metadata instead of migrations. Database initialization errors should be explicit.

## 4. Setup expectations

A clean checkout should support:

- One documented command for backend setup/migrations/seeding.
- One documented command for backend run.
- One documented command for frontend run.
- One documented command for backend tests.
- One documented command for ML training/evaluation.

Docker Compose is optional. If included, it should start only the frontend/backend/database services needed for local operation; the ML model is an artifact, not a separate service.

## 5. Demo data

The seed process should support:

- Faculty/admin identity provisioned from environment configuration.
- A small set of student demo users with non-production passwords explicitly documented for local demo only, or a command to provision them.
- The eight topic labels.
- One unpublished draft exam and one published exam built from original demo questions.
- Dataset variants for selective lookup, join and aggregation benchmarks in an isolated schema.

Never expose demo users/passwords in a public deployment. Do not seed fake benchmark results; seed only benchmark input data.

## 6. Database maintenance and reset

- Use Alembic migrations for schema updates.
- Reset scripts must require an explicit development/test environment and must fail if configured against a non-test database.
- Lab reset may only drop/rebuild objects in `examos_lab`.
- A full database reset must be documented as destructive and must not be presented as a normal recovery action.
- Before collecting benchmark results, reseed variants identically and record PostgreSQL version, dataset size, seed, index configuration and repetitions.

## 7. Security and operational checks

- Confirm `.env` and model artifacts containing no sensitive data are appropriately ignored/managed.
- Confirm public registration forces `STUDENT`.
- Confirm faculty is provisioned only by trusted command.
- Confirm cookies, CORS and CSRF work with the actual frontend/backend origins.
- Confirm the student API never returns correct-option flags before finalization.
- Confirm error responses do not reveal tracebacks or SQL.
- Confirm lab endpoints are faculty-only and only accept scenario IDs/enumerated parameters.
- Confirm PostgreSQL test URL points to a disposable test database.

## 8. Troubleshooting guide

| Symptom | Checks |
|---|---|
| API cannot connect to PostgreSQL | Verify service status, database URL, user grants, port and network. Do not paste credentials into logs/issues. |
| Cookie auth fails between ports | Verify frontend origin, `credentials` setting, exact CORS allowlist, cookie `SameSite`/`Secure` options and CSRF header. |
| Alembic reports schema drift | Check current revision, migration history and target database before modifying anything; do not delete tables casually. |
| Save shows conflict | Another tab/request likely advanced the answer revision. Reload authoritative state; do not bypass version checks. |
| Attempt appears active after its deadline in DB | Lazy finalization occurs on relevant access or optional sweep; check the request path and sweep logs. The database row is not promised to flip at the exact deadline without a trigger. |
| ML suggestion unavailable | Check artifact path, taxonomy version, model metadata and server logs. Manual topic selection should still work. |
| DB lab index is not used | This may be correct planner behavior. Check selectivity, row count, plan and cache; never force a fabricated result. |
| Test involving row locks passes on SQLite but fails on PostgreSQL | Run it against PostgreSQL; SQLite does not substitute for the chosen locking semantics. |

## 9. Handover record

Update this section at the end of each development session or before switching coding agents.

### Current status

- **Last updated:** 2026-10-23
- **Current milestone:** M1-EXAM-UI-1 & M1-STUD-UI-1 complete, verified via manual browser smoke test (faculty question authoring, draft creation, attachment, publication, student attempt, autosave, submission, and finalized scoring).
- **Current HEAD:** `d200092` — `feat(frontend): implement faculty exam authoring UI` (tracking `origin/main`).
- **Branch:** `main`, tracking `origin/main`. Working tree contains uncommitted post-smoke-test marks precision standardizations.

### Uncommitted local changes (post-smoke-test audit)

**Modified tracked files:**
- `frontend/src/pages/ExamEditorPage.tsx` — formatted question marks to 2 decimal places (`toFixed(2)`) for consistency with total exam marks.
- `frontend/src/pages/AttemptWorkspacePage.tsx` — formatted active question marks to 2 decimal places (`toFixed(2)`) for consistency.
- `frontend/src/pages/AttemptResultPage.tsx` — formatted breakdown question marks, score delta, and score badge subtext to 2 decimal places (`toFixed(2)`).
- `docs/10_SETUP_AND_HANDOVER.md` — this document.

### Implemented and verified in M1-ATTEMPT-1

**Attempt Data Model & Alembic Migration (`f5a2b3c4d5e6`):**
- `attempts` table: tracks student attempt lifecycle (`IN_PROGRESS`, `SUBMITTED`, `EXPIRED`).
  - Columns: `id`, `student_id`, `exam_id`, `status`, `started_at`, `deadline_at`, `submitted_at`, `finalized_at`, `score`, `created_at`, `updated_at`.
  - Check constraints: `ck_attempts_status` (allowed enum states), `ck_attempts_deadline_after_started` (`deadline_at > started_at`), `ck_attempts_paired_status_finalized` (consistency between terminal status and `finalized_at`/`score`).
  - Unique constraint: `uq_attempts_student_exam` (`student_id`, `exam_id`) enforcing one attempt per student/exam in v1.
- `attempt_answers` table: durable answer records.
  - Columns: `id`, `attempt_id`, `exam_question_id`, `selected_option_id`, `revision`, `created_at`, `updated_at`.
  - Composite foreign keys: (`exam_question_id`, `selected_option_id`) references `exam_question_options (exam_question_id, id)` with `ON DELETE SET NULL`, strictly preventing cross-question option selection at the database engine level.
  - Unique constraint: `uq_attempt_answers_attempt_question` (`attempt_id`, `exam_question_id`).

**Student Examination Lifecycle & Secure Engine APIs:**
- `GET /api/v1/exams/available` (Student): lists published exams with duration, question count, total marks, and current student attempt status.
- `POST /api/v1/exams/{exam_id}/attempts/start` (Student): starts attempt atomically or recovers existing active attempt idempotently. Pre-populates empty answer rows for all frozen questions. Sets deadline = server time + exam duration.
- `GET /api/v1/attempts/{attempt_id}` (Student owner): returns full attempt workspace with questions and student answers. Performs lazy finalization if overdue (`now >= deadline_at`). Strictly omits `is_correct` flags on options while attempt is active (OD-04).
- `PUT /api/v1/attempts/{attempt_id}/answers/{exam_question_id}` (Student owner): saves answer durably. Enforces optimistic revision locking (`expected_revision`), validates frozen question and option membership, enforces server-authoritative deadline boundary (`now < deadline_at`), and increments answer revision.
- `POST /api/v1/attempts/{attempt_id}/submit` (Student owner): finalizes attempt atomically under row lock. Idempotent on repeated calls. Evaluates server-authoritative time against deadline (`now < deadline_at` -> `SUBMITTED`, `now >= deadline_at` -> `EXPIRED`). Computes score atomically from frozen option correctness keys.
- `GET /api/v1/attempts/{attempt_id}/result` (Student owner or Faculty): returns finalized score and per-question breakdown. Discloses `is_correct` only after attempt is finalized (`SUBMITTED` or `EXPIRED`).
- `GET /api/v1/exams/{exam_id}/attempts` (Faculty): lists all student attempts for a published exam, triggering lazy expiry on overdue attempts.

**Security, Invariants & Concurrency Safety:**
- Authenticated student identity is always resolved from HttpOnly JWT cookie; client-supplied IDs are never trusted.
- CSRF validation enforced on all mutating attempt operations (`POST /attempts/start`, `PUT /answers`, `POST /submit`).
- Cross-student access is strictly blocked (HTTP 403 / 404).
- PostgreSQL server time (`clock_timestamp()`) is the sole authority for deadline decisions; client clocks cannot alter deadlines.
- Deadlines use the exclusive boundary rule: requests are timely strictly when `decision_time < deadline_at`.
- Optimistic revision control (`expected_revision`) detects concurrent save conflicts (HTTP 409 `REVISION_CONFLICT`).
- Row locking (`SELECT ... FOR UPDATE` with `selectinload`) prevents race conditions between concurrent saves and submission.

### Implemented and verified in M1-EXAM-1

**Topic taxonomy seeding:**
- 8 authoritative taxonomy topics via `app.services.topic_service.seed_taxonomy_topics` and CLI `python -m app.commands.seed_topics`: `OS_PROCESS`, `OS_SCHEDULING`, `OS_SYNC`, `OS_MEMORY_FILES`, `DB_NORMALIZATION`, `DB_SQL_JOINS`, `DB_TRANSACTIONS`, `DB_INDEXING`.
- Seed is fully idempotent. `GET /api/v1/topics` implemented and verified.

**Faculty question-bank CRUD APIs (`/api/v1/questions`):**
- `GET /questions`: lists/filters active questions by topic UUID or search keyword; supports `include_archived=true`.
- `POST /questions`: creates MCQ question with 2-6 non-empty options and exactly one correct option.
- `GET /questions/{id}`: returns detailed question data including correct-option designation.
- `PATCH /questions/{id}`: updates prompt, topic, or replacement options; enforces author ownership.
- `POST /questions/{id}/archive`: soft-archives questions (`archived_at` set).

**Draft examination authoring (`/api/v1/exams`):**
- `GET /exams`, `POST /exams`, `GET /exams/{id}`, `PATCH /exams/{id}`
- `POST /exams/{id}/questions`: attach with marks and display order.
- `PUT /exams/{id}/questions`: bulk replace/reorder.
- `DELETE /exams/{id}/questions/{qid}`: remove from draft.

**Atomic publishing and immutable snapshots:**
- `POST /exams/{id}/publish`: row-locked (`SELECT ... FOR UPDATE`), wrapped in `begin_nested()` savepoint. Validates title, duration, question count >= 1, non-archived source questions, 2-6 options per question, exactly one correct option, non-empty option text. Creates frozen `exam_questions` and `exam_question_options` rows. Transitions status to `PUBLISHED`.
- Repeated publish is idempotent; returns existing published state without duplicating snapshots.
- Rollback guarantee: savepoint rollback on any failure leaves no partial snapshot rows.
- Immutability: subsequent question-bank edits do not mutate published snapshot rows. **Enforcement layer: application-level only.** Service functions read exclusively from snapshot tables for published exams.
- `POST /exams/{id}/unpublish`: transitions to `UNPUBLISHED` without deleting snapshots.

**Security, authorization, and CSRF:**
- `FACULTY_ADMIN` role guard on all question-bank and exam endpoints.
- Creator/author ownership on all mutating operations.
- CSRF token double-submit on all state-changing endpoints (`POST`, `PATCH`, `PUT`, `DELETE`).
- Unauthenticated -> 401, student -> 403, wrong owner -> 403.

### Test results (observed 2026-10-23)

| Suite | Tests | Warnings | Status |
|---|---|---|---|
| All backend tests (`pytest backend/tests/ -q`) | 189 | 1 (external Starlette deprecation) | 189 passed (when PostgreSQL docker service is running) |
| Frontend TypeScript (`tsc -b`) | — | 0 errors | Exit 0 |
| Frontend production build (`npm run build`) | — | 0 warnings | Exit 0 (vite v5.4.21, dist 231 kB bundle) |
| `git diff --check` | — | Exit 0 | No trailing whitespace errors |

No changes have been staged, committed, pushed, reset, or discarded.

### Manual browser smoke-test verification (observed 2026-10-23)

An interactive manual end-to-end smoke test was performed in the local browser covering:
1. Faculty authentication and landing on dashboard (`FACULTY_ADMIN` role badge).
2. Question authoring via Question Bank: created question with prompt `"what is my name guess it?"` with two options (`"hardik kapil"` marked correct, `"chat gpt"`).
3. Examination draft creation: created draft titled `"guess my name"` with 3-minute duration and student instructions `"guess if you can"`.
4. Question attachment and atomic exam publication: verified frozen assessment snapshot creation.
5. Student examination workflow: opened published exam from `/exams/available`, launched attempt, selected radio option, durable save indicator confirmed save, opened submit confirmation dialog with accurate answered count.
6. Submission and result finalization: submitted attempt, received terminal state (`SUBMITTED`), 100.0% score, 1.00 / 1.00 marks, with answer review showing student selection matched correct key.

### Unverified automated browser behavior

Automated browser driver tests (e.g. Playwright / Selenium CI suites) remain **NOT VERIFIED via automated browser test** because external browser binaries cannot be downloaded in this environment. Manual browser verification above confirmed interactive runtime stability.

### Commands verified

| Command | Environment | Result | Date |
|---|---|---|---|
| `docker compose -p examos-dev-20261016 up -d` | Windows / Docker Desktop | Container healthy on `127.0.0.1:5433` | 2026-10-16 |
| `pip install -r backend\requirements.txt` | Python 3.11.9, venv | All packages installed | 2026-10-16 |
| `pytest backend\tests\test_scheduler.py -v` | Python 3.11.9, venv | **20 passed, 1 warning (external)** | 2026-10-23 |
| `pytest backend\tests\test_scheduler_api.py -v` | Python 3.11.9, venv | **6 passed, 1 warning (external)** | 2026-10-23 |
| `pytest backend\tests\ -q` | Python 3.11.9, venv | **215 passed, 1 warning (external)** | 2026-10-23 |
| `alembic current` (from `backend/`) | Python 3.11.9, venv | `f5a2b3c4d5e6 (head)` on dev database `examos` | 2026-10-21 |
| `python -m app.commands.seed_topics --db-url ...` (from `backend/`) | Python 3.11.9, venv | Seeded 8 taxonomy topics; idempotent | 2026-10-21 |
| `python -m app.commands.bootstrap_faculty` | Python 3.11.9, venv | Provisioned `FACULTY_ADMIN`; idempotent | 2026-10-16 |
| `npm run build` (from `frontend/`) | Node.js LTS, Vite 5.4.21 | Exit 0; 0 errors, 0 warnings | 2026-10-23 |
| `git diff --check` | Git on Windows | Exit 0 | 2026-10-23 |

### Milestone M2-OS-UI-1: Visual CPU Scheduling Simulator Verified

- **Backend Integration:**
  - Route: `POST /api/v1/scheduler/simulate` in `backend/app/api/v1/endpoints/scheduler.py`.
  - Protected with `require_faculty` (`FACULTY_ADMIN` only) and `validate_csrf` (double-submit cookie & header).
  - Delegates to `scheduler_service.py` pure simulation engine; validates job inputs, quantum, and algorithm.
  - Returns 422 with structured field-level error detail on invalid scheduling inputs.
- **Frontend Visualizer UI:**
  - Route: `/faculty/os-scheduler` in `frontend/src/pages/SchedulerSimulatorPage.tsx`, protected with `ProtectedRoute role="FACULTY_ADMIN"`.
  - Enabled faculty dashboard navigation card for "OS Scheduling Simulator".
  - Interactive job table editor supporting up to 50 jobs with dynamic add/remove, ID, arrival time, burst duration, and conditional priority inputs.
  - Preloaded editable preset cases (Case A FCFS + Idle, Case B Round Robin Q=2, Case C Priority, and SJF).
  - Configurable time quantum for Round Robin with validation.
  - Interactive Gantt timeline schedule with distinct CPU idle blocks, start/end timestamps, duration indicators, and color-coded job legend.
  - Comprehensive aggregate statistics: Average Waiting Time, Average Turnaround Time, Average Response Time, CPU Utilization (%), and Throughput (jobs/unit).
  - Detailed per-job metrics table showing Arrival, Burst, Priority, First Start, Completion, Turnaround, Waiting, and Response times.
  - Clear educational disclosure banner stating simulation of abstract jobs with zero context-switch overhead.

### Milestone M3-DB-1: Isolated Database Lab Foundation Verified

- **Migration** `a7b8c9d0e1f2` creates `public.benchmark_runs`, `examos_lab` schema, and 4 paired lab tables (`lab_students_no_index`, `lab_students_indexed`, `lab_enrollments_no_index`, `lab_enrollments_indexed`). Migration is self-contained: `CREATE SCHEMA IF NOT EXISTS examos_lab` and least-privilege GRANTs to `examos_app`/`examos_test_runner` are included.
- **Least-privilege boundary**: `examos_migrator` owns DDL; `examos_app`/`examos_test_runner` have only `SELECT, INSERT, UPDATE, DELETE`. Lab tables are fully isolated from live exam tables in the public schema.
- **Benchmark catalog** (`benchmark_catalog.py`): 3 approved scenarios — `SELECTIVE_LOOKUP`, `JOIN`, `AGGREGATION` — each paired across `NO_INDEX` and `INDEXED` variants. No raw SQL accepted from UI input.
- **Seeding** (`lab_data_service.py`): Deterministic `seed=42` generator; `small` = 100 students / 400 enrollments; `DELETE` used instead of `TRUNCATE` to respect least-privilege grants. Seeding is idempotent.
- **Benchmark runner** (`benchmark_service.py`): Executes `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` on fixed parameterised queries. Never runs arbitrary user SQL.
- **CLI seed command**: `python -m app.commands.seed_lab_dataset --size small --seed 42`.
- **Applied to test DB**: Migration applied to `examos_test` via `-x url=TEST_DATABASE_URL`. All lab tables and grants verified on test DB.
- **Tests**: 11 focused lab tests (`tests/test_database_lab.py`), 226 total tests — all pass.

### Next three tasks

1. **M3-DB-UI-1**: Database performance benchmark lab visualizer UI.
2. **M4-ML-1**: ML topic classification service & fallback.
3. **M4-ML-UI-1**: ML suggestions display in question authoring.

### Decisions not to re-open without a real issue

- Modular monolith; no microservices.
- PostgreSQL is required for critical transaction tests.
- No persisted `CREATED` attempt state; explicit start creates `IN_PROGRESS` atomically.
- Exclusive database-time deadline boundary (`now < deadline_at`).
- Published exam snapshot immutability is enforced at application layer; no DB trigger required by current requirements.
- One attempt ever per student/exam in v1.
- Composite foreign keys on `attempt_answers` guarantee option belongs to referenced question.
- Lazy finalization on attempt recovery / retrieval guarantees eventual consistency without background workers.
- Scheduler uses the documented non-preemptive priority/tie rules.
- No arbitrary SQL and no external AI service.

## 10. Handover prompt for a new coding-agent session

Copy this prompt into a new Codex/agent session after opening the repository:

> You are continuing the ExamOS project. First read `AGENTS.md`, `README.md`, `docs/00_PROJECT_BRIEF.md`, `docs/01_REQUIREMENTS.md` including Appendix A, `docs/02_SYSTEM_ARCHITECTURE.md`, and `docs/10_SETUP_AND_HANDOVER.md`. Inspect the actual repository and Git status before changing files. Treat the requirements Appendix A and system architecture as the resolved design baseline. Do not claim features or tests exist unless verified in the repository. Report current implementation status, the next smallest task from the roadmap, its relevant requirement IDs, files to touch, and tests to run. Implement one bounded task at a time; preserve transaction, deadline, answer-key confidentiality, and lab-isolation invariants. If documentation and code disagree, report the discrepancy instead of silently rewriting requirements.

**Document Status:** Active — Updated after M3-DB-1 completion (2026-10-23)
