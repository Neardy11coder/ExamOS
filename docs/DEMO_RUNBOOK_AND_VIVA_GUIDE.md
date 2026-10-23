# ExamOS — Demonstration Runbook and Viva Preparation Guide

**Version:** 1.0 · **Status:** Final Live Demonstration Runbook & Viva Preparation
**Audience:** B.Tech Project Evaluators, Faculty Viva Panel, Presenters
**Target Duration:** 8–12 Minutes

---

## 1. Pre-Demo Setup and Verification Checklist

Before presenting, complete and verify these environmental prerequisites:

### A. Environment & Infrastructure Check
1. **Docker & PostgreSQL**:
   ```powershell
   # Check container status (PostgreSQL 16 Alpine on 127.0.0.1:5433)
   docker compose -p examos-dev-20261016 ps
   ```
   *Expected:* `examos-dev-20261016-db-1` is `Up` and `(healthy)`.
   *If stopped:* Run `docker compose -p examos-dev-20261016 up -d`.

2. **Database Migrations & Seed Prerequisites**:
   ```powershell
   cd C:\Projects\ExamOS\backend

   # Apply Alembic schema migrations
   .venv\Scripts\python.exe -m alembic upgrade head

   # Seed the 8 fixed taxonomy topics
   .venv\Scripts\python.exe -m app.commands.seed_topics

   # Seed the isolated Database Performance Lab dataset (medium scale: 1,000 students, ~4,000 enrollments)
   .venv\Scripts\python.exe -m app.commands.seed_lab_dataset --size medium --seed 42

   # Bootstrap/verify faculty admin account (idempotent)
   .venv\Scripts\python.exe -m app.commands.bootstrap_faculty
   ```

3. **Machine Learning Model Artifact**:
   - Check if `ml/artifacts/topic_classifier.joblib` exists.
   - If missing (e.g., after clean clone):
     ```powershell
     cd C:\Projects\ExamOS
     & backend\.venv\Scripts\python.exe -m ml.train
     ```

### B. Service Launch & Health Verification

1. **Start Backend Server** (Terminal 1):
   ```powershell
   cd C:\Projects\ExamOS\backend
   .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
   ```
   - Health check: [http://127.0.0.1:8000/api/v1/health](http://127.0.0.1:8000/api/v1/health) returns `{"status":"ok","app_env":"development","database":"connected"}`.

2. **Start Frontend Dev Server** (Terminal 2):
   ```powershell
   cd C:\Projects\ExamOS\frontend
   npm run dev
   ```
   - App URL: [http://localhost:5173](http://localhost:5173).

---

## 2. Authentication and Demo Accounts

ExamOS enforces strict role boundaries:
- **Faculty Admin Account**:
  - Email: `faculty@examos.local` (configured in `.env` / bootstrapped via `bootstrap_faculty`)
  - Password: as configured in local `.env` (`SEED_FACULTY_PASSWORD`, default local dev credentials)
  - Role: `FACULTY_ADMIN` (access to question bank, exam authoring, OS simulator, Database Lab).
- **Student Account**:
  - Public registration: Navigate to `/register` in browser.
  - Recommended Demo Student: Email `student@example.test`, Display Name: `Student Demo`, Password: `StudentDemo123!`.
  - Role: `STUDENT` (access strictly restricted to available exams, active attempt workspace, own results).

---

## 3. Timed Step-by-Step Demonstration Script (8–12 Minutes)

| Time | Stage | UI Route | Action & Presenter Walkthrough | Expected Visible Result | Spoken Script / Core Concept |
|---|---|---|---|---|---|
| **0:00–1:00** | **1. Architecture & Role Isolation** | `/login`<br>`/register` | Open [http://localhost:5173](http://localhost:5173). Show `/login`. Show student self-registration at `/register`. Log in as `faculty@examos.local`. | Redirection to `/dashboard`. Faculty dashboard displays Question Bank, Exams, OS Simulator, and Database Lab cards. | *"ExamOS is an intelligent, high-reliability examination platform. Notice strict role-based isolation: students register publicly but cannot escalate privileges; faculty accounts are provisioned via trusted CLI. Authentication uses HttpOnly JWT cookies and double-submit CSRF headers."* |
| **1:00–2:30** | **2. Question Bank & ML Topic Classifier** | `/faculty/questions` | Click **Question Bank** or go to `/faculty/questions`. Click **Create Question** modal.<br><br>**Test 1 (Graceful Fallback):** Enter prompt: `Which concurrency control mechanism avoids deadlocks by aborting older or younger transactions using timestamps?`. Add 4 options (e.g. Wait-Die, Wound-Wait, 2PL, Lockout). Click **Suggest Topic**.<br><br>**Test 2 (Ambiguous Input):** Change prompt to ambiguous text: `Something about stuff`. Click **Suggest Topic**. Show the same graceful fallback message. | For both tests with the default `ML_CONFIDENCE_THRESHOLD=0.55`: the classifier’s max class probability is below threshold (~0.38), so the API returns `{"available": false, "reason": "LOW_CONFIDENCE"}`. The UI displays an informational alert: *"No confident topic suggestion — the classifier could not determine a topic with sufficient certainty. Please select a topic manually."* Dismiss it; manual topic selector remains fully functional.<br><br>**Optional high-confidence demo:** To show a successful suggestion, temporarily set `ML_CONFIDENCE_THRESHOLD=0.30` in `.env` and restart the backend. The suggestion panel will then appear with a topic badge. Reset threshold afterward. | *"The ML classifier is completely advisory and runs locally using TF-IDF and Logistic Regression on an 8-topic taxonomy. It never auto-overrides faculty choices. If confidence is below the configurable threshold (default 55%) or the model is unavailable, the UI falls back gracefully to manual selection without blocking question creation."* |
| **2:30–4:00** | **3. Exam Authoring & Immutable Snapshots** | `/faculty/exams`<br>`/faculty/exams/:id` | Navigate to **Exams**. Click **Create Exam**. Enter title: `Operating Systems & DBMS Evaluation`, Duration: `10` minutes. Attach 2–3 questions from the bank. Click **Publish Exam**. | Status changes from `DRAFT` to `PUBLISHED` (green badge). Questions can no longer be added, deleted, or reordered. | *"Publishing an exam is an atomic database transaction that freezes immutable snapshots of question text, options, marks, and correct answers. If a question is edited or deleted in the question bank tomorrow, existing and historical examinations remain completely unchanged."* |
| **4:00–6:00** | **4. Student Workflow: Autosave, Recovery & Integrity** | `/exams/available`<br>`/attempts/:id` | Log out as faculty. Log in as student (`student@example.test`). Navigate to **Available Exams**. Click **Start Exam** on the published exam.<br><br>1. Select an option on Question 1. Point to the green save indicator (**Saved**).<br>2. Mark Question 2 for review.<br>3. **Simulate Disconnection/Refresh:** Hit browser Refresh (`F5`).<br>4. Open DevTools Network tab: inspect `/attempts/{id}`. | After refresh, the attempt immediately recovers: the previously selected option and review flag are restored. The server-authoritative countdown continues from the persisted deadline without granting extra time. Network tab confirms `is_correct` is absent from all options. | *"ExamOS treats PostgreSQL as the single authority for state and time. Notice that browser refresh does not grant extra time: the deadline was persisted at start time. Furthermore, look at the network payload: answer keys and `is_correct` flags are completely stripped from student attempt payloads to prevent client-side inspection."* |
| **6:00–7:30** | **5. Submission, Lazy Expiry & Results** | `/attempts/:id`<br>`/attempts/:id/result` | On the attempt workspace, click **Submit Exam**. Confirm in the dialog. | Redirects to `/attempts/:id/result`. Shows final score, percentage, submission timestamp, and now reveals correct options with detailed breakdown. | *"Finalization commits terminal state and score in one atomic transaction. It is strictly idempotent: duplicate submit requests return the exact same persisted score. If a student disconnects and the deadline passes, lazy finalization automatically commits EXPIRED with computed score on their next read without requiring background cron daemons."* |
| **7:30–9:30** | **6. OS CPU Scheduling Simulator** | `/faculty/os-scheduler` | Log out. Log back in as `faculty@examos.local`. Navigate to **OS Simulator**. Enter benchmark job workload:<br>- **P1**: Arrival `0`, Burst `5`, Priority `2`<br>- **P2**: Arrival `1`, Burst `3`, Priority `1`<br>- **P3**: Arrival `2`, Burst `8`, Priority `3`<br>- **P4**: Arrival `3`, Burst `6`, Priority `2`<br><br>Test **FCFS**, **Round Robin (Quantum = 2)**, and **Priority (Non-Preemptive)**. | Visual Gantt chart renders timeline segments with CPU utilization %, Average Waiting Time, Turnaround Time, and Response Time. | *"This simulator provides interactive, pure educational simulations of classic operating systems scheduling algorithms. Notice deterministic tie-breaking: lower priority number represents higher priority; Round Robin strictly enforces quantum boundaries. The engine is pure Python and isolated from exam tables."* |
| **9:30–11:00** | **7. Database Performance Lab** | `/faculty/database-lab` | Navigate to **Database Lab**. Show Active Dataset scale (`medium`: 1,000 students, ~4,000 enrollments).<br><br>Select scenario: **Selective Point Lookup (Single Row)**. Dataset scale: `medium`. Repetitions: `3`. Click **Run Benchmark**. | Split comparison visualizer appears: compares `NO_INDEX` (Sequential Scan) against `INDEXED` (B-Tree Index Scan). Displays real execution plan JSON, buffer hits, and speedup ratio. Actual timings depend on host hardware and PostgreSQL cache state. | *"The Database Lab runs only server-approved read-only benchmarks against the isolated `examos_lab` schema. Notice we never accept arbitrary user SQL. The execution times and EXPLAIN ANALYZE plans are 100% genuine from PostgreSQL, illustrating real indexing trade-offs."* |
| **11:00–12:00** | **8. Conclusion & Architecture Summary** | Dashboard / Docs | Return to Dashboard. Summarize modular monolith structure, test suite (271 tests), and reliability guarantees. | Overview of full system health and completed milestones. | *"To summarize: ExamOS demonstrates operating systems scheduling and checkpoint recovery principles, relational database ACID transactions, optimistic concurrency, and practical machine learning advisory integration."* |

---

## 4. Comprehensive Viva Preparation (Questions & Answers)

### A. System Architecture & Engineering
- **Q: Why a modular monolith instead of microservices?**
  - *Answer:* Microservices introduce network latency, distributed transaction complexity (2PC/Sagas), and network partition failure modes. For examination platforms where strict transactional atomicity (e.g., publishing exams and scoring attempts) is required, a modular monolith using FastAPI, PostgreSQL, and React provides ACID guarantees within a single transactional boundary while maintaining clean code modularity.
- **Q: How is authentication and session security implemented?**
  - *Answer:* Stateless JWT access tokens are issued on login and stored in an `HttpOnly`, `SameSite=Lax` cookie (`examos_access`) with configurable `Secure` flags. To prevent Cross-Site Request Forgery (CSRF), a cryptographic random hex token is set in a non-HttpOnly cookie (`examos_csrf`) and must be transmitted in the `X-CSRF-Token` header for all state-changing requests (`POST`, `PUT`, `PATCH`, `DELETE`). The backend verifies this using constant-time `hmac.compare_digest`.

### B. Concurrency, Timing & Database Integrity
- **Q: How does ExamOS prevent race conditions and lost updates on answer saves?**
  - *Answer:* In `save_answer`, we acquire an exclusive row-level lock on the attempt (`SELECT ... FOR UPDATE`), verify ownership, and check the server-authoritative time (`clock_timestamp() < deadline_at`). We then lock the specific `attempt_answers` row and check the optimistic revision counter (`ans.revision == expected_revision`). If a multi-tab concurrent edit occurred, it immediately rejects the stale save with `409 ANSWER_REVISION_CONFLICT` and returns the canonical state.
- **Q: How does lazy finalization work? Why no Redis/Celery?**
  - *Answer:* In accordance with the non-negotiable project brief, ExamOS avoids external queuing daemons. Finalization is a triggered operation. When any student or faculty operation reads or updates an attempt (`GET /attempts/{id}`, save, submit, or exam attempt lists), the system checks `now >= deadline_at`. If overdue, it atomically locks the attempt, computes the score, sets the status to `EXPIRED`, and commits. This guarantees that overdue attempts are never shown as active or editable.
- **Q: What is the purpose of published examination snapshots?**
  - *Answer:* In normal normalized databases, updating a question in the bank would alter historical exams. ExamOS implements snapshot isolation: when faculty publishes an exam, the draft questions and options are copied into immutable snapshot tables (`exam_questions` and `exam_question_options`). Any subsequent edits, updates, or soft-archives to the question bank affect future drafts only.

### C. Operating Systems Concepts
- **Q: Is an exam attempt an OS process?**
  - *Answer:* No. An exam attempt is an application-level entity stored in PostgreSQL. We use OS concepts like process states (`IN_PROGRESS`, `SUBMITTED`, `EXPIRED`), checkpoint/recovery, and deadline scheduling as architectural design patterns. The OS CPU scheduling simulator is a separate, educational module simulating abstract jobs.
- **Q: What tie-breaking rules are implemented in CPU scheduling?**
  - *Answer:* For FCFS and SJF, ties in arrival or burst times break deterministically by initial job input order. For Round Robin, newly arrived jobs are enqueued before jobs preempted at the exact same quantum boundary. For Priority scheduling, smaller numeric values denote higher priority, with ties broken by arrival time and input order.

### D. Database Indexing & Benchmark Lab
- **Q: Does adding an index always make queries faster?**
  - *Answer:* No. As demonstrated in our Database Lab, if a table is very small (fitting inside a single 8KB disk page) or if a query has low selectivity (returning a large percentage of table rows), a Sequential Scan is cheaper than an Index Scan because it avoids reading both index tree blocks and table heap blocks.
- **Q: How is the Database Performance Lab protected against SQL injection?**
  - *Answer:* The lab never accepts arbitrary SQL fragments, table names, or raw queries from the UI. Only enumerated scenario IDs (e.g. `selective_lookup`, `join_students_enrollments`) are accepted. The backend maps these to predefined, parameterized SQL queries that run exclusively against the isolated `examos_lab` schema.

### E. Machine Learning & Advisory Classification
- **Q: Why use TF-IDF and Logistic Regression instead of an LLM or deep learning?**
  - *Answer:* The topic classifier is designed as a local, lightweight, advisory service requiring zero external cloud dependencies or API keys. TF-IDF with sublinear term-frequency scaling and multinomial Logistic Regression evaluates in under 5 milliseconds, trains deterministically, and outputs calibrated probabilities for threshold verification.
- **Q: How does ExamOS handle low-confidence predictions or missing models?**
  - *Answer:* Predictions are emitted only if `max(proba) >= ML_CONFIDENCE_THRESHOLD` (default 0.55). If confidence is below threshold or the `.joblib` model artifact is missing, the service returns `available: false` with reason codes `LOW_CONFIDENCE` or `MODEL_NOT_FOUND`. The question authoring UI renders an informational message and lets faculty select the topic manually without disruption.

---

## 5. Verification Commands Summary

Commands verified during M6-DEMO-PREP:
1. `docker compose -p examos-dev-20261016 ps` -> Container healthy on port 5433.
2. Backend full test suite: `pytest -q` -> 271 passed, 0 failed.
3. Frontend production build: `npm run build` -> Clean build in 1.63s.
4. Git whitespace check: `git diff --check` -> Clean.
5. ML artifact check: `ml/artifacts/topic_classifier.joblib` present and verified.
6. CLI Seed commands: `seed_topics`, `seed_lab_dataset`, `bootstrap_faculty` importable and verified.
