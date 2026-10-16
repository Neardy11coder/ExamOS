# ExamOS — UI/UX Specification

**Version:** 0.2 · **Status:** Draft — UI/UX Specification

## 1. Experience principles

- Make the exam-taking interface calm and distraction-light.
- Make save status and the deadline visible at all times during an attempt.
- Never communicate that data is saved until the server acknowledges the committed save.
- Use distinct states for loading, empty, error, unauthorized, pending save, saved, conflict and expired.
- Treat accessibility and responsive layouts as practical baseline quality, not visual decoration.
- Use a consistent design system; do not spend milestone time on elaborate animations.

## 2. Navigation and roles

### Student navigation

- Dashboard / Available Exams
- Active Attempt / Resume
- My Results
- My Performance
- Account / Logout

### Faculty/Admin navigation

- Dashboard
- Examinations
- Question Bank
- Results & Analytics
- OS Scheduling Simulator
- Database Performance Lab
- Account / Logout

Routes are protected in the frontend for usability, but every route's underlying API remains server-authorized. Student navigation must never expose faculty functions; direct URL entry must still be rejected by the API.

## 3. Screens and acceptance notes

### 3.1 Login / registration

- Email, password, submit, validation and generic invalid-credentials error.
- Registration creates a student account only.
- Faculty/admin provisioning is not exposed as a role dropdown.
- Show a pending submit indicator and disable duplicate submit while in flight.

### 3.2 Student exam dashboard

Each exam card shows title, duration, total marks and action: `Start`, `Resume`, or `View result` as appropriate. A student with an attempt must not see a second `Start` action for the same exam. Empty state explains that no published exams are currently available.

### 3.3 Pre-exam instructions

Display exam title, instructions, duration, total marks and a clear statement that the timer runs on the server and refresh does not grant extra time. Starting is an explicit action; opening the instructions page must not begin the timer.

### 3.4 Attempt workspace

Recommended desktop layout:

```text
┌────────────────────────────────────────────────────────────────┐
│ Exam title                         Remaining time  Save status  │
├────────────────────────────┬───────────────────────────────────┤
│ Question navigator         │ Question prompt                    │
│ [1] [2] [3] [4]            │                                     │
│ answered / review legend   │ ○ Option A                          │
│                            │ ○ Option B                          │
│                            │ ○ Option C                          │
│                            │ ○ Option D                          │
│                            │                                     │
│                            │ Previous      Next      Mark review │
├────────────────────────────┴───────────────────────────────────┤
│ Answered: n  Unanswered: n  Review: n                  Submit  │
└────────────────────────────────────────────────────────────────┘
```

Core UI states:

- Remaining time from server; refresh/resume recalculates from persisted deadline.
- Question text and options from the frozen exam snapshot; never include correct answer metadata before finalization.
- Navigator clearly distinguishes unanswered, answered and marked-for-review; review can coexist with either answer status.
- Save indicator: `Saving…`, `Saved`, `Save failed — retry`, `Conflict — reloading latest answer`.
- If a save fails, keep the local edit visible as pending, but do not label it saved. Warn before submission if local changes have not been acknowledged.
- Submit confirmation displays answered/unanswered/review counts and warns that submission is final.
- At expiry, disable new answer selection and request authoritative terminal state; do not decide final outcome only in the browser.
- Network loss should show a connection warning without pretending the timer stopped.

### 3.5 Result screen

Show terminal status (`Submitted` or `Expired`), score, total marks, finalization time and per-question correctness. Reveal correct options only after finalization. If no question answers were saved, explain that scoring uses saved answers. Display analytics separately from the raw result and label small topic samples.

### 3.6 Faculty examination list and editor

Exam list shows title, duration, status, question count, and actions consistent with state. Draft editor supports title, instructions, duration, question selection/order, and validation. Publication confirmation explains that publishing freezes a content snapshot; changes require a new draft exam. Unpublish blocks new starts but leaves existing attempts running.

### 3.7 Question bank

Fields: prompt, topic (manual or suggested), ordered options and exactly one correct option. Topic suggestion is clearly labelled as a suggestion and may be ignored, changed or cleared. Model failure returns to manual topic selection with no broken form. Show validation near the field that failed.

### 3.8 Faculty results / analytics

Exam attempt table includes student, state, start time, finalization time and score. Do not expose correct-answer data from non-finalized attempts through this interface. Aggregates use finalized attempts only. Label sample size and avoid claims such as “does not understand” based on one exam.

### 3.9 OS scheduling simulator

Fields for job ID, arrival, burst, and priority where required; algorithm selector; quantum for Round Robin; add/remove job controls; sample workloads; Run action. Validate before submission. Render a Gantt timeline with labeled intervals and explicit idle gaps plus a per-job metrics table and averages. Always show a note that this is an educational simulation of abstract jobs, not kernel scheduling.

### 3.10 Database Performance Lab

Select an approved scenario and dataset size; display scenario explanation; Run action; loading and timeout states. Results include run metadata, actual timing measurements (individual repetitions and summary method), PostgreSQL plan output and caveat that an index may not help. Do not show an editable SQL console. Keep error output sanitized and label any cached historical result by timestamp and parameters.

## 4. Visual system

Use neutral backgrounds, one primary accent, clear contrast, and a restrained color palette. Color is never the only way to communicate a state: pair state colors with text/icons. Use consistent spacing, buttons, cards, form controls, table styles, focus outlines and typography. Tables should wrap/scroll on narrow screens without losing data.

Suggested component set: `AppShell`, `ProtectedRoute`, `FormField`, `InlineError`, `LoadingState`, `EmptyState`, `StatusPill`, `SaveStatus`, `ConfirmDialog`, `QuestionNavigator`, `QuestionCard`, `MetricCard`, `DataTable`, `GanttChart`, `BenchmarkPlanPanel`.

Do not add a full component framework until needed. Keep the theme and layout implementation small.

## 5. Interaction details

- Disable repeated form submission while a request is active, but do not rely on this for backend correctness.
- Show server-confirmed changes only as persisted.
- Use explicit confirmation for irreversible student submission.
- If a revision conflict occurs, explain that another tab or later save changed the answer and reload server state; do not silently overwrite.
- A failed classifier is not a blocking form error; manual topic selection remains available.
- A database lab timeout/error never gets replaced with fake values.
- Preserve useful context after errors; avoid resetting an entire form for one field error.

## 6. Keyboard and accessibility baseline

- All controls usable by keyboard; visible focus styles.
- Use associated labels for inputs.
- Provide accessible names for icon-only buttons.
- Keep timer and save state readable by screen readers without announcing every second aggressively; announce important state changes (e.g. five-minute and one-minute warnings, save failure, expiry).
- Do not rely only on color for question states or benchmark comparisons.
- Respect reduced-motion preferences if animations are added.

## 7. UI data ownership rules

| Data | Authority |
|---|---|
| Current role/user identity | Authenticated `/auth/me` response and server authorization |
| Answer saved state / revision | Backend committed response |
| Remaining time | Server deadline calculation; local countdown is display-only |
| Attempt status and result | Backend/persisted database |
| Correct answer before finalization | Server-only; never in student payload |
| ML topic suggestion | Optional model output; faculty-selected topic is final |
| Benchmark timing/plan | Actual PostgreSQL execution output |
| Scheduler results | Deterministic simulator calculation |

## 8. UI test checklist

- Student and faculty navigation differ by role.
- Directly loading a protected route without authentication returns to login or an unauthorized page.
- A save failure never displays `Saved`.
- Refresh restores saved answers and does not reset the deadline.
- Stale save conflict shows a warning and reloads canonical state.
- Expiry locks the attempt and shows the backend's final outcome.
- Result UI reveals correct options only after finalization.
- ML unavailable state permits manual topic selection.
- Scheduler validates invalid fields and displays idle intervals.
- DB lab displays only approved scenarios and real measured results.

**Document Status:** Draft — UI/UX Specification
