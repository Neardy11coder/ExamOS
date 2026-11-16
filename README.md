# ExamOS — Intelligent Examination & Reliability Platform

[![Production Status](https://img.shields.io/badge/Production-Live-success?style=flat-square&logo=cloudflare)](https://examos-cts.pages.dev)
[![Staging Status](https://img.shields.io/badge/Staging-Online-blue?style=flat-square&logo=cloudflare)](https://examos-staging.pages.dev)
[![Backend](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com)
[![Frontend](https://img.shields.io/badge/React-18.3-61DAFB?style=flat-square&logo=react)](https://react.dev)
[![Database](https://img.shields.io/badge/PostgreSQL-16.16-4169E1?style=flat-square&logo=postgresql)](https://www.postgresql.org)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.6-3178C6?style=flat-square&logo=typescript)](https://www.typescriptlang.org)
[![Tests](https://img.shields.io/badge/Tests-332%20Passed-brightgreen?style=flat-square&logo=pytest)](https://pytest.org)

**ExamOS** is a resilient, cloud-native examination and educational systems platform built as a modular monolith. It demonstrates distributed systems fault tolerance, operating system CPU scheduling, relational database performance benchmarking, and advisory machine learning in a single cohesive architecture.

---

## Live Deployments

- **Production Application**: [https://examos-cts.pages.dev](https://examos-cts.pages.dev)
  - Direct Backend API: `https://backend-prod-production-4aade984.up.railway.app`
  - Health Endpoint: [https://examos-cts.pages.dev/api/v1/health](https://examos-cts.pages.dev/api/v1/health)
- **Staging Application**: [https://examos-staging.pages.dev](https://examos-staging.pages.dev)
  - Direct Backend API: `https://backend-production-5837298c.up.railway.app`
  - Health Endpoint: [https://examos-staging.pages.dev/api/v1/health](https://examos-staging.pages.dev/api/v1/health)

---

## Table of Contents

1. [Key Capabilities](#1-key-capabilities)
2. [User Features & Workflows](#2-user-features--workflows)
3. [Examination Lifecycle & Reliability Engineering](#3-examination-lifecycle--reliability-engineering)
4. [Educational Simulation Labs](#4-educational-simulation-labs)
5. [System Architecture](#5-system-architecture)
6. [Technology Stack](#6-technology-stack)
7. [Database Schema & Migrations](#7-database-schema--migrations)
8. [Security & Authentication Model](#8-security--authentication-model)
9. [Application Screenshots](#9-application-screenshots)
10. [Local Development Setup](#10-local-development-setup)
11. [Configuration Reference](#11-configuration-reference)
12. [Verification & Testing](#12-verification--testing)
13. [Production Deployment Architecture](#13-production-deployment-architecture)
14. [Documentation Index](#14-documentation-index)
15. [Contribution & License](#15-contribution--license)

---

## 1. Key Capabilities

1. **High-Integrity Examination Engine**:
   - Atomic publication snapshots protecting historical examination data from subsequent question-bank mutations.
   - Server-authoritative deadlines driven by PostgreSQL `clock_timestamp()`.
   - Optimistic concurrency control for answer saves preventing lost updates across flaky network connections.
   - Lazy deadline finalization guaranteeing state consistency without requiring continuous background worker polling.
   - Zero disclosure of correct answer options or scoring keys during active examination attempts.
2. **Deterministic CPU Scheduling Simulator (OS Lab)**:
   - Pure, deterministic simulation of First-Come First-Served (FCFS), Shortest Job First (SJF), Round Robin (configurable quantum), and Non-Preemptive Priority scheduling.
   - Visual Gantt chart timeline rendering, process lifecycle tracking, and aggregate metrics calculation (Average Turnaround Time, Waiting Time, Response Time, CPU Throughput).
3. **Isolated Database Performance Lab (DBMS Lab)**:
   - Real PostgreSQL query execution comparisons (`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`).
   - Evaluates point lookups, equi-joins, and grouped aggregations across synthetic datasets (small, medium, large) on isolated paired tables (`examos_lab` schema: with-index vs without-index).
   - Strictly parameterized execution; rejects arbitrary client SQL requests by design.
4. **Advisory Question Topic Classifier (AI/ML Lab)**:
   - Real-time topic classification for MCQ prompts across an 8-topic computer science taxonomy.
   - Lightweight local TF-IDF + Logistic Regression baseline with fine-tuned DistilBERT transformer adapter support.
   - Advisory only: enforces confidence thresholds and requires explicit faculty approval before tagging questions.

---

## 2. User Features & Workflows

### Student Workflows
- **Self-Registration & Authentication**: Direct registration strictly assigning the `STUDENT` role; case-insensitive email normalization and secure session cookie issuance.
- **Examination Catalog**: Real-time listing of active, published examinations eligible for attempts.
- **Examination Workspace**: Timed test environment with live countdown, question palette, review flags, and persisted answer auto-saving.
- **Instant Result Breakdown**: Finalized score display, percentage calculation, and topic-level performance analysis available immediately upon authorized submission.

### Faculty Workflows
- **Question Bank Management**: Author, edit, and soft-archive multiple-choice questions with 2–6 options and rich markdown prompts.
- **AI-Assisted Classification**: Trigger the local ML topic classifier to suggest appropriate taxonomy categories with confidence scores.
- **Draft Examination Authoring**: Create examinations, configure durations, attach questions, reorder display sequences, and assign individual question marks.
- **Atomic Snapshot Publishing**: Transition draft exams to immutable published snapshots, locking assessment configuration against retroactive bank modifications.
- **Interactive Labs**: Access the educational OS CPU Scheduler and Database Performance Lab benchmark suite directly from the faculty portal.

---

## 3. Examination Lifecycle & Reliability Engineering

```mermaid
stateDiagram-v2
    [*] --> DRAFT : Faculty authors exam
    DRAFT --> PUBLISHED : Atomic publication snapshot
    PUBLISHED --> IN_PROGRESS : Student starts attempt

    state IN_PROGRESS {
        [*] --> Answering
        Answering --> Saving : Student selects option
        Saving --> Saved : Optimistic revision confirmed
        Saved --> Answering : Revision incremented
    }

    IN_PROGRESS --> SUBMITTED : Student submits before deadline
    IN_PROGRESS --> EXPIRED : Lazy finalization on retrieval post-deadline

    SUBMITTED --> [*] : Results & correct options unlocked
    EXPIRED --> [*] : Results & correct options unlocked
```

### 1. Atomic Snapshot Publishing
When a faculty author publishes an examination, ExamOS captures an immutable snapshot of all attached questions, options, and point weightings in a single database transaction. Subsequent edits or deletions in the question bank never mutate a published or historical examination.

### 2. Optimistic Concurrency Control
Answer updates enforce explicit revision checking:
```http
PUT /api/v1/attempts/{attempt_id}/answers/{exam_question_id}
Content-Type: application/json
X-CSRF-Token: <token>

{
  "selected_option_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "marked_for_review": false,
  "expected_revision": 1
}
```
If an overlapping save has already committed, the server rejects the stale request with `HTTP 409 Conflict`, ensuring consistent state transitions.

### 3. Server-Authoritative Deadlines & Lazy Expiry
Attempt durations and deadlines are calculated and stored in database time:
$$\text{deadline\_at} = \text{started\_at} + (\text{duration\_minutes} \times 60)$$
Any request to save an answer after `deadline_at` is rejected. If an attempt is queried or submitted post-deadline, the server lazily finalizes the attempt as `EXPIRED`, computes the final score from answers saved before the cutoff, and commits the terminal state atomically.

---

## 4. Educational Simulation Labs

### Operating System CPU Scheduling Simulator
Designed to explore classic CPU scheduling behavior without operating system overhead:
- **FCFS (First-Come First-Served)**: Demonstrates the convoy effect when compute-heavy jobs precede short bursts.
- **SJF (Shortest Job First - Non-Preemptive)**: Demonstrates optimal average waiting time for batch jobs.
- **Round Robin**: Demonstrates time-sliced fairness with configurable quantum sizes ($q$) and context-switch boundaries.
- **Priority (Non-Preemptive)**: Simulates priority dispatching with strict arrival-time tie breaking.

### Database Performance Lab
Provides live empirical validation of relational database indexing principles:
- **Point Lookup (`selective_lookup`)**: Demonstrates B-Tree unique index traversal ($O(\log N)$) vs full table sequential heap scans.
- **Equi-Join (`join_students_enrollments`)**: Demonstrates index-assisted nested loop joins vs hash joins.
- **Grouped Aggregation (`aggregation_department_gpa`)**: Demonstrates index-assisted grouping vs hash aggregation.
- **Safety Boundary**: Benchmarks execute exclusively on isolated tables (`examos_lab.lab_students_*`, `examos_lab.lab_enrollments_*`). No arbitrary SQL input is permitted from the client.

---

## 5. System Architecture

ExamOS follows a **modular monolith** design deployed across cloud edge, application, and database layers:

```mermaid
flowchart TD
    subgraph ClientBrowser["Client Browser"]
        SPA["React 18 SPA (TypeScript + Vite)"]
    end

    subgraph Cloudflare["Cloudflare Pages Edge"]
        StaticAssets["Static Asset CDN (dist/)"]
        EdgeProxy["Pages Function Reverse Proxy (functions/api/[[path]].ts)"]
    end

    subgraph Railway["Railway Cloud Platform"]
        FastAPI["FastAPI Application Backend (Python 3.13)"]
        MLClassifier["Local ML Model (TF-IDF / DistilBERT)"]
        SchedulerEngine["Deterministic CPU Scheduler Engine"]
    end

    subgraph Neon["Neon Serverless PostgreSQL 16"]
        subgraph PublicSchema["public Schema"]
            UsersTable["users (RLS active)"]
            ExamsTable["exams & snapshots"]
            AttemptsTable["attempts & attempt_answers"]
            AuditTable["benchmark_runs"]
        end
        subgraph LabSchema["examos_lab Schema (Isolated)"]
            IndexedTables["lab_students_indexed / enrollments"]
            UnindexedTables["lab_students_no_index / enrollments"]
        end
    end

    SPA -->|Static Requests| StaticAssets
    SPA -->|/api/* Requests + First-Party Cookies| EdgeProxy
    EdgeProxy -->|HTTPS Proxy + Hop-by-Hop Sanitization| FastAPI
    FastAPI --> MLClassifier
    FastAPI --> SchedulerEngine
    FastAPI -->|psycopg Connection Pool (examos_app)| PublicSchema
    FastAPI -->|Read-Only Benchmark Execution| LabSchema
```

---

## 6. Technology Stack

| Layer | Technologies | Rationale |
| :--- | :--- | :--- |
| **Frontend** | React 18, TypeScript, Vite, Tailwind CSS, Lucide Icons | Responsive modern UI, type safety, instant hot reloading, and minimal bundle footprint. |
| **Backend** | FastAPI, Python 3.11/3.13, Pydantic v2, Uvicorn | High-throughput asynchronous routing with strict schema validation and auto-generated OpenAPI contracts. |
| **Database** | PostgreSQL 16, SQLAlchemy 2.0, Alembic, Psycopg 3 | ACID guarantees, complex relational integrity, check constraints, Row-Level Security, and migration history. |
| **Edge Proxy** | Cloudflare Pages Functions (TypeScript) | Transparent zero-cost reverse proxy rewriting upstream cookies to first-party browser origin. |
| **Machine Learning** | Scikit-learn 1.5, Joblib, PyTorch, Hugging Face Transformers | Advisory topic classification supporting both lightweight TF-IDF and fine-tuned DistilBERT pipelines. |
| **Infrastructure** | Cloudflare Pages + Railway + Neon PostgreSQL | Zero-cost serverless hosting with strict memory boundaries ($5.00/month flat total spend). |

---

## 7. Database Schema & Migrations

The database is partitioned into two schemas:
1. `public`: Houses user identities, role assignments, questions, options, published examinations, snapshots, candidate attempts, and answer revisions.
2. `examos_lab`: Completely isolated schema housing synthetic benchmark datasets with paired indexed and non-indexed tables.

### Least-Privilege Database Roles
ExamOS enforces strict role separation across its operational lifecycle:
- `examos_migrator`: Executes Alembic migrations (`alembic upgrade head`). Granted temporary `CREATE` on the database during migration runs, revoked immediately afterward.
- `examos_app`: Runtime application role. Granted DML (`SELECT, INSERT, UPDATE, DELETE`) on application tables, read-only `SELECT` on `examos_lab.*` and `alembic_version`, and subject to Row-Level Security on `public.users`.
- `examos_provisioner`: Dedicated role executing the `SECURITY DEFINER` stored procedure `public.provision_faculty_account(...)` during faculty bootstrapping. Locked post-bootstrap (`ALTER ROLE examos_provisioner NOLOGIN`).
- `examos_test_runner`: Owner and runner of isolated automated test suites on `examos_test`.

### Current Alembic Revision
- Head Revision: `d1e2f3a4b5c6` (`eliminate password hash disclosure and enforce case insensitive email`).

---

## 8. Security & Authentication Model

1. **Authentication & JWT Cookies**:
   - Authentication returns an encrypted JSON Web Token (JWT) signed with `HS256`.
   - Delivered exclusively via `HttpOnly`, `SameSite=Lax`, `Secure` cookies (`examos_access`).
   - JavaScript code in the browser has zero access to the authentication token, neutralizing XSS credential theft.
2. **Double-Submit CSRF Protection**:
   - On login, a cryptographically secure CSRF token is issued in an accessible cookie (`examos_csrf`) and in the response body.
   - All state-mutating requests (`POST`, `PUT`, `PATCH`, `DELETE`) require the `X-CSRF-Token` header.
   - The server verifies that the header token matches the signed CSRF cookie before executing request handlers.
3. **Password Security**:
   - Passwords hashed using salted `bcrypt` with work factor 12 via Passlib.
   - Case-insensitive email normalization (`lower(email)`) with unique index constraints (`uq_users_lower_email`).
   - Stored procedures never accept or return raw password hashes.
4. **PostgreSQL Row-Level Security (RLS)**:
   - RLS is permanently active on `public.users`.
   - Prevents unauthorized access or bypasses even if application query logic fails.

---

## 9. Application Screenshots

| Screen | Description |
| :---: | :--- |
| ![Sign In Screen](./docs/screenshots/01_login.png) | **Sign In Screen**: Clean, responsive authentication interface enforcing double-submit CSRF tokens and HttpOnly session cookies. |
| ![Faculty Dashboard](./docs/screenshots/02_faculty_dashboard.png) | **Faculty Dashboard**: Central administrative hub providing navigation across Examinations, Question Bank, OS Simulator, and Database Lab. |
| ![Examinations Registry](./docs/screenshots/03_examinations_registry.png) | **Examinations Registry**: Management view displaying published immutable examination snapshots, point totals, durations, and status badges. |
| ![Question Bank & Taxonomy](./docs/screenshots/04_question_bank_taxonomy.png) | **Question Bank**: Authoring environment with topic filtering across the 8-category computer science taxonomy and AI-assisted classification. |

---

## 10. Local Development Setup

### Prerequisites
- **Git**
- **Python 3.11+**
- **Node.js 18+ (LTS) & npm**
- **Docker & Docker Compose** (for PostgreSQL 16)

### 1. Clone the Repository
```powershell
git clone https://github.com/Neardy11coder/ExamOS.git
cd ExamOS
```

### 2. Environment Configuration
Copy the provided environment template:
```powershell
Copy-Item .env.example .env
```

### 3. Start PostgreSQL Container
```powershell
docker compose -p examos-dev-20261016 up -d
docker compose -p examos-dev-20261016 ps
```
The container boots PostgreSQL 16 on port `5433` and initializes least-privilege roles automatically.

### 4. Backend Setup & Migrations
```powershell
# Create and activate virtual environment
python -m venv backend\.venv
backend\.venv\Scripts\pip install -r backend\requirements.txt

# Run migrations and seed data
cd backend
.venv\Scripts\python.exe -m alembic upgrade head

# Seed 8 authoritative taxonomy topics
.venv\Scripts\python.exe -m app.commands.seed_topics

# Seed Database Lab benchmark dataset (Medium: 1,000 students, 4,000 enrollments)
.venv\Scripts\python.exe -m app.commands.seed_lab_dataset --size medium --seed 42

# Bootstrap default faculty administrator interactively
.venv\Scripts\python.exe -m app.commands.bootstrap_faculty --prompt-password

cd ..
```

### 5. Train Local ML Classifier
```powershell
backend\.venv\Scripts\python.exe -m ml.train
backend\.venv\Scripts\python.exe -m ml.evaluate
```

### 6. Frontend Setup
```powershell
cd frontend
npm install
npm run build
cd ..
```

### 7. Run Applications Locally
Open two terminal windows:
```powershell
# Terminal 1: Backend API (FastAPI)
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
```powershell
# Terminal 2: Frontend SPA (Vite)
cd frontend
npm run dev
```
- Frontend Web App: `http://localhost:5173`
- Backend API Docs: `http://127.0.0.1:8000/docs`
- Health Check: `http://127.0.0.1:8000/api/v1/health`

---

## 11. Configuration Reference

The application consumes configuration from environment variables defined in `.env.example`:

| Variable | Description | Example / Default |
| :--- | :--- | :--- |
| `APP_ENV` | Environment identifier (`development`, `staging`, `production`) | `development` |
| `APP_SECRET_KEY` | Cryptographic secret for signing JWT tokens | `PLACEHOLDER_SECRET_KEY` |
| `DATABASE_URL` | Application runtime database connection string (`examos_app`) | `postgresql+psycopg://examos_app:...@localhost:5433/examos` |
| `MIGRATION_DATABASE_URL` | Schema migration connection string (`examos_migrator`) | `postgresql+psycopg://examos_migrator:...@localhost:5433/examos` |
| `TEST_DATABASE_URL` | Automated test database connection string (`examos_test_runner`) | `postgresql+psycopg://examos_test_runner:...@localhost:5433/examos_test` |
| `PROVISIONER_DATABASE_URL` | Stored procedure execution string (`examos_provisioner`) | `postgresql+psycopg://examos_provisioner:...@localhost:5433/examos` |
| `FRONTEND_ORIGIN` | Allowed CORS origin matching frontend domain | `http://localhost:5173` |
| `COOKIE_SECURE` | Set `true` in production to require HTTPS for cookies | `false` (local) / `true` (prod) |
| `CSRF_ENABLED` | Enables double-submit CSRF header validation | `true` |
| `AUTH_TOKEN_TTL_MINUTES` | Access token time-to-live in minutes | `480` (8 hours) |
| `MAX_EXAM_DURATION_MINUTES` | Upper boundary for examination durations | `240` |
| `ML_MODEL_PATH` | Path to trained serialized topic classifier artifact | `../ml/artifacts/topic_classifier.joblib` |
| `ML_CONFIDENCE_THRESHOLD` | Minimum confidence required for auto-selection | `0.55` |

---

## 12. Verification & Testing

ExamOS maintains an extensive automated testing suite covering unit, integration, concurrency, security, and edge proxy behaviors:

```powershell
# Run full backend test suite (332 tests)
backend\.venv\Scripts\python.exe -m pytest backend\tests\ -v

# Run frontend TypeScript type checking and production build
npm --prefix frontend run build

# Run Git whitespace validation
git diff --check
```

### Verified Test Suite Metrics
- **Backend Tests**: **332 passed**, 0 failed (48.97s runtime across authentication, attempts, schema constraints, deadline enforcement, optimistic concurrency, scheduler invariants, database lab, and ML suggestions).
- **Frontend Build**: **0 errors**, production asset bundle generated cleanly in 1.90s.
- **Whitespace / Formatting**: `git diff --check` passes cleanly with zero whitespace defects.

---

## 13. Production Deployment Architecture

ExamOS is architected for a zero-cost cloud deployment across three serverless tiers:

1. **Frontend Hosting (Cloudflare Pages)**:
   - Static asset hosting with global edge distribution.
   - Built with `npm run build` and deployed using Wrangler.
   - Project: `examos` live at `https://examos-cts.pages.dev`.
2. **Edge Reverse Proxy (Cloudflare Pages Functions)**:
   - TypeScript Function (`functions/api/[[path]].ts`) route-matched via `_routes.json`.
   - Strips upstream `Domain` attributes from `Set-Cookie` headers, allowing HttpOnly cookies to bind cleanly to the first-party frontend origin.
   - Enforces RFC 7230 hop-by-hop header stripping and Location header sanitization.
3. **Backend Service (Railway)**:
   - Single-worker Uvicorn deployment (`--workers 1`) bounding memory footprint to 512 MB RAM.
   - Service: `backend-prod` live at `https://backend-prod-production-4aade984.up.railway.app`.
   - Healthcheck: `/api/v1/health` with automatic restart policy on failure.
4. **Managed Database (Neon Serverless PostgreSQL 16)**:
   - Hosted on AWS Singapore (`ap-southeast-1`).
   - Serverless scale-to-zero compute (0.25 CU minimum) and point-in-time branch backups (`pre-release-prod-backup`).
   - Strict least-privilege role segregation between migration, provisioning, and runtime roles.

---

## 14. Documentation Index

For exhaustive architecture and operational specifications, consult the documents in `docs/`:

- [`docs/00_PROJECT_BRIEF.md`](./docs/00_PROJECT_BRIEF.md) — Problem statement, functional boundaries, and non-goals.
- [`docs/01_REQUIREMENTS.md`](./docs/01_REQUIREMENTS.md) — Normative requirements and Appendix A technical clarifications.
- [`docs/02_SYSTEM_ARCHITECTURE.md`](./docs/02_SYSTEM_ARCHITECTURE.md) — System architecture, transaction strategy, and invariants.
- [`docs/03_DATABASE_DESIGN.md`](./docs/03_DATABASE_DESIGN.md) — Relational schema, indexes, and schema isolation models.
- [`docs/04_API_CONTRACT.md`](./docs/04_API_CONTRACT.md) — REST endpoints, status codes, and error schemas.
- [`docs/10_SETUP_AND_HANDOVER.md`](./docs/10_SETUP_AND_HANDOVER.md) — Operational handover, milestone logs, and verification status.
- [`docs/11_DEMO_AND_VIVA.md`](./docs/11_DEMO_AND_VIVA.md) — Presentation structure and defense notes.
- [`docs/13_CLOUD_DEPLOYMENT_RUNBOOK.md`](./docs/13_CLOUD_DEPLOYMENT_RUNBOOK.md) — Cloud deployment runbook for Cloudflare, Railway, and Neon.
- [`docs/DEMO_RUNBOOK_AND_VIVA_GUIDE.md`](./docs/DEMO_RUNBOOK_AND_VIVA_GUIDE.md) — Evaluator demo script and viva question & answer guide.

---

## 15. Contribution & License

ExamOS is developed as an academic capstone and educational platform demonstrating distributed systems reliability and computer science principles. All rights reserved by the repository authors.

For code reviews, academic evaluations, or collaborative inquiries, please submit an issue or pull request following the repository's modular monolith and test-driven development guidelines.
