# Instructions for Coding Agents — ExamOS

Before changing code, read:

1. `README.md`
2. `docs/00_PROJECT_BRIEF.md`
3. `docs/01_REQUIREMENTS.md`, including Appendix A
4. `docs/02_SYSTEM_ARCHITECTURE.md`
5. The relevant module document in `docs/03`–`docs/10`

## Non-negotiable project rules

- Build a **modular monolith**: React/TypeScript frontend, FastAPI backend, PostgreSQL database. Do not create microservices.
- Implement only the agreed scope. Do not add proctoring, face recognition, a general chatbot, arbitrary SQL execution, Redis, Celery, Kubernetes, or external AI dependencies.
- Treat PostgreSQL as the authority for durable attempt state, deadline decisions, answer revisions, and finalization.
- A student may access only their own attempts, answers, results, and analytics.
- Never send correct options to the student before the attempt is finalized.
- Acknowledged saves must be durable. Failed or pending saves must never be displayed as saved.
- Enforce answer ownership, selected-option membership, attempt state, and deadline on the server.
- Saves and finalization must have explicit concurrency behavior. Use the approved optimistic revision and transaction strategy.
- Finalization must atomically commit one terminal state and its score. Duplicate requests return the existing outcome.
- Published examinations use immutable assessment snapshots. A question-bank edit must not rewrite a published or historical examination.
- Lazy finalization is the expiry correctness mechanism. An optional periodic sweep may improve promptness but is not required for correctness.
- The OS scheduler is an educational simulation of abstract jobs; it must not read or write examination data.
- The database lab may run only approved, predefined benchmark scenarios against isolated lab data. Never accept arbitrary SQL from a UI request.
- The ML classifier is optional, local, and advisory. Faculty can override it; absence or failure of the model must not block core flows.
- Never fabricate benchmark timings, query plans, evaluation metrics, or performance claims.
- Use migrations for schema changes. Do not rely on ORM auto-creation in production/startup code.
- Do not hard-code secrets. Update `.env.example` when adding configuration, but never place real secrets in it.
- Add or update automated tests for each behavior change, especially state transitions, deadlines, permissions, save ordering, and concurrent finalization.
- Prefer straightforward code over speculative abstractions. Do not refactor unrelated modules while implementing a milestone.

## Implementation discipline

1. Inspect the existing repository before editing.
2. Implement one roadmap task at a time.
3. State the relevant requirement IDs in PR/commit/task notes when practical.
4. Run targeted tests, then the full test suite for cross-cutting changes.
5. Report exactly which tests were run and their actual result. Do not say tests pass unless they were executed successfully.
6. If a requirement is ambiguous or conflicts with another document, stop the affected work and identify the conflict instead of making an undocumented choice.
7. Keep `docs/10_SETUP_AND_HANDOVER.md` current with completed milestones, commands, known defects, and next tasks.
