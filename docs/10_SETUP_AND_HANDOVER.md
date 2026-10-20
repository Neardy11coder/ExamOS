# ExamOS — Setup, Operations and Handover

**Version:** 0.4 · **Status:** M1-AUTH-3 Complete — Frontend Authentication UI
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

- **Last updated:** 2026-10-21
- **Current milestone:** Milestone 1 — Core Examination Database Schema (M1-SCHEMA-1 completed)
- **Last known good commit:** 8fc1dab — fix(auth): scope local email validation to development
- **Uncommitted local changes (untracked / modified):**
  - Infrastructure & Config: `.gitattributes`, `database/init-db.sh`, `docker-compose.yml`, `.env.example`, `backend/alembic/env.py`
  - Migrations: `backend/alembic/versions/20261020_0cb900c103a1_grant_provisioner_users_permissions.py`, `backend/alembic/versions/20261021_e4a1f8b2c9d0_create_core_examination_schema.py`
  - ORM Models: `backend/app/models/topic.py`, `backend/app/models/question.py`, `backend/app/models/exam.py`, `backend/app/models/__init__.py`
  - Tests: `backend/tests/test_exam_schema.py`
  - Frontend auth & components: `frontend/package.json`, `frontend/package-lock.json`, `frontend/index.html`, `frontend/src/App.tsx`, `frontend/src/main.tsx`, `frontend/src/styles/index.css`, `frontend/src/api/auth.ts`, `frontend/src/components/`, `frontend/src/contexts/`, `frontend/src/pages/`
- **Implemented and verified in M1-SCHEMA-1:**
  - Alembic migration `e4a1f8b2c9d0` created from parent `0cb900c103a1`
  - Core examination and question schema created per `docs/03_DATABASE_DESIGN.md` §§3.2–3.7:
    - `topics`: UUID PK, unique code and name, subject check ('OS', 'DBMS'), is_active, timestamptz audit columns.
    - `questions`: UUID PK, author_id FK (`users.id` RESTRICT), topic_id nullable FK (`topics.id` SET NULL), non-empty prompt check, archived_at timestamptz.
    - `question_options`: UUID PK, question_id FK (`questions.id` RESTRICT), non-empty option_text, display_order >= 1, is_correct, unique `(question_id, display_order)`, partial unique index ensuring at most one correct option.
    - `exams`: UUID PK, creator_id FK (`users.id` RESTRICT), title non-empty, duration_minutes > 0, status check ('DRAFT', 'PUBLISHED', 'UNPUBLISHED'), published_at, audit columns.
    - `exam_questions`: UUID PK, exam_id FK (`exams.id` RESTRICT), source_question_id FK (`questions.id` RESTRICT), prompt_snapshot, topic_code_snapshot, topic_name_snapshot, marks numeric > 0, display_order >= 1, unique `(exam_id, display_order)`, unique `(id, exam_id)`.
    - `exam_question_options`: UUID PK, exam_question_id FK (`exam_questions.id` RESTRICT), option_text_snapshot, display_order >= 1, is_correct, unique `(exam_question_id, display_order)`, unique `(exam_question_id, id)`, partial unique index ensuring at most one correct option.
  - Snapshot immutability: verified that publication snapshot tables preserve frozen question prompts, options, marks, and topic labels independently from subsequent authoring bank modifications.
  - Migration verification: verified fresh install migration on disposable container (base -> head and downgrade head -> base), development database (`examos`) at `e4a1f8b2c9d0 (head)`, and test database (`examos_test`) at `e4a1f8b2c9d0 (head)`.
  - All 111 backend tests passing (`pytest backend/tests/ -q`) with 0 failures (93 pre-existing + 18 new schema and constraint tests).
  - Frontend TypeScript check (`tsc -b`) passing with 0 errors.
  - Frontend production build (`npm run build`) passing with 0 errors and 0 warnings.
- **Implemented but not verified end to end in browser:**
  - Full browser-driven UI interactive flows (`/login`, `/register`, `/dashboard`, session persistence on reload, public-only route redirects, in-browser logout). Playwright browser binaries cannot be downloaded in this sandboxed environment (`404 Not Found` from Azure CDN). Requires manual browser verification.
- **Test status:** 111 backend tests passed, 16 warnings (Starlette TestClient deprecation warning, transaction rollback warnings); `tsc -b` 0 errors; `npm run build` exit 0 (0 warnings).

### Commands verified

| Command | Environment | Result | Date |
|---|---|---|---|
| `docker compose -p examos-dev-20261016 up -d` | Windows / Docker Desktop | Container healthy on `127.0.0.1:5433` | 2026-10-16 |
| `pip install -r backend\requirements.txt` | Python 3.11.9, venv | All packages installed | 2026-10-16 |
| `pytest backend\tests\ -q` | Python 3.11.9, venv | 111 passed, 16 warnings | 2026-10-21 |
| `alembic current` (from `backend/`) | Python 3.11.9, venv | `e4a1f8b2c9d0 (head)` verified on dev database `examos` | 2026-10-21 |
| `SELECT version_num FROM alembic_version` | PostgreSQL (`examos_test`) | `e4a1f8b2c9d0` verified on test database `examos_test` | 2026-10-21 |
| Fresh DB migration upgrade & downgrade | PostgreSQL 16 container | Base -> Head -> Base verified cleanly | 2026-10-21 |
| `python -m app.commands.bootstrap_faculty` | Python 3.11.9, venv | Provisioned `FACULTY_ADMIN`; idempotent | 2026-10-16 |
| `npx tsc -b` (from `frontend/`) | Node.js LTS | 0 errors | 2026-10-20 |
| `npm run build` (from `frontend/`) | Node.js LTS, Vite | Exit 0; 0 warnings, 0 errors | 2026-10-21 |
| `git diff --check` | Git on Windows | Exit 0 | 2026-10-21 |

### Next three tasks

1. **M1-EXAM-1**: Faculty question-bank CRUD endpoints (`/questions`) and exam authoring/publish/unpublish workflow with atomic immutable snapshot creation per `docs/04_API_CONTRACT.md`.
2. **M1-ATTEMPT-1**: Student exam attempt lifecycle (`IN_PROGRESS` → durable answer saves → deadline enforcement → `SUBMITTED`/`EXPIRED` finalization).
3. **M1-STUD-UI-1**: Student exam taking UI (catalogue, start attempt, question selection, mark for review, timer, submit, results).

### Decisions not to re-open without a real issue

- Modular monolith; no microservices.
- PostgreSQL is required for critical transaction tests.
- No persisted `CREATED` attempt state; explicit start creates `IN_PROGRESS` atomically.
- Exclusive database-time deadline boundary.
- Published exam snapshot is immutable.
- One attempt ever per student/exam in v1.
- Scheduler uses the documented non-preemptive priority/tie rules.
- No arbitrary SQL and no external AI service.

## 10. Handover prompt for a new coding-agent session

Copy this prompt into a new Codex/agent session after opening the repository:

> You are continuing the ExamOS project. First read `AGENTS.md`, `README.md`, `docs/00_PROJECT_BRIEF.md`, `docs/01_REQUIREMENTS.md` including Appendix A, `docs/02_SYSTEM_ARCHITECTURE.md`, and `docs/10_SETUP_AND_HANDOVER.md`. Inspect the actual repository and Git status before changing files. Treat the requirements Appendix A and system architecture as the resolved design baseline. Do not claim features or tests exist unless verified in the repository. Report current implementation status, the next smallest task from the roadmap, its relevant requirement IDs, files to touch, and tests to run. Implement one bounded task at a time; preserve transaction, deadline, answer-key confidentiality, and lab-isolation invariants. If documentation and code disagree, report the discrepancy instead of silently rewriting requirements.

**Document Status:** Active — Updated after Milestone 0 completion (2026-10-16)
