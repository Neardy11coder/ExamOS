# ExamOS — Setup, Operations and Handover

**Version:** 0.3 · **Status:** Milestone 0 Complete  
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
APP_SECRET_KEY=replace-with-a-random-secret
DATABASE_URL=postgresql+psycopg://exam_os:local_password@localhost:5432/examos
FRONTEND_ORIGIN=http://localhost:5173
AUTH_TOKEN_TTL_MINUTES=480
COOKIE_SECURE=false
CSRF_ENABLED=true
MAX_EXAM_DURATION_MINUTES=240
MAX_QUESTIONS_PER_EXAM=100
MAX_OPTIONS_PER_QUESTION=6
MAX_SCHEDULER_JOBS=50
DBLAB_MAX_DATASET_SIZE=large
DBLAB_DEFAULT_REPETITIONS=5
ML_MODEL_PATH=../ml/artifacts/topic_classifier.joblib
ML_CONFIDENCE_THRESHOLD=0.55
EXPIRED_ATTEMPT_SWEEP_SECONDS=60
```

These are illustrative development defaults, not secure production settings. Validate all settings at startup. Generate a strong random application secret locally. `COOKIE_SECURE=false` is only for local HTTP; HTTPS deployment must enable secure cookies.

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

- **Last updated:** 2026-10-16
- **Current milestone:** Milestone 1A — Authentication (M1-AUTH-1 completed)
- **Last known good commit:** 4e6cedb — chore: ignore generated TypeScript build info
- **Working features:**
  - PostgreSQL 16 container `examos-dev-20261016-db-1` healthy on `127.0.0.1:5433`
  - Alembic migration `2efc4c54e793` (`users` table) applied to both `examos` and `examos_test`
  - `/api/v1/health` returns 200 with `database: connected`
  - `POST /api/v1/auth/register` (forces `STUDENT` role, enforces duplicate email 409, validates inputs)
  - `POST /api/v1/auth/login` (sets HttpOnly JWT cookie `examos_access` + JS-readable CSRF cookie `examos_csrf`, returns generic 401 on invalid/deactivated credentials)
  - `POST /api/v1/auth/logout` (clears cookies, requires valid JWT + CSRF header `X-CSRF-Token`)
  - `GET /api/v1/auth/me` (returns authenticated user profile; requires valid JWT cookie)
  - Password hashing via bcrypt (`passlib[bcrypt]`), JWT via HS256 (`PyJWT`), CSRF via 32-byte hex tokens
  - Role guard dependencies (`require_student`, `require_faculty`)
  - Frontend TypeScript compiles and production build succeeds
- **Failing tests / known bugs:** None. All 39 backend tests passing.

### Commands verified

| Command | Environment | Result | Date |
|---|---|---|---|
| `docker compose -p examos-dev-20261016 up -d` | Windows / Docker Desktop | Container `examos-dev-20261016-db-1` healthy on `127.0.0.1:5433` | 2026-10-16 |
| `pip install -r backend\requirements.txt` | Python 3.11.9, venv | All packages including `email-validator==2.3.0` installed | 2026-10-16 |
| `pytest backend\tests\test_auth.py -v` | Python 3.11.9, venv | 37 passed against `examos_test` | 2026-10-16 |
| `pytest backend\tests\ -v` | Python 3.11.9, venv | 39 passed (37 auth + 2 health) | 2026-10-16 |
| `alembic upgrade head` (from `backend/`) | Python 3.11.9, venv | Applied revision `2efc4c54e793` to `examos` and `examos_test` | 2026-10-16 |
| `npm run build` (from `frontend/`) | Node.js LTS, Vite | Production build succeeded (`tsc -b && vite build`) | 2026-10-16 |

### Next three tasks

1. **M1-AUTH-2**: Seed faculty user from `SEED_FACULTY_EMAIL` / `SEED_FACULTY_PASSWORD` env vars / management command; verify role boundary invariants.
2. **M1-SCHEMA-1**: Create Alembic migration for `topics`, `examinations`, `questions`, `options` tables; implement faculty question-bank CRUD endpoints per `docs/04_API_CONTRACT.md`.
3. **M1-EXAM-1**: Exam authoring & publishing workflow with immutable snapshot upon publication.

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
