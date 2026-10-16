# ExamOS — Documentation Pack

**Project:** ExamOS — Intelligent Examination & Reliability Platform  
**Audience:** Solo B.Tech CSE (AI/ML) developer, coding agent, and PBL evaluator  
**Status:** Architecture and requirements are a design baseline; implementation is not yet claimed.

## How to use this pack

1. Read `docs/00_PROJECT_BRIEF.md` for the project vision and scope.
2. Read `docs/01_REQUIREMENTS.md`. Its original specification is preserved, and **Appendix A at the end resolves decisions that were previously open**. Appendix A is normative wherever it supersedes an earlier interim statement.
3. Read `docs/02_SYSTEM_ARCHITECTURE.md` before writing application code.
4. Use `docs/03_DATABASE_DESIGN.md` and `docs/04_API_CONTRACT.md` as implementation contracts.
5. Use `docs/05_UI_UX_SPECIFICATION.md`, `docs/06_OS_SCHEDULING_SIMULATOR.md`, and `docs/07_AI_ML_DESIGN.md` for their respective modules.
6. Follow `docs/08_TESTING_STRATEGY.md` and `docs/09_IMPLEMENTATION_ROADMAP.md` to build incrementally.
7. Follow `docs/10_SETUP_AND_HANDOVER.md` and root `AGENTS.md` when working with Codex or another coding agent.
8. Use `docs/11_DEMO_AND_VIVA.md` to prepare the live demonstration and viva; update it to reflect only verified features.
9. Use `docs/12_CODEX_BUILD_PROMPTS.md` to implement one bounded milestone at a time.

## Normative precedence

Where documents appear inconsistent, use this order:

1. `docs/01_REQUIREMENTS.md` including its final **Appendix A — Resolved Decisions and Normative Clarifications**.
2. `docs/02_SYSTEM_ARCHITECTURE.md` for the selected architecture and transaction/state behavior, provided it does not contradict Appendix A.
3. The module-specific contracts in `docs/03` through `docs/08`.
4. The high-level project brief.

If implementation reveals a genuine conflict, do not silently invent behavior. Update the relevant requirement and architecture decision together, then update tests.

## Recommended repository layout

```text
exam-os/
├── AGENTS.md
├── README.md
├── docs/                       # This documentation pack
├── frontend/                   # React + TypeScript + Tailwind
├── backend/                    # FastAPI application
├── database/                   # seed data and benchmark definitions
├── ml/                         # topic dataset, training, evaluation, artifact
├── docker-compose.yml          # optional reproducible local services
└── .env.example
```

See `docs/10_SETUP_AND_HANDOVER.md` for the proposed detailed layout.

## Important status note

These files define the intended design. They do **not** claim that the system has already been implemented, deployed, tested, trained, benchmarked, or achieved any performance/accuracy target. All such claims must be based on actual run results.
