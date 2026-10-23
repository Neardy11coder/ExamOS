# ExamOS — Setup, Operations and Handover

**Version:** 1.2 · **Status:** M6-DEMO-PREP Complete — PBL Demonstration & Viva Readiness
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
| All backend tests (`pytest backend/tests/ -v`) | 271 | 5 (external Starlette/httpx/scipy deprecations) | 271 passed in ~42s (when PostgreSQL docker service is running) |
| Focused ML tests only (`pytest tests/test_ml_dataset.py tests/test_ml_topic_suggestions.py -v`) | 35 | 5 (external deprecations) | 35 passed in ~3s |
| Frontend TypeScript (`tsc -b`) | — | 0 errors | Exit 0 |
| Frontend production build (`npm run build`) | — | 0 warnings | Exit 0 (vite v5.4.21, 1600 modules, dist ~326 kB bundle) |
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

### Milestone M3-DB-UI-1: Database Performance Benchmark Visualizer Verified

- **Backend Integration:**
  - Endpoints in `backend/app/api/v1/endpoints/database_lab.py`:
    - `GET /api/v1/labs/db/benchmarks`: Lists approved scenarios from catalog (`selective_lookup`, `join_students_enrollments`, `aggregation_department_gpa`) and dataset scales (`small`, `medium`, `large`). Faculty/admin only (`require_faculty`).
    - `POST /api/v1/labs/db/benchmarks/run`: Executes approved benchmarks on isolated `examos_lab` tables using `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`. Requires `FACULTY_ADMIN` role and validates CSRF (`validate_csrf`). Persists execution records to `public.benchmark_runs`. Rejects arbitrary SQL and invalid inputs.
    - `GET /api/v1/labs/db/benchmarks/runs`: Retrieves recent benchmark execution audit history ordered by `created_at DESC`.
    - `GET /api/v1/labs/db/benchmarks/runs/{run_id}`: Retrieves full run details, parameters, and parsed execution plans.
  - Pydantic schemas in `backend/app/schemas/database_lab.py` and registered in `backend/app/api/v1/api.py`.
  - Comprehensive API test suite in `backend/tests/test_database_lab_api.py` verifying 401 unauthenticated, 403 student access, CSRF validation, parameter bounds validation, execution, and history retrieval.
- **Frontend Visualizer UI:**
  - Route: `/faculty/database-lab` in `frontend/src/pages/DatabaseLabPage.tsx`, protected with `<ProtectedRoute role="FACULTY_ADMIN">`.
  - Enabled faculty dashboard navigation card for "Database Performance Lab".
  - Dedicated API client in `frontend/src/api/databaseLab.ts` with CSRF cookie handling.
  - Benchmark scenario selector with educational descriptions, learning objectives, table references, and caveat notices.
  - Configurable dataset scale (`small`, `medium`, `large`), reproducible random seed, and repetition controls (1–10).
  - Side-by-side comparison of NO_INDEX (Sequential Scan) vs INDEXED (B-tree Index Scan) with actual median timings, planning times, rows scanned, and speedup ratio.
  - Interactive EXPLAIN plan viewer with side-by-side and isolated plan tree JSON inspection.
  - Audit history tab allowing inspection of past benchmark runs.
  - Clear real-measurement notice explaining cache warmup and server load variations.
- **Verification Results:**
  - Backend tests: 236 passing tests (21 lab tests across `test_database_lab.py` and `test_database_lab_api.py`), 0 failures, 1 warning.
  - Frontend build: `npm run build` succeeds cleanly with zero TypeScript errors.
- **Active Dataset Scale & Reliability Hardening:**
  - Added `inspect_active_lab_dataset()` in `lab_data_service.py` to count rows across all four paired tables and classify active scale (`small`, `medium`, `large`, `inconsistent`, `empty`).
  - Catalog endpoint `GET /api/v1/labs/db/benchmarks` surfaces `active_dataset` object with verified table row counts and detected scale.
  - Benchmark execution `POST /api/v1/labs/db/benchmarks/run` validates that requested scale matches verified active data before running queries. Rejects scale mismatch with HTTP 409 `DATASET_SCALE_MISMATCH`.
  - Added explicit PostgreSQL `ANALYZE` commands on all four lab tables at the conclusion of `seed_lab_dataset()` to guarantee immediate statistics availability for query plan costing.
  - Updated frontend `DatabaseLabPage.tsx` to display active database scale, row counts, and clear operator CLI instructions when target scale differs from database state.

### Milestone M4-ML-1: Local ML Topic Classification Service & Graceful Fallback ✅

- **Requirements:** FR-ML-001–011, OD-06, docs/07_AI_ML_DESIGN.md §5, docs/04_API_CONTRACT.md §8
- **Completed:** 2026-10-23

#### ML package (`ml/`)

- `ml/__init__.py` — canonical 8-code taxonomy list (`TAXONOMY_TOPIC_CODES`).
- `ml/preprocessing.py` — `normalize_text()` / `combine_prompt_and_options()` — no answer-key fields.
- `ml/dataset.py` — `load_dataset()` (validates all 8 classes, no empty rows, no duplicate normalized texts) + `get_stratified_split()` (deterministic, seed=42, 80/20, leakage-checked).
- `ml/train.py` — TF-IDF (1-gram + 2-gram, sublinear_tf) + Logistic Regression (C=1.0, lbfgs, max_iter=1000). Saves `.joblib` artifact + metadata JSON. Run: `python -m ml.train` from project root.
- `ml/evaluate.py` — Evaluates on deterministic held-out test split; writes `ml/reports/evaluation_report.json` and `ml/reports/evaluation_summary.md`. Run: `python -m ml.evaluate` from project root.
- `ml/data/question_topics.csv` — 160 curated examples (20 per class × 8 topics). No student data. No answer keys.
- `ml/artifacts/topic_classifier_metadata.json` — tracked (not ignored).
- `ml/artifacts/topic_classifier.joblib` — **git-ignored** (regenerate with `ml.train`).
- `ml/artifacts/.gitkeep`, `ml/reports/.gitkeep` — directory markers.

#### Actual evaluation metrics (seed=42, 80/20 split, 128 train / 32 test)

| Metric | Value |
|---|---|
| Overall Accuracy | **68.8%** |
| Macro F1 | **0.6496** |
| Weighted F1 | **0.6496** |

| Topic | Precision | Recall | F1 | Test n |
|---|---|---|---|---|
| OS_PROCESS | 0.80 | 1.00 | 0.889 | 4 |
| OS_SCHEDULING | 0.80 | 1.00 | 0.889 | 4 |
| OS_SYNC | 0.00 | 0.00 | 0.000 | 4 |
| OS_MEMORY_FILES | 1.00 | 0.75 | 0.857 | 4 |
| DB_NORMALIZATION | 1.00 | 0.50 | 0.667 | 4 |
| DB_SQL_JOINS | 0.43 | 0.75 | 0.545 | 4 |
| DB_TRANSACTIONS | 0.75 | 0.75 | 0.750 | 4 |
| DB_INDEXING | 0.50 | 0.75 | 0.600 | 4 |

**Known limitations:**
1. Dataset scale is a modest development baseline (160 samples, 20 per class). With only 4 test samples per class, per-topic metrics are highly variable.
2. `OS_SYNC` scores F1=0.00 on this split — its 4 test examples were misclassified as OS_PROCESS, OS_SCHEDULING, DB_SQL_JOINS, and DB_INDEXING. This reflects the small test set; the classifier is advisory only.
3. Conceptual overlap on cross-cutting terms (e.g. transactions vs SQL joins, sync vs process) degrades precision on similar-domain questions.
4. The default threshold (0.55) is intentionally conservative to suppress false positives when faculty are authoring questions.
5. Model predictions are strictly advisory. Faculty confirmation is authoritative.

#### Backend integration

- `backend/app/schemas/ml.py` — `TopicSuggestionRequest` (prompt max 5000 chars, options max 10 × 1000 chars, extra fields forbidden), `TopicSuggestionResponse`, `TopicSuggestionDetails`.
- `backend/app/services/ml_service.py`:
  - Lazy model load on first `suggest_topic()` call.
  - `ML_MODEL_PATH` resolved relative to `backend/` directory regardless of process CWD. Default: `../ml/artifacts/topic_classifier.joblib` (resolves to `ml/artifacts/topic_classifier.joblib` under repo root).
  - `ML_CONFIDENCE_THRESHOLD` validated `[0.0, 1.0]`; raises `ValueError` on misconfiguration.
  - Incompatible-model guard: returns `MODEL_NOT_FOUND` if loaded model's classes don't cover the full 8-topic taxonomy.
  - Reason codes: `MODEL_NOT_FOUND`, `MODEL_LOAD_FAILED`, `INFERENCE_FAILED`, `LOW_CONFIDENCE`. `MODEL_ERROR` retained as backward-compat alias.
  - No exceptions surfaced to callers; no question content or paths logged.
- `backend/app/api/v1/endpoints/ml.py` — `POST /api/v1/ml/topic-suggestions`: faculty-only (`require_faculty`), CSRF-protected (`validate_csrf`). Always returns HTTP 200. Never persists topic assignment.
- `backend/app/api/v1/api.py` — Router registered.
- `backend/requirements.txt` — `scikit-learn==1.5.2` added (Python 3.11 compatible).

#### Tests

- `backend/tests/test_ml_dataset.py` — 18 tests covering: all 8 classes present, 20+ samples/class, no duplicates, split disjointness, split determinism, train+evaluate round-trip, metadata fields.
- `backend/tests/test_ml_topic_suggestions.py` — 17 tests covering: model-not-found, high-confidence suggestion, low-confidence, prediction exception, prompt-only input, relative path resolution independent of CWD, faculty-only auth, CSRF, input validation, response schema contracts, no artifact path leakage.
- Full suite: **271 passed, 0 failed** (2026-10-24).

#### ML commands (run from project root `C:\Projects\ExamOS`)

```powershell
# Verify environment
& backend\.venv\Scripts\python.exe -c "import sklearn, joblib; print('sklearn', sklearn.__version__); print('joblib', joblib.__version__)"

# Train (saves ml/artifacts/topic_classifier.joblib + metadata.json)
& backend\.venv\Scripts\python.exe -m ml.train

# Evaluate (reads held-out test split; writes ml/reports/)
& backend\.venv\Scripts\python.exe -m ml.evaluate
```

> **Note:** The `.joblib` artifact is git-ignored. After a fresh clone, run `ml.train` before starting the backend server. The server starts normally without the artifact — topic suggestions will return `available=false, reason="MODEL_NOT_FOUND"` until the artifact is present.

#### Frontend integration (M4-ML-UI-1)

- `frontend/src/api/ml.ts` (109 lines):
  - Typed API client for `POST /api/v1/ml/topic-suggestions`.
  - Types: `TopicSuggestionRequest`, `TopicSuggestionDetails`, `TopicSuggestionAvailable`, `TopicSuggestionUnavailable`, `TopicSuggestionResponse`.
  - Security & privacy invariant: never sends `is_correct` flags or answer keys; strips them to send only question prompt text and optional option texts.
  - Passes `X-CSRF-Token` via `readCsrfCookie()`, credentials include.
  - Treats non-200 responses as `ApiError`, ensuring non-blocking failure handling in UI.
- `frontend/src/pages/QuestionBankPage.tsx`:
  - **Explicit trigger:** Faculty clicks "Suggest Topic" button (`#suggest-topic-btn`). Disabled when prompt is empty or while request is in-flight.
  - **Local prompt validation:** Rejects empty prompt with clear message before issuing any network call.
  - **Suggestion panel:** Displays "Automatic Topic Suggestion" label with purple accent styling, topic name, topic code, confidence percentage, and model threshold.
  - **Accept action:** "Use Suggestion" (`#use-suggestion-btn`) maps the returned `topic_code` to the corresponding UUID in the loaded `topics` list and updates `topicInput`. If the topic code is not found in the current active taxonomy, it displays a safe fallback error rather than misassigning.
  - **Dismiss action:** "Dismiss" (`#dismiss-suggestion-btn`) clears displayed proposal without affecting the manual selector.
  - **Manual override:** Faculty retains full control to change or clear the topic at any point via the standard dropdown selector.
  - **Graceful degradation:** Displays friendly, non-blocking informational messages for `LOW_CONFIDENCE`, `MODEL_NOT_FOUND`, and `MODEL_LOAD_FAILED`. Suggestion errors do not block question creation or editing.
  - **Staleness invalidation:** Edits to prompt or option texts invalidate visible suggestions; modal close/cancel and question switching reset all suggestion state.
  - **Verification:** Verified via `npm run build` (0 TypeScript errors, 1600 modules transformed in ~1.65s).

### Milestone 5 — Security, Concurrency & Reliability Audit (M5-AUDIT-1)

Completed end-to-end audit across 7 key architectural domains:
1. **Authentication & Authorization**: Role boundaries (`STUDENT` vs `FACULTY_ADMIN`), CSRF validation, HttpOnly cookie handling, ownership enforcement across attempts and questions verified.
2. **Exam Lifecycle & Concurrency**: Atomic publication snapshots, exclusive deadline enforcement (`now < deadline_at`), optimistic answer revision concurrency (`ANSWER_REVISION_CONFLICT`), idempotent attempt finalization, and lazy expiry confirmed.
3. **Database Integrity**: Proper transaction management, foreign keys, Alembic migrations, and role isolation confirmed.
4. **API Validation & Security**: Strict Pydantic models, answer confidentiality (`is_correct` withheld until finalization), and error response sanitization verified.
5. **Scheduler & Database Lab**: Educational CPU scheduling simulator purity confirmed; Database Performance Lab strictly bounded to predefined queries in isolated `examos_lab` schema with zero arbitrary SQL execution.
6. **ML Topic Suggestions**: Advisory-only topic classification, graceful degradation on model absence or low confidence, strict CSRF/faculty guards verified.
7. **Regression Coverage**: Full backend suite passed (271 passed, 0 failed in 39.72s), frontend production build passed (0 errors in 1.63s), `git diff --check` clean.

### Milestone 6 — PBL Demonstration & Viva Readiness (M6-DEMO-PREP)

Completed live demonstration preparation and comprehensive viva material:
1. **Demo Runbook**: Created [`docs/DEMO_RUNBOOK_AND_VIVA_GUIDE.md`](./DEMO_RUNBOOK_AND_VIVA_GUIDE.md) providing an 8–12 minute evaluator walkthrough covering:
   - System framing, authentication, and role boundaries.
   - Faculty question authoring with advisory ML topic classification and graceful low-confidence fallback.
   - Exam drafting, question attachment, and atomic publication with frozen immutable snapshots.
   - Student attempt lifecycle: answering, mark-for-review, autosave, disconnection/recovery, and answer key confidentiality.
   - Idempotent finalization, score computation, and lazy expiry.
   - Interactive CPU scheduling simulation (FCFS, Round Robin, non-preemptive Priority) with Gantt timeline.
   - Database Performance Lab: parameterized read-only queries on `examos_lab`, active scale checks, and real `EXPLAIN ANALYZE` comparisons.
2. **Viva Preparation Guide**: Comprehensive questions and answers covering modular monolith architecture, JWT/CSRF security, row-level locking (`with_for_update`), optimistic answer revision counters, ACID guarantees, B-Tree index selectivity trade-offs, and TF-IDF/Logistic Regression evaluation.
3. **Demo Script Validation**: Updated [`docs/11_DEMO_AND_VIVA.md`](./11_DEMO_AND_VIVA.md) referencing the detailed live runbook.
4. **Verification**: Pre-demo checklist validated; full backend test suite passes (271 passed); frontend production build clean. Manual browser rehearsal completed (2026-10-24) confirming: ML LOW_CONFIDENCE fallback and manual topic selection on `/faculty/questions`; exam publication on `/faculty/exams`; student attempt with autosave, submission, and 100% result on `/attempts/{id}/result`; FCFS/SJF/RR/Priority Gantt charts on `/faculty/os-scheduler`; Database Lab medium-scale (1,000 students) benchmark comparison on `/faculty/database-lab`.

### Next task

1. **M7-PROJECT-WRAPUP**: Final code freeze, repository tagging, and presentation rehearsal.

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

**Document Status:** Active — Updated after M6-DEMO-PREP completion (2026-10-24, manual browser rehearsal complete)
