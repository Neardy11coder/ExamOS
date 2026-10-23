# ExamOS Question Topic Classifier — Evaluation Report

- **Evaluated At:** 2026-10-23T15:54:00.816696+00:00
- **Model Artifact:** `topic_classifier.joblib`
- **Dataset Split:** 80% Train (128 samples) / 20% Test (32 samples), Seed=42
- **Overall Accuracy:** **68.8%**
- **Macro F1:** **0.6496**
- **Weighted F1:** **0.6496**

## Per-Topic Performance

| Topic Code | Precision | Recall | F1-Score | Test Samples |
|---|---|---|---|---|
| `OS_PROCESS` | 0.80 | 1.00 | 0.89 | 4 |
| `OS_SCHEDULING` | 0.80 | 1.00 | 0.89 | 4 |
| `OS_SYNC` | 0.00 | 0.00 | 0.00 | 4 |
| `OS_MEMORY_FILES` | 1.00 | 0.75 | 0.86 | 4 |
| `DB_NORMALIZATION` | 1.00 | 0.50 | 0.67 | 4 |
| `DB_SQL_JOINS` | 0.43 | 0.75 | 0.55 | 4 |
| `DB_TRANSACTIONS` | 0.75 | 0.75 | 0.75 | 4 |
| `DB_INDEXING` | 0.50 | 0.75 | 0.60 | 4 |

## Known Model Limitations

1. Modest development dataset (160 samples total, 20 per class).
2. Conceptual overlap on cross-cutting terms (e.g. transactions vs query joins).
3. High-confidence heuristic threshold (default 0.55) required for displaying suggestions to avoid false positives.
