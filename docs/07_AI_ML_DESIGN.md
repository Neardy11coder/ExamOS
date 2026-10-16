# ExamOS — AI/ML Design

**Version:** 0.2 · **Status:** Draft — ML and Analytics Design

## 1. Scope

The initial ML feature suggests a topic for a faculty-authored MCQ. The prediction is advisory; the faculty-confirmed topic is stored. Student performance analytics are deterministic statistics and are not described as machine learning.

No LLM, external AI API, online data collection, or personal student-data training is required. If the classifier is absent or fails, the application works with manual topic selection.

## 2. Topic taxonomy

Use eight fixed labels:

| Code | Topic |
|---|---|
| `OS_PROCESS` | Process Management |
| `OS_SCHEDULING` | CPU Scheduling |
| `OS_SYNC` | Synchronization and Deadlocks |
| `OS_MEMORY_FILES` | Memory and File Systems |
| `DB_NORMALIZATION` | Relational Modeling and Normalization |
| `DB_SQL_JOINS` | SQL Queries and Joins |
| `DB_TRANSACTIONS` | Transactions and Concurrency |
| `DB_INDEXING` | Indexing and Query Optimization |

Store stable codes separately from display labels. If taxonomy changes after training, retrain/re-evaluate and update the topic seed in a migration or seed routine. Do not let model output create new taxonomy labels.

## 3. Dataset

Proposed file: `ml/data/question_topics.csv`, with columns `text`, `topic_code`, and optional source/author note. Use original or permission-cleared question text; do not collect personal data. Do not include answer keys unless there is a documented need; the classifier can use prompt and optional options text.

Target at least 20 labelled examples per topic (160 total) as a starting dataset. This is a modest development target, not a claim that the dataset is sufficient for production. Prefer varied wording and clear class boundaries. Check duplicates and near-duplicates before splitting so near-identical questions do not leak between train and test sets.

Split once using a fixed random seed and stratification, target 80% train / 20% test. Store split logic in code rather than committing a separate test set that accidentally gets mixed into training. Record row counts per class and the split seed in the evaluation report.

## 4. Baseline model

Pipeline:

1. Normalize whitespace and harmless formatting; do not aggressively stem or remove meaningful technical terms.
2. Convert text to TF-IDF features using scikit-learn.
3. Train a Logistic Regression multiclass classifier with fixed `random_state` and recorded settings.
4. Evaluate once on the held-out test split.
5. Save a versioned model artifact and a metadata file containing taxonomy version, training row count, split seed, library versions, training timestamp and metrics.

Train with a reproducible command (for example `python -m ml.train`) and evaluate separately (for example `python -m ml.evaluate`). Do not retrain on every app startup or per user request.

## 5. Evaluation and enablement

The report must contain:

- Dataset total and per-topic counts.
- Train/test split counts and seed.
- Accuracy.
- Per-topic precision, recall and F1.
- Macro F1 and confusion matrix.
- Library versions and pipeline parameters.
- Limitations, including class overlap and small-data uncertainty.

Do not fabricate values. If no trained artifact/evaluation report exists yet, explicitly say “not evaluated” rather than insert a placeholder score. Model output may be demonstrated only after the model can load and has passed a smoke test. Poor evaluation is not a reason to fake a result: show it as a prototype limitation and retain manual tagging.

Use a configurable confidence threshold, initial default `0.55`. This threshold is a heuristic for whether to display a suggestion and is not a guarantee that predictions are correct. If maximum predicted probability is below threshold, return no suggestion. If classes required by the taxonomy are absent from training, or model loading/inference fails, return a graceful unavailable/no-suggestion response.

## 6. Service contract

The service takes prompt text and optionally option text, returns either:

```json
{"available": true, "topic_code": "DB_TRANSACTIONS", "confidence": 0.67, "threshold": 0.55}
```

or:

```json
{"available": false, "reason": "LOW_CONFIDENCE"}
```

Possible reasons include `MODEL_NOT_FOUND`, `MODEL_LOAD_FAILED`, `LOW_CONFIDENCE`, or `INFERENCE_FAILED`. Do not return stack traces or local artifact paths to the browser. Log operational details server-side without logging credentials or private assessment payloads unnecessarily.

Faculty can accept, change or clear a suggestion. A later question save persists the faculty-selected topic, not the classifier's raw output. No suggestion is a valid outcome and does not block question creation.

## 7. Deterministic performance analytics

Analytics consume finalized attempt answers and frozen topic labels. They may calculate:

- Score and total marks.
- Overall question accuracy.
- Correct/incorrect/unanswered counts.
- Topic accuracy and sample count.
- Revision suggestions derived from actual missed/unanswered topics.

A topic can be displayed with a percentage whenever there is at least one question, but it is ranked as strongest/weakest only if the attempt contains at least three questions for that topic. If several eligible topics tie at an extreme, show all tied topics. Below the threshold, label “small sample—do not rank.” Questions with no topic are excluded from topic-level calculations and the excluded count is disclosed.

Do not infer a student's broad competence from one examination. Copy should use language such as “You missed 2 of 3 questions tagged Indexing and Query Optimization in this exam; consider revising that topic.”

## 8. Privacy and security

- Keep training data free of student answers and identifiable personal data.
- Do not train automatically on student results.
- Enforce faculty-only access to question suggestion endpoint.
- Treat question text as untrusted input, but the classifier does not execute it.
- Local model artifact path comes from configuration.
- Only load trusted, project-generated model artifacts; do not accept uploaded pickled models from users.
- The rest of the application must continue to function without the artifact.

## 9. Tests

- Training/evaluation command is deterministic for fixed inputs/seed to the extent expected by selected libraries.
- Artifact load succeeds in the expected environment.
- Known sample text returns a valid taxonomy code when confidence exceeds threshold; do not assert a made-up accuracy threshold.
- Low confidence returns no suggestion.
- Missing/corrupt artifact returns a safe fallback.
- Manual topic assignment succeeds with model disabled.
- Faculty override/clear is persisted correctly.
- No analytics endpoint describes deterministic statistics as ML.

**Document Status:** Draft — ML and Analytics Design
