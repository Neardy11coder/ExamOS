# ExamOS — Cloud Deployment Runbook (Cloudflare Pages + Railway)

**Project:** ExamOS — Intelligent Examination & Reliability Platform  
**Target Environment:**
- **Frontend:** Cloudflare Pages (React 18 / TypeScript SPA via Vite)
- **Backend:** Railway Hobby (FastAPI / Python 3.11 web service, Singapore region `sin`)
- **Database:** Railway PostgreSQL 16 (Singapore region `sin`)
- **Reverse Proxy Routing:** Cloudflare Pages Function (`frontend/functions/api/[[path]].ts`) proxying `/api` and `/api/*` to Railway backend via explicit `frontend/public/_routes.json`

---

## 1. Architectural Strategy & Cookie/CSRF Integrity

ExamOS uses HttpOnly SameSite JWT cookies (`examos_access`) and a double-submit CSRF cookie (`examos_csrf`) read by the frontend to send the `X-CSRF-Token` header.

To preserve secure, first-party cookie behavior across distributed cloud hosts:
1. The React frontend is deployed to **Cloudflare Pages** (Build root: `frontend`, Build command: `npm run build`, Output directory: `dist`).
2. Cloudflare Pages acts as the single public entry point for users (`https://<project>.pages.dev`).
3. An explicit `frontend/public/_routes.json` defines routing boundaries:
   ```json
   {
     "version": 1,
     "include": ["/api", "/api/*"],
     "exclude": []
   }
   ```
   This guarantees that only API calls trigger the Pages Function, while static assets and client-side SPA routes are served at zero function invocation cost directly from Cloudflare edge caches.
4. The Cloudflare Pages Function reverse proxy (`frontend/functions/api/[[path]].ts`):
   - Validates `BACKEND_ORIGIN` (rejects non-HTTPS in production, credentials, query strings, and subpaths).
   - Strips `Host` and all hop-by-hop headers (RFC 7230 §6.1) including headers nominated by the `Connection` header.
   - Forwards client IP via `CF-Connecting-IP` as `X-Forwarded-For`.
   - Separates multiple `Set-Cookie` headers via standard `response.headers.getSetCookie()` to prevent comma-concatenation.
   - Accurately strips upstream `Domain` attributes so cookies bind to the Pages frontend host.
   - Never logs tokens, credentials, or internal connection parameters.
5. In the backend, `FRONTEND_ORIGIN` is configured to `https://<project>.pages.dev` (or your custom domain) to enforce strict CORS and origin matching.

---

## 2. Production Environment Variables Reference

### Railway Backend Service Variables

Configure these environment variables in your **Railway** backend service settings:

| Variable Name | Required | Secret? | Production Guidance |
|---|---|---|---|
| `APP_ENV` | Yes | No | Set to `production`. Disables OpenAPI `/docs` and enforces strict domain validation. |
| `APP_SECRET_KEY` | Yes | **YES** | 64+ character random hex string (`openssl rand -hex 32`). Used for HS256 JWT signing. |
| `DATABASE_URL` | Yes | **YES** | Runtime connection string for application user: `postgresql+psycopg://examos_app:<PASSWORD>@<HOST>:<PORT>/<DB>`. (Use Railway private network domain if within same project). |
| `MIGRATION_DATABASE_URL` | Yes | **YES** | Schema management connection string: `postgresql+psycopg://examos_migrator:<PASSWORD>@<HOST>:<PORT>/<DB>`. |
| `FRONTEND_ORIGIN` | Yes | No | Production Cloudflare Pages domain, e.g. `https://examos.pages.dev` (strictly no trailing slash). |
| `COOKIE_SECURE` | Yes | No | Set to `true` to require HTTPS for session and CSRF cookies. |
| `CSRF_ENABLED` | Yes | No | Set to `true` to enforce double-submit CSRF protection on mutating endpoints. |
| `AUTH_TOKEN_TTL_MINUTES` | No | No | `480` (8-hour session lifetime). |
| `SEED_FACULTY_EMAIL` | Yes | No | Production-valid email with fully qualified domain (e.g. `faculty@examos.edu` — NOT `.local`). |
| `SEED_FACULTY_PASSWORD` | Optional | **YES** | If set, used by initial bootstrap. If unset, bootstrap prompts interactively with `--prompt-password`. |
| `ML_MODEL_PATH` | No | No | `../ml/artifacts/distilbert_classifier` (or `../ml/artifacts/topic_classifier.joblib`). |
| `ML_FALLBACK_MODEL_PATH` | No | No | `../ml/artifacts/topic_classifier.joblib` (guarantees lightweight fallback). |
| `ML_CONFIDENCE_THRESHOLD` | No | No | `0.55` (conservative threshold to suppress false positives). |
| `MAX_EXAM_DURATION_MINUTES`| No | No | `240` |
| `MAX_QUESTIONS_PER_EXAM` | No | No | `100` |
| `MAX_OPTIONS_PER_QUESTION` | No | No | `6` |
| `MAX_SCHEDULER_JOBS` | No | No | `50` |
| `DBLAB_MAX_DATASET_SIZE` | No | No | `large` |
| `DBLAB_DEFAULT_REPETITIONS`| No | No | `5` |
| `EXPIRED_ATTEMPT_SWEEP_SECONDS` | No | No | `60` |

### Cloudflare Pages Variables

Configure in **Cloudflare Pages -> Project Settings -> Environment Variables**:

| Variable Name | Required | Secret? | Production Guidance |
|---|---|---|---|
| `BACKEND_ORIGIN` | Yes | No | Public Railway backend URL, e.g. `https://examos-backend-production.up.railway.app` (strictly HTTPS, no credentials, no query string, no trailing slash). |

---

## 3. Database Provisioning & Least-Privilege Role Model

ExamOS enforces strict role separation:
- **`examos_migrator`**: Owns DDL on schemas `public` and `examos_lab`. Granted `CREATE` on the database to create schemas during migrations. Used solely during migrations via `MIGRATION_DATABASE_URL`.
- **`examos_app`**: Least-privilege runtime role. Has `USAGE` on schemas `public` and `examos_lab`, and DML (`SELECT, INSERT, UPDATE, DELETE`) strictly on verified application tables. **Never** granted `CREATE` or `DROP`. Can only `SELECT` from `alembic_version` (no modification allowed).
- **`examos_provisioner`**: Dedicated least-privilege operator role for one-off faculty bootstrapping and account recovery. Direct table permissions on `public.users` are strictly revoked; it is granted execute-only privilege on the hardened `SECURITY DEFINER` stored procedure `public.provision_faculty_account(...)`. **Never** granted direct table DML (`SELECT`, `INSERT`, `UPDATE`, `DELETE`), DDL, or sequence privileges.

### Operator Provisioning Credential Lifecycle & Isolation

- **Ephemeral CLI Usage Only**: `PROVISIONER_DATABASE_URL` must **never** be configured as an environment variable on the long-running Railway backend web service container or stored in any continuous runtime environment. It is an operator-only credential passed ephemerally to the one-off CLI command:
  ```bash
  PROVISIONER_DATABASE_URL=postgresql+psycopg://examos_provisioner:<password>@<host>:<port>/<db> \
  python -m app.commands.bootstrap_faculty --email "admin@university.edu" --name "Initial Admin" --password "<secure-pass>"
  ```
- **Post-Bootstrap Role Lockdown**: Immediately after initial deployment and faculty bootstrapping, disable logins for `examos_provisioner`:
  ```sql
  ALTER ROLE examos_provisioner NOLOGIN;
  ```
- **Operational Account Recovery / Future Provisioning**: When faculty onboarding or account recovery is required by operators:
  1. Re-enable login temporarily:
     ```sql
     ALTER ROLE examos_provisioner LOGIN;
     ```
  2. Rotate the password:
     ```sql
     ALTER ROLE examos_provisioner WITH PASSWORD '<new-random-secret>';
     ```
  3. Execute `python -m app.commands.bootstrap_faculty` in an ephemeral terminal/one-off container session.
  4. Immediately re-lock the role:
     ```sql
     ALTER ROLE examos_provisioner NOLOGIN;
     ```
- **Log Protection**: Ensure operator scripts and CI/CD runners never echo or log connection strings containing passwords. ExamOS log filters redact database URLs matching user credentials, but operator terminals should avoid displaying raw passwords in terminal history.

### One-Time Cloud Database Role Provisioning

Before running migrations on Railway PostgreSQL in Singapore (`sin`), connect to the database as the primary administrative user (e.g. `postgres`) and execute:

```sql
-- See database/provision-cloud-roles.sql
```

Key points for managed cloud environments:
1. `GRANT examos_migrator TO CURRENT_USER;` allows the cloud admin role (e.g. `postgres`) to run `ALTER DEFAULT PRIVILEGES FOR ROLE examos_migrator` and manage schema ownership without requiring superuser privileges.
2. `GRANT CREATE ON DATABASE <db> TO examos_migrator;` ensures the migration runner can execute `CREATE SCHEMA IF NOT EXISTS examos_lab`.
3. Safe repeatable role creation is idempotent and supports password rotation.
4. `examos_test_runner` is deliberately omitted from cloud production databases.

---

## 4. Railway Backend Deployment Walkthrough

### Step 1: Configure Project & Services in Railway (Singapore Region)
1. Create a project in Railway. Set project/service region to **Singapore (`sin`)**.
2. Add a **PostgreSQL 16** database service.
3. Add a **Web Service** pointing to your GitHub repository.
4. In service **Settings**:
   - **Root Directory**: `.` (Repository root — **do NOT set to `backend/`** so `ml/` remains accessible).
   - **Build Command**: `pip install -r backend/requirements.txt && python -m ml.train`
   - **Pre-deploy / Release Command**: 
     ```bash
     python -c "import os, alembic.config; os.chdir('backend'); alembic.config.main(['--raiseerr', '-c', 'alembic.ini', 'upgrade', 'head'])"
     ```
   - **Start Command**: `uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port $PORT --workers 1`
   - **Healthcheck Path**: `/api/v1/health`
   - **Healthcheck Timeout**: `15` seconds
   - **Restart Policy**: `ON_FAILURE` (max 5 retries)
5. In service **Variables**, define all backend variables listed in Section 2.
6. Private Networking: Connect backend to database using Railway's private service domain (e.g., `postgres.railway.internal`) to eliminate cross-datacenter transit latency and egress costs.

### Step 2: Railway Infrastructure as Code (.railway/railway.ts)
The repository defines the backend service specification in `.railway/railway.ts`:
- Preserves single Uvicorn worker.
- Preserves pre-deploy release migration command with `--raiseerr`.
- Preserves Nixpacks build and health check.
- Note: Database volume and credentials are deliberately managed via private environment variable references to prevent accidental recreation or state loss during declarative configuration synchronization.

### Step 3: Single-Worker Memory Footprint on Railway Hobby
- Railway Hobby containers enforce a 512 MB memory ceiling.
- Baseline ExamOS backend working set: ~158 MB (FastAPI, PyTorch CPU DistilBERT/Scikit-learn fallback, Psycopg 3 pool).
- Setting `--workers 1` guarantees stable execution well within the 512 MB boundary.
- For concurrency, uvicorn's asynchronous event loop handles concurrent I/O.
- Lazy finalization ensures attempt expiry correctness without requiring background worker processes.

### Step 4: Seed Taxonomy Topics & Database Lab
Once migrations complete, open the Railway Service Shell:

```bash
# 1. Seed authoritative topics taxonomy (Idempotent)
python -m app.commands.seed_topics

# 2. Seed Database Performance Lab dataset (Medium scale: 1,000 students, 4,000 enrollments)
python -m app.commands.seed_lab_dataset --size medium --seed 42

# 3. Bootstrap initial faculty administrator (Interactive password prompt — never stores password in shell history)
python -m app.commands.bootstrap_faculty --prompt-password
```

---

## 5. Cloudflare Pages Frontend Deployment Walkthrough

### Step 1: Deploy to Cloudflare Pages
1. In Cloudflare Dashboard, navigate to **Workers & Pages -> Create Application -> Pages -> Connect to Git**.
2. Select repository `ExamOS`.
3. Build configuration:
   - **Framework Preset**: `None` or `Vite`
   - **Build Command**: `npm run build`
   - **Build Output Directory**: `dist`
   - **Root Directory**: `frontend`
4. Set Environment Variables:
   - `BACKEND_ORIGIN`: `https://<your-railway-backend>.up.railway.app`
5. Click **Save and Deploy**.

### Step 2: Reverse Proxy Routing Verification
- Vite automatically outputs `dist/_routes.json` copied from `frontend/public/_routes.json`.
- Cloudflare Pages routes `/api` and `/api/*` directly to `frontend/functions/api/[[path]].ts`.
- All static assets and SPA routes are handled directly by Cloudflare edge caching.

---

## 6. Database Migrations, Backups & Disaster Recovery

### Deterministic Migration Command
The verified, non-interactive pre-deploy release command:
```bash
python -c "import os, alembic.config; os.chdir('backend'); alembic.config.main(['--raiseerr', '-c', 'alembic.ini', 'upgrade', 'head'])"
```
This command runs from the repository root, changes directory to `backend`, reads `backend/alembic.ini`, discovers all revisions in `backend/alembic/versions`, uses `MIGRATION_DATABASE_URL`, and aborts deployment immediately if any migration step fails (`--raiseerr`).

### Production Backup & Offsite Archive Strategy
1. **Automated Railway Platform Backups:**
   - Daily snapshots maintained by Railway PostgreSQL service with 7-day retention.
   - Restores raw volume state in the event of platform hardware failure.
2. **Independent Logical Snapshot Before Major Releases:**
   - Must use standard PostgreSQL-native connection string (converting `postgresql+psycopg://` to `postgresql://`):
   ```bash
   PG_URL=$(echo "$MIGRATION_DATABASE_URL" | sed 's/postgresql+psycopg:\/\//postgresql:\/\//')
   pg_dump --format=custom --no-owner --no-privileges -d "$PG_URL" -f "examos_backup_$(date +%Y%m%d_%H%M%S).dump"
   ```

### Disaster Recovery & Safe Restore Verification Runbook

> [!CAUTION]
> **NEVER restore with `--clean` into the live production database as a routine test.**
> Routine restore tests must always target an isolated staging database or temporary container.

#### Restore Verification Checklist (Periodic Staging Test)
1. **Create an isolated restore target:**
   ```bash
   createdb -h <HOST> -p <PORT> -U postgres examos_restore_test
   ```
2. **Execute restore into isolated target:**
   ```bash
   pg_restore --no-owner --no-privileges -d "postgresql://postgres:<PASSWORD>@<HOST>:<PORT>/examos_restore_test" examos_backup_<timestamp>.dump
   ```
3. **Verify Table Schema & Integrity:**
   - Verify all 10 public application tables exist.
   - Verify isolated schema `examos_lab` and all 4 benchmark tables exist.
   - Verify `alembic_version` matches current migration head (`a7b8c9d0e1f2`).
4. **Verify Record Counts:**
   - Confirm `SELECT count(*) FROM users;` matches pre-backup count.
   - Confirm `SELECT count(*) FROM questions;` matches pre-backup count.
   - Confirm `SELECT count(*) FROM examos_lab.lab_students_indexed;` is non-zero.
5. **Run Application Health Check on Staging:**
   - Point a staging instance of ExamOS to `examos_restore_test` and confirm `/api/v1/health` returns status `200` with `database: "connected"`.
6. **Teardown test database:**
   ```bash
   dropdb -h <HOST> -p <PORT> -U postgres examos_restore_test
   ```

#### Emergency Production Cutover Runbook
In the event of total data corruption requiring production restoration:
1. Place the backend into maintenance mode (drain web traffic or route Cloudflare Pages proxy to maintenance page).
2. Archive the corrupted database volume for forensic analysis.
3. Provision a clean, empty production PostgreSQL instance.
4. Execute `database/provision-cloud-roles.sql` as administrator.
5. Restore the verified backup dump:
   ```bash
   pg_restore --no-owner --no-privileges -d "$PG_MIGRATION_URL" verified_backup.dump
   ```
6. Re-apply role permissions from `database/provision-cloud-roles.sql` (Section 6 & 7) to guarantee least-privilege runtime access.
7. Switch Railway `DATABASE_URL` and `MIGRATION_DATABASE_URL` environment variables to the restored instance.
8. Trigger redeployment, verify `/api/v1/health`, and reopen user traffic.

---

## 7. Linux Container Memory Verification Methodology

To verify Railway Hobby (512 MB) memory compliance under actual Linux container conditions:

### 1. Build and Run Isolated Linux Test Container
```bash
# Build standard Linux production container matching Railway's Nixpacks Python 3.11 environment
docker build -t examos-memtest -f backend/Dockerfile .

# Run with 512 MB memory ceiling enabled
docker run -d --name examos-memtest-container \
  --memory=512m --memory-swap=512m \
  -e APP_ENV=production \
  -e APP_SECRET_KEY=1d542fe66669462480df9cec591f0a300161edeb61ab489f8f00886187877172 \
  -e DATABASE_URL=postgresql+psycopg://examos_app:pass@db:5432/examos \
  -e MIGRATION_DATABASE_URL=postgresql+psycopg://examos_migrator:pass@db:5432/examos \
  -e FRONTEND_ORIGIN=https://examos.pages.dev \
  -p 8000:8000 examos-memtest
```

### 2. High-Concurrency Stress Test
Execute concurrent requests simulating active exam autosaves, database lab benchmarks, and ML model inference:
```bash
# Benchmark concurrent health and question advisory endpoints
ab -n 1000 -c 20 http://localhost:8000/api/v1/health
```

### 3. Record Peak RSS and Container Memory Metrics
```bash
# Inspect container memory usage and peak memory
docker stats --no-stream examos-memtest-container

# Inspect Linux process RSS within container
docker exec examos-memtest-container ps -o pid,user,%mem,rss,cmd ax
```
- **Observed Target Peak RSS:** < 220 MB
- **Safety Margin:** > 290 MB head-room below the 512 MB Railway limit.
- **Single Worker Guarantee:** Single Uvicorn worker ensures no multi-process memory multiplication.

---

## 8. Post-Deployment Verification Checklist

1. **Health Check:**
   - Open `https://<your-project>.pages.dev/api/v1/health`.
   - Confirm status `200` with:
     ```json
     {"status": "ok", "app_env": "production", "database": "connected"}
     ```
2. **Direct SPA Routing:**
   - Directly navigate to `https://<your-project>.pages.dev/login` and refresh the page.
   - Confirm the React app loads (SPA fallback functions without 404).
3. **Faculty Login & CSRF:**
   - Log in using your bootstrapped faculty account.
   - In browser DevTools, verify that cookies `examos_access` (HttpOnly, Secure) and `examos_csrf` (Secure) are attached to the `.pages.dev` domain.
4. **Advisory ML Topic Suggestion:**
   - On `/faculty/questions`, click "Suggest Topic" for an MCQ prompt.
   - Confirm proposal renders or provides graceful `LOW_CONFIDENCE` fallback (and not `MODEL_NOT_FOUND`).
5. **OS CPU Scheduler:**
   - On `/faculty/os-scheduler`, run Round Robin simulation; verify Gantt chart timeline.
6. **Database Performance Lab:**
   - On `/faculty/database-lab`, verify Active Scale indicates `Medium (1,000 students)`.
   - Run the Selective Lookup benchmark and inspect real `EXPLAIN (ANALYZE, BUFFERS)` execution plans.
7. **Student Exam Lifecycle:**
   - Publish an exam, self-register a student at `/register`, take the exam, observe autosave, submit, and review the finalized scoring breakdown.
