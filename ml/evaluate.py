"""
Evaluation pipeline for ExamOS Question Topic Classifier (M4-ML-1).

Usage:
  python -m ml.evaluate
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import joblib
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)

from ml import TAXONOMY_TOPIC_CODES
from ml.dataset import DEFAULT_SPLIT_SEED, DEFAULT_TEST_SIZE, get_stratified_split, load_dataset
from ml.train import DEFAULT_METADATA_FILE, DEFAULT_MODEL_FILE

DEFAULT_REPORTS_DIR = Path(__file__).resolve().parent / "reports"
DEFAULT_EVALUATION_REPORT_FILE = DEFAULT_REPORTS_DIR / "evaluation_report.json"
DEFAULT_EVALUATION_SUMMARY_FILE = DEFAULT_REPORTS_DIR / "evaluation_summary.md"


def evaluate_pipeline(
    model_path: Path | str | None = None,
    metadata_path: Path | str | None = None,
    dataset_path: Path | str | None = None,
    output_report_path: Path | str | None = None,
    output_summary_path: Path | str | None = None,
    split_seed: int = DEFAULT_SPLIT_SEED,
    test_size: float = DEFAULT_TEST_SIZE,
) -> dict:
    """
    Evaluates the trained model artifact against the deterministic held-out test split.
    Computes:
      - Overall Accuracy
      - Per-class Precision, Recall, F1-score, and Support
      - Macro and Weighted F1-scores
      - Multi-class Confusion Matrix
    Writes out machine-readable JSON and human-readable Markdown evaluation reports.
    """
    m_path = Path(model_path) if model_path else DEFAULT_MODEL_FILE
    meta_path = Path(metadata_path) if metadata_path else DEFAULT_METADATA_FILE

    if not m_path.is_file():
        raise FileNotFoundError(f"Model artifact not found at {m_path}. Please run 'python -m ml.train' first.")

    pipeline = joblib.load(m_path)

    records = load_dataset(dataset_path)
    train_records, test_records = get_stratified_split(records, test_size=test_size, seed=split_seed)

    x_test = [r["normalized_text"] for r in test_records]
    y_test = [r["topic_code"] for r in test_records]

    y_pred = pipeline.predict(x_test)

    acc = float(accuracy_score(y_test, y_pred))
    macro_f1 = float(f1_score(y_test, y_pred, average="macro", zero_division=0))
    weighted_f1 = float(f1_score(y_test, y_pred, average="weighted", zero_division=0))

    report_dict = classification_report(
        y_test,
        y_pred,
        labels=TAXONOMY_TOPIC_CODES,
        output_dict=True,
        zero_division=0,
    )

    cm = confusion_matrix(y_test, y_pred, labels=TAXONOMY_TOPIC_CODES).tolist()

    metadata_info = {}
    if meta_path.is_file():
        with open(meta_path, mode="r", encoding="utf-8") as f:
            metadata_info = json.load(f)

    evaluation_data = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "model_file": str(m_path.name),
        "split_seed": split_seed,
        "test_size": test_size,
        "dataset_total_samples": len(records),
        "train_samples": len(train_records),
        "test_samples": len(test_records),
        "overall_metrics": {
            "accuracy": round(acc, 4),
            "macro_f1": round(macro_f1, 4),
            "weighted_f1": round(weighted_f1, 4),
        },
        "per_topic_metrics": {
            topic: {
                "precision": round(report_dict[topic]["precision"], 4),
                "recall": round(report_dict[topic]["recall"], 4),
                "f1_score": round(report_dict[topic]["f1-score"], 4),
                "test_support": int(report_dict[topic]["support"]),
            }
            for topic in TAXONOMY_TOPIC_CODES
            if topic in report_dict
        },
        "confusion_matrix": {
            "labels": TAXONOMY_TOPIC_CODES,
            "matrix": cm,
        },
        "metadata_info": metadata_info,
        "limitations": [
            "Dataset scale is a modest development baseline (160 samples, 20 per topic).",
            "Near-boundary topics (e.g. DB_INDEXING vs DB_SQL_JOINS, or OS_PROCESS vs OS_SCHEDULING) may display semantic overlap on concise questions.",
            "Model predictions are strictly advisory; faculty confirmation remains authoritative.",
        ],
    }

    rep_path = Path(output_report_path) if output_report_path else DEFAULT_EVALUATION_REPORT_FILE
    sum_path = Path(output_summary_path) if output_summary_path else DEFAULT_EVALUATION_SUMMARY_FILE

    rep_path.parent.mkdir(parents=True, exist_ok=True)
    sum_path.parent.mkdir(parents=True, exist_ok=True)

    with open(rep_path, mode="w", encoding="utf-8") as f:
        json.dump(evaluation_data, f, indent=2)

    # Format Markdown summary
    md_lines = [
        "# ExamOS Question Topic Classifier — Evaluation Report",
        "",
        f"- **Evaluated At:** {evaluation_data['evaluated_at']}",
        f"- **Model Artifact:** `{m_path.name}`",
        f"- **Dataset Split:** 80% Train ({len(train_records)} samples) / 20% Test ({len(test_records)} samples), Seed={split_seed}",
        f"- **Overall Accuracy:** **{acc * 100:.1f}%**",
        f"- **Macro F1:** **{macro_f1:.4f}**",
        f"- **Weighted F1:** **{weighted_f1:.4f}**",
        "",
        "## Per-Topic Performance",
        "",
        "| Topic Code | Precision | Recall | F1-Score | Test Samples |",
        "|---|---|---|---|---|",
    ]
    for topic in TAXONOMY_TOPIC_CODES:
        m = evaluation_data["per_topic_metrics"].get(topic, {})
        p = m.get("precision", 0.0)
        r = m.get("recall", 0.0)
        f1 = m.get("f1_score", 0.0)
        sup = m.get("test_support", 0)
        md_lines.append(f"| `{topic}` | {p:.2f} | {r:.2f} | {f1:.2f} | {sup} |")

    md_lines.extend([
        "",
        "## Known Model Limitations",
        "",
        "1. Modest development dataset (160 samples total, 20 per class).",
        "2. Conceptual overlap on cross-cutting terms (e.g. transactions vs query joins).",
        "3. High-confidence heuristic threshold (default 0.55) required for displaying suggestions to avoid false positives.",
    ])

    with open(sum_path, mode="w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    return evaluation_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate ExamOS Question Topic Classifier")
    parser.add_argument("--seed", type=int, default=DEFAULT_SPLIT_SEED, help="Random seed for train/test split")
    parser.add_argument("--test-size", type=float, default=DEFAULT_TEST_SIZE, help="Held-out evaluation fraction")
    args = parser.parse_args()

    print(f"Running ML evaluation pipeline (Seed: {args.seed}, Test Size: {args.test_size})...")
    eval_res = evaluate_pipeline(split_seed=args.seed, test_size=args.test_size)
    print("Evaluation Complete:")
    print(f"  - Accuracy: {eval_res['overall_metrics']['accuracy'] * 100:.1f}%")
    print(f"  - Macro F1: {eval_res['overall_metrics']['macro_f1']:.4f}")
    print(f"  - Reports written to:")
    print(f"    - {DEFAULT_EVALUATION_REPORT_FILE}")
    print(f"    - {DEFAULT_EVALUATION_SUMMARY_FILE}")


if __name__ == "__main__":
    main()
