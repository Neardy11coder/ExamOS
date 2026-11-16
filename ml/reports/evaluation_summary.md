# ExamOS Question Topic Classifier — Evaluation Report

- **Evaluated At:** 2026-11-09T19:30:12.809424+00:00
- **Model Artifact:** `test_model.joblib`
- **Dataset Split:** 80% Train (256 samples) / 20% Test (64 samples), Seed=42
- **Overall Accuracy:** **78.1%**
- **Macro F1:** **0.7737**
- **Weighted F1:** **0.7737**

## Per-Topic Performance

| Topic Code | Precision | Recall | F1-Score | Test Samples |
|---|---|---|---|---|
| `OS_PROCESS` | 0.60 | 0.75 | 0.67 | 8 |
| `OS_SCHEDULING` | 0.88 | 0.88 | 0.88 | 8 |
| `OS_SYNC` | 0.50 | 0.38 | 0.43 | 8 |
| `OS_MEMORY_FILES` | 0.80 | 1.00 | 0.89 | 8 |
| `DB_NORMALIZATION` | 0.83 | 0.62 | 0.71 | 8 |
| `DB_SQL_JOINS` | 0.89 | 1.00 | 0.94 | 8 |
| `DB_TRANSACTIONS` | 0.86 | 0.75 | 0.80 | 8 |
| `DB_INDEXING` | 0.88 | 0.88 | 0.88 | 8 |

## Known Model Limitations

1. Modest development dataset (160 samples total, 20 per class).
2. Conceptual overlap on cross-cutting terms (e.g. transactions vs query joins).
3. High-confidence heuristic threshold (default 0.55) required for displaying suggestions to avoid false positives.
