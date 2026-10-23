# ExamOS — Intelligent Examination & Reliability Platform

**Project:** ExamOS (B.Tech CSE AI/ML Capstone / Problem-Based Learning)
**Architecture:** Modular Monolith (FastAPI + React 18 + PostgreSQL 16)
**Status:** Milestones M0–M6 Implemented & Verified; Milestone M7 Project Wrap-Up Complete

---

## 1. Project Overview

**ExamOS** is a resilient, full-stack examination and educational systems platform designed to demonstrate distributed systems reliability, operating system process scheduling, relational database optimization, and applied machine learning:

1. **Reliable Examination Engine**: Atomic assessment publication snapshots, tamper-resistant attempts with server-authoritative deadlines (`clock_timestamp()`), optimistic answer revision concurrency, persisted answer autosave, idempotent submission finalization, and confidential answer-key handling.
2. **CPU Scheduling Simulator (OS Lab)**: Pure, deterministic educational simulator supporting FCFS, SJF, Round Robin (configurable quantum), and non-preemptive Priority scheduling with interactive Gantt timeline rendering and per-job/aggregate metrics.
3. **Database Performance Lab (DBMS Lab)**: Real execution plan comparisons (`EXPLAIN (ANALYZE, BUFFERS)`) running pre-approved parameterized query scenarios (Selective Lookup, Multi-Table Join, Aggregation) on isolated seeded benchmark datasets (`examos_lab` schema) comparing B-Tree indexed vs non-indexed execution. Never runs arbitrary user SQL.
4. **Advisory ML Topic Classifier (AI/ML Lab)**: Local TF-IDF + Logistic Regression model providing real-time question topic classification proposals with confidence scoring, graceful `LOW_CONFIDENCE` fallback, and mandatory faculty override.

---

## 2. Technology Stack & Architecture

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy 2.0 (synchronous sessions), Alembic, Pydantic v2.
- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS, Lucide Icons.
- **Database**: PostgreSQL 16 Alpine (with isolated schemas: `public` for transactional exam engine and `examos_lab` for benchmark datasets).
- **Machine Learning**: Scikit-learn 1.5+, Joblib, TF-IDF Vectorizer + Logistic Regression (8-topic CS taxonomy).
- **Security**: HttpOnly SameSite JWT cookies, double-submit CSRF tokens, salted bcrypt password hashing via Passlib, role-based access control (`STUDENT` vs `FACULTY_ADMIN`), least-privilege PostgreSQL database users.

---

## 3. Quickstart Guide (Evaluator Onboarding)

### Prerequisites

- **Git**
- **Docker & Docker Compose** (for PostgreSQL 16)
- **Python 3.11+**
- **Node.js 18+ (LTS) & npm**

---

### Step-by-Step Setup

#### 1. Clone the Repository
```powershell
git clone https://github.com/Neardy11coder/ExamOS.git
cd ExamOS
```

#### 2. Environment Configuration
Copy the provided environment template:
```powershell
Copy-Item .env.example .env
```
*(The default `.env.example` file is pre-configured with local development defaults and placeholders for containerized PostgreSQL on port `5433`)*.

#### 3. Start PostgreSQL Database
```powershell
docker compose -p examos-dev-20261016 up -d
docker compose -p examos-dev-20261016 ps
```
PostgreSQL runs on `127.0.0.1:5433`. The container automatically provisions roles and databases via `database/init-db.sh`.

#### 4. Backend Setup, Migrations & Seeding
```powershell
# Create and activate virtual environment
python -m venv backend\.venv
backend\.venv\Scripts\pip install -r backend\requirements.txt

# Run migrations and seed data from backend/
cd backend

.venv\Scripts\python.exe -m alembic upgrade head

# Seed authoritative taxonomy topics
.venv\Scripts\python.exe -m app.commands.seed_topics

# Seed Database Performance Lab dataset
.venv\Scripts\python.exe -m app.commands.seed_lab_dataset --size medium --seed 42

# Bootstrap the faculty administrator
.venv\Scripts\python.exe -m app.commands.bootstrap_faculty

# Return to project root for ML commands
cd ..
```

#### 5. ML Model Artifact Training
Train the local question topic classifier artifact (`ml/artifacts/topic_classifier.joblib` is git-ignored and reproducible):
```powershell
& backend\.venv\Scripts\python.exe -m ml.train
& backend\.venv\Scripts\python.exe -m ml.evaluate
```

#### 6. Frontend Setup
```powershell
cd frontend
npm install
npm run build   # Verifies clean TypeScript and production Vite bundling
cd ..
```

---

## 4. Running the Application

Open two terminal windows:

### Terminal 1 — FastAPI Backend Server
```powershell
cd C:\Projects\ExamOS\backend
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
- API Base URL: `http://127.0.0.1:8000`
- Interactive Swagger Docs: `http://127.0.0.1:8000/docs`
- Health Endpoint: `http://127.0.0.1:8000/api/v1/health`

### Terminal 2 — React Frontend Dev Server
```powershell
cd C:\Projects\ExamOS\frontend
npm run dev
```
- Web Application: `http://localhost:5173`

---

## 5. Default Demonstration Credentials

| Role | Email | Password | Allowed Capabilities |
|---|---|---|---|
| **Faculty Admin** | `faculty@examos.local` | Defined in `.env` (`SEED_FACULTY_PASSWORD`) | Author questions, suggest ML topics, draft & publish exams, view student attempts, run CPU scheduler, execute DB benchmarks. |
| **Student** | Self-registered at `/register` | User chosen | View published exams, start timed attempts, answer MCQs, autosave, review flags, submit & inspect results. |

---

## 6. Verification and Automated Testing

Execute the complete test suite against local PostgreSQL:

```powershell
# Run full backend test suite (271 tests across auth, exams, attempts, concurrency, scheduler, db lab, ML)
& backend\.venv\Scripts\python.exe -m pytest backend\tests\ -v

# Run frontend production build
cd frontend
npm run build
```

*Latest verified test results:*
- **Backend**: **271 passed**, 0 failed in ~39.7s.
- **Frontend**: **0 errors**, production bundle compiled cleanly via Vite.
- **Whitespace / Git formatting**: `git diff --check` passes cleanly.

---

## 7. Major Application Routes

### Student Routes
- `/` — Landing page with platform overview and sign-in.
- `/login` & `/register` — Authentication (registration defaults strictly to `STUDENT` role).
- `/dashboard` — Student dashboard with quick access to examinations.
- `/exams/available` — Catalogue of published examinations open for attempts.
- `/attempts/:id` — Live exam workspace with autosave, question navigator, and time remaining.
- `/attempts/:id/result` — Finalized examination result, score breakdown, and topic performance analytics.

### Faculty Routes
- `/faculty/dashboard` — Faculty administrative dashboard.
- `/faculty/questions` — Question Bank manager with AI/ML topic suggestion and manual overrides.
- `/faculty/exams` — Draft exam authoring, question attachment, and atomic snapshot publishing.
- `/faculty/os-scheduler` — Educational CPU scheduling simulator (FCFS, SJF, Round Robin, Priority).
- `/faculty/database-lab` — Database Performance Lab benchmark comparison tool with EXPLAIN viewer.

---

## 8. Documentation Index

For in-depth architectural and operational details, consult the `docs/` pack:
- [`docs/00_PROJECT_BRIEF.md`](./docs/00_PROJECT_BRIEF.md) — Scope, constraints, and non-goals.
- [`docs/01_REQUIREMENTS.md`](./docs/01_REQUIREMENTS.md) — Normative requirements and Appendix A clarifications.
- [`docs/02_SYSTEM_ARCHITECTURE.md`](./docs/02_SYSTEM_ARCHITECTURE.md) — System architecture, transaction strategy, and invariants.
- [`docs/03_DATABASE_DESIGN.md`](./docs/03_DATABASE_DESIGN.md) — Relational schema, indexes, and isolation model.
- [`docs/04_API_CONTRACT.md`](./docs/04_API_CONTRACT.md) — REST endpoints, status codes, and error schemas.
- [`docs/10_SETUP_AND_HANDOVER.md`](./docs/10_SETUP_AND_HANDOVER.md) — Detailed operational handover, implementation log, and verification status.
- [`docs/11_DEMO_AND_VIVA.md`](./docs/11_DEMO_AND_VIVA.md) — Live presentation structure and defense notes.
- [`docs/DEMO_RUNBOOK_AND_VIVA_GUIDE.md`](./docs/DEMO_RUNBOOK_AND_VIVA_GUIDE.md) — Step-by-step minute-by-minute evaluator runbook and comprehensive viva Q&A.
