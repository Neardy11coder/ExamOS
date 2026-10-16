# ExamOS — API Contract

**Version:** 0.2 · **Status:** Draft — API Contract  
**Base path:** `/api/v1`  
**Transport:** JSON over HTTP; authenticated browser requests use cookies and CSRF protection

This is a proposed contract for the first implementation. Exact response schemas should be represented by Pydantic models and kept synchronized with OpenAPI. Do not return ORM objects directly.

## 1. Common conventions

- JSON request/response bodies use `application/json` unless explicitly stated.
- IDs are opaque UUID strings.
- Timestamps are ISO 8601 UTC instants.
- Marks are non-negative numeric values; the server defines allowed precision.
- All non-login routes require authentication except public student registration and health checks.
- Every protected operation also enforces role and resource ownership on the server.
- Use configured request size and input length limits.
- Do not return passwords, password hashes, token signing details, internal stack traces or arbitrary SQL.

### 1.1 Authentication

JWT is stored in an HttpOnly cookie. State-changing requests must include the CSRF token/header required by the auth middleware. The frontend sends credentials for API requests. CORS permits only the configured frontend origin.

### 1.2 Error envelope

Use a consistent envelope:

```json
{
  "error": {
    "code": "ATTEMPT_EXPIRED",
    "message": "This attempt has expired and can no longer be changed.",
    "details": {"attempt_status": "EXPIRED"},
    "request_id": "optional-correlation-id"
  }
}
```

`details` is optional and must not leak another user's data or internal diagnostics.

| HTTP status | Use |
|---|---|
| `400` | Malformed request / validation failure where field feedback is useful. |
| `401` | Missing, invalid or expired authentication. |
| `403` | Authenticated but role/action is not allowed. A non-owned resource may use `404` to avoid disclosure. |
| `404` | Resource unavailable or intentionally concealed because it belongs to another user. |
| `409` | State conflict, stale answer revision, duplicate/immutable operation conflict. |
| `422` | Structurally valid JSON but invalid business input, according to one consistent project convention. |
| `429` | Rate/size limit when implemented. |
| `500` | Generic server error, with internal details only in server logs. |
| `503` | Temporary dependency unavailability, such as database unavailable. |

Pick one validation convention (`400` or `422`) and use it consistently. FastAPI defaults to `422`; retaining that behavior is acceptable.

## 2. Authentication and identity

### `POST /auth/register`

**Public; creates students only.**

Request:

```json
{"email":"student@example.test","display_name":"Demo Student","password":"user-supplied-password"}
```

Success `201`:

```json
{"id":"uuid","email":"student@example.test","display_name":"Demo Student","role":"STUDENT"}
```

Never accept `role` from this request. Reject duplicate normalized email addresses without disclosing sensitive account details.

### `POST /auth/login`

Request: `{"email":"...","password":"..."}`. On success, set the HttpOnly auth cookie and return the public user profile plus a CSRF token or CSRF bootstrap value. Invalid credentials return a generic `401`.

### `POST /auth/logout`

Authenticated and CSRF-protected. Clear the auth cookie and return `204`. Server-side JWT revocation is not required in v1; the access token remains bounded by its expiry.

### `GET /auth/me`

Returns `{ "id", "email", "display_name", "role" }` for the authenticated user.

### `GET /health`

Returns service status only. Do not expose secrets, connection strings or detailed infrastructure topology. A separate readiness check may validate database connectivity for local debugging.

## 3. Faculty examination and question management

All endpoints in this section require `FACULTY_ADMIN`.

### `GET /exams`

Returns faculty's complete exam list with title, duration, status, question count, and timestamps. The prototype has one faculty role with global scope.

### `POST /exams`

Creates a `DRAFT` exam. Example request:

```json
{"title":"OS and DBMS Midterm","instructions":"Choose one option per question.","duration_minutes":30}
```

Returns the created exam ID and draft metadata. Reject blank title, invalid duration or invalid configured maximum.

### `GET /exams/{exam_id}`

Returns exam metadata. For a draft, faculty may also receive editable question associations. For a published/unpublished frozen exam, include the immutable assessment summary.

### `PATCH /exams/{exam_id}`

Updates title/instructions/duration only while `DRAFT`. Reject after first publication, including after subsequent unpublishing. Create a new draft exam to revise assessment content.

### `POST /exams/{exam_id}/publish`

Validates the draft; creates the frozen question and option snapshots and marks it published in one transaction. Must fail atomically if there are no questions, an invalid option count, no/ multiple correct options, invalid marks or invalid duration.

### `POST /exams/{exam_id}/unpublish`

Blocks new attempt starts. Existing attempts continue with their persisted deadline and frozen content.

### Question bank endpoints

- `GET /questions?topic_id=...&search=...` — list/filter questions.
- `POST /questions` — create question and 2+ non-empty options, with exactly one correct option; topic may be omitted or manually selected.
- `GET /questions/{question_id}` — faculty authoring view, includes correct-option designation.
- `PATCH /questions/{question_id}` — edit bank content; affects future snapshots only.
- `POST /questions/{question_id}/archive` — soft archive; do not hard-delete data needed for provenance/history.

Proposed create request:

```json
{
  "prompt":"Which scheduling algorithm uses a time quantum?",
  "topic_id":"uuid-or-null",
  "options":[
    {"text":"Round Robin","is_correct":true},
    {"text":"FCFS","is_correct":false},
    {"text":"SSTF","is_correct":false},
    {"text":"FIFO page replacement","is_correct":false}
  ]
}
```

The question bank write endpoint may request a topic suggestion separately; classifier failure must not block creation.

## 4. Student exam catalogue and attempt API

### `GET /exams/available`

**Student.** Lists published exams. Returns title, instructions summary if useful, duration, total marks, and whether the student already has an attempt. It never returns correct options.

### `POST /exams/{exam_id}/attempts/start`

**Student.** Starts an exam or returns the student's already-existing attempt due to idempotent start behavior. The server verifies publication and one-attempt policy; it creates `IN_PROGRESS`, `started_at`, `deadline_at`, and answer rows atomically.

Success example:

```json
{
  "attempt_id":"uuid",
  "status":"IN_PROGRESS",
  "started_at":"2026-10-10T10:00:00Z",
  "deadline_at":"2026-10-10T10:30:00Z",
  "remaining_seconds":1789,
  "exam":{"id":"uuid","title":"OS and DBMS Midterm","total_marks":20},
  "questions":[
    {
      "exam_question_id":"uuid",
      "prompt":"Which scheduling algorithm uses a time quantum?",
      "marks":2,
      "display_order":1,
      "options":[{"id":"uuid","text":"Round Robin","display_order":1},{"id":"uuid","text":"FCFS","display_order":2}],
      "answer":{"selected_option_id":null,"marked_for_review":false,"revision":0}
    }
  ]
}
```

**Confidentiality:** student question option payloads must omit `is_correct`, correct option ID, answer key, solution field and any derived correct-answer flag until finalized.

### `GET /attempts/{attempt_id}`

**Owner student.** Returns current attempt status, remaining time, saved responses, review flags and revisions. Before returning, run lazy expiry. If overdue, return the terminal outcome/result rather than an active attempt.

### `PUT /attempts/{attempt_id}/answers/{exam_question_id}`

**Owner student; active and before deadline only.** Request:

```json
{
  "selected_option_id":"uuid-or-null",
  "marked_for_review":false,
  "expected_revision":3,
  "mutation_id":"uuid"
}
```

Successful response returns the canonical selected option, review flag, new revision and `saved_at`. The server acknowledges only after the DB transaction commits.

On revision mismatch, return `409 ANSWER_REVISION_CONFLICT` with the canonical current answer state. The client must reload/resolve rather than silently overwrite. If the exact `mutation_id` has already been applied, the request is idempotent and can return the existing canonical state.

If the deadline has passed, finalize as `EXPIRED` if not already finalized, reject the mutation, and return a consistent expiration response.

### `POST /attempts/{attempt_id}/submit`

**Owner student.** The client may include a `submission_request_id`; no score/status/deadline supplied by the client is trusted. The server locks the attempt and uses DB time. Before the deadline, atomically finalize as `SUBMITTED`. At or after the deadline, finalize as `EXPIRED`. If already terminal, return the same outcome and score.

Example response:

```json
{"attempt_id":"uuid","status":"SUBMITTED","score":16,"total_marks":20,"finalized_at":"2026-10-10T10:27:00Z"}
```

### `GET /attempts/{attempt_id}/result`

**Owner student or faculty with appropriate scope.** Runs lazy expiry first where relevant. Only finalized attempts have a result. After finalization, the student may receive question-level correctness and correct options. Faculty can access finalized result details and their examination's attempt list.

## 5. Faculty results and analytics

- `GET /exams/{exam_id}/attempts` — faculty attempt list. Expire overdue attempts in scope before returning statuses/scores; never show overdue attempts as still active.
- `GET /exams/{exam_id}/analytics` — faculty exam-level metrics computed from finalized attempts only.
- `GET /attempts/{attempt_id}/result` — includes question-level result detail for authorized faculty/student.
- `GET /me/analytics` — student-only analytics derived from the student's own finalized attempts.

Do not expose a student list/score to a different student. Use the immutable exam snapshot topic label for topic-level analytics.

## 6. OS scheduling simulator

### `POST /labs/os-scheduler/run`

**Faculty/admin only.** This endpoint performs a pure simulation; it does not read or modify examination tables.

Request example:

```json
{
  "algorithm":"ROUND_ROBIN",
  "quantum":2,
  "jobs":[
    {"id":"P1","arrival_time":0,"burst_time":5,"priority":2},
    {"id":"P2","arrival_time":1,"burst_time":3,"priority":1}
  ]
}
```

Return per-job start/completion/waiting/turnaround/response times, CPU utilization, averages, and a chronological list of execution/idle intervals for Gantt rendering. For FCFS and Round Robin, priority may be ignored. Validate configured job count, unique IDs, integer/nonnegative arrival time, positive burst time, and positive integer quantum. Priority Scheduling is non-preemptive; smaller number means higher priority. Label the output as a simulation of abstract jobs.

## 7. Database Performance Lab

### `GET /labs/db/benchmarks`

**Faculty/admin only.** Returns allowed scenario IDs, descriptions, allowed dataset sizes and index variants. Does not return arbitrary executable SQL.

### `POST /labs/db/benchmarks/run`

Request example:

```json
{"scenario_id":"selective_lookup","dataset_size":"medium","seed":42,"repetitions":5}
```

Only predefined scenario codes and enumerated dataset-size values are accepted. The backend resolves fixed query definitions and lab table identifiers. User input may influence only validated parameters. Run approved read-only queries against isolated lab data; return actual timings, repetition count and summary method, PostgreSQL version, scenario parameters, and actual plan output. On failure/timeout, return a sanitized error rather than substitute timings. The service never executes raw user SQL.

### `GET /labs/db/benchmarks/runs/{run_id}`

Returns a prior run and its metadata, clearly labelled with run time and parameters. Restrict to faculty/admin.

## 8. ML topic suggestion

### `POST /ml/topic-suggestions`

**Faculty/admin only.** Request:

```json
{"prompt":"Which property makes a transaction all-or-nothing?","options":["Atomicity","Durability","Isolation","Normalization"]}
```

Possible response:

```json
{"available":true,"suggestion":{"topic_code":"DB_TRANSACTIONS","topic_name":"Transactions and Concurrency","confidence":0.67,"threshold":0.55}}
```

If model artifact is missing or confidence is below threshold, return a successful no-suggestion result, for example `{"available":false,"reason":"LOW_CONFIDENCE"}`. This is not a fatal API error. Do not return training records, raw artifact paths, or an untrusted prediction as a confirmed topic. The faculty's manually submitted topic is stored.

## 9. Idempotency, concurrency and time contract

- Start uses the unique `(student_id, exam_id)` constraint to avoid duplicate attempts.
- Answer updates use `expected_revision` plus `mutation_id` and always lock attempt before answer.
- Submit/expiry finalization locks attempt and obtains `clock_timestamp()` after lock acquisition.
- A request is timely only if DB decision time is strictly earlier than `deadline_at`.
- Terminal result fields are immutable.
- Lazy expiry is performed before returning an overdue attempt as active or using it in aggregates.
- Acknowledgement means transaction committed. No endpoint may report success while DB changes are pending/uncommitted.

## 10. API implementation checklist

- [ ] Pydantic request/response model for every endpoint.
- [ ] Server-side role checks on every protected route.
- [ ] Owner check on every student attempt/result route.
- [ ] Safe response DTOs prevent answer key leakage.
- [ ] Consistent validation/error envelope.
- [ ] CSRF/CORS configuration tested with the actual frontend origin.
- [ ] Database transactions wrap publish, start, save and finalization as specified.
- [ ] OpenAPI docs match this file after implementation.

**Document Status:** Draft — API Contract
