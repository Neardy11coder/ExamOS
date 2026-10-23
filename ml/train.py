"""
Training pipeline for ExamOS Question Topic Classifier (M4-ML-1).

Usage:
  python -m ml.train
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import joblib
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from ml import TAXONOMY_TOPIC_CODES
from ml.dataset import DEFAULT_SPLIT_SEED, DEFAULT_TEST_SIZE, get_stratified_split, load_dataset
from ml.preprocessing import normalize_text

DEFAULT_ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
DEFAULT_MODEL_FILE = DEFAULT_ARTIFACTS_DIR / "topic_classifier.joblib"
DEFAULT_METADATA_FILE = DEFAULT_ARTIFACTS_DIR / "topic_classifier_metadata.json"


def train_pipeline(
    dataset_path: Path | str | None = None,
    output_model_path: Path | str | None = None,
    output_metadata_path: Path | str | None = None,
    split_seed: int = DEFAULT_SPLIT_SEED,
    test_size: float = DEFAULT_TEST_SIZE,
    max_iter: int = 1000,
    c_param: float = 1.0,
) -> dict:
    """
    Trains a reproducible TF-IDF + Logistic Regression pipeline on the stratified training split.
    Saves:
      1. Serialized Pipeline artifact (.joblib)
      2. Metadata JSON containing taxonomy version, library versions, hyperparameters, and split configuration.
    """
    records = load_dataset(dataset_path)
    train_records, test_records = get_stratified_split(records, test_size=test_size, seed=split_seed)

    x_train = [r["normalized_text"] for r in train_records]
    y_train = [r["topic_code"] for r in train_records]

    pipeline = Pipeline(
        steps=[
            (
                "tfidf",
                TfidfVectorizer(
                    ngram_range=(1, 2),
                    min_df=1,
                    sublinear_tf=True,
                    preprocessor=None,
                    tokenizer=None,
                ),
            ),
            (
                "classifier",
                LogisticRegression(
                    C=c_param,
                    max_iter=max_iter,
                    random_state=split_seed,
                    solver="lbfgs",
                ),
            ),
        ]
    )

    pipeline.fit(x_train, y_train)

    # Validate pipeline learned all 8 taxonomy classes
    model_classes = list(pipeline.classes_)
    missing_classes = set(TAXONOMY_TOPIC_CODES) - set(model_classes)
    if missing_classes:
        raise RuntimeError(f"Trained model is missing classes: {missing_classes}")

    model_path = Path(output_model_path) if output_model_path else DEFAULT_MODEL_FILE
    metadata_path = Path(output_metadata_path) if output_metadata_path else DEFAULT_METADATA_FILE

    model_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)

    joblib.dump(pipeline, model_path)

    metadata = {
        "artifact_version": "1.0.0",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "taxonomy_classes": TAXONOMY_TOPIC_CODES,
        "model_classes": [str(c) for c in model_classes],
        "dataset_total_samples": len(records),
        "train_samples": len(train_records),
        "test_samples": len(test_records),
        "split_seed": split_seed,
        "test_size": test_size,
        "library_versions": {
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
            "python": sys.version.split()[0],
        },
        "pipeline_parameters": {
            "tfidf__ngram_range": [1, 2],
            "tfidf__sublinear_tf": True,
            "classifier__C": c_param,
            "classifier__max_iter": max_iter,
            "classifier__solver": "lbfgs",
            "classifier__random_state": split_seed,
        },
    }

    with open(metadata_path, mode="w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Train ExamOS Question Topic Classification Pipeline")
    parser.add_argument("--seed", type=int, default=DEFAULT_SPLIT_SEED, help="Random seed for train/test split")
    parser.add_argument("--test-size", type=float, default=DEFAULT_TEST_SIZE, help="Held-out evaluation fraction")
    args = parser.parse_args()

    print(f"Starting ML training pipeline (Seed: {args.seed}, Test Size: {args.test_size})...")
    meta = train_pipeline(split_seed=args.seed, test_size=args.test_size)
    print("Training complete:")
    print(f"  - Total samples: {meta['dataset_total_samples']} (Train: {meta['train_samples']}, Test: {meta['test_samples']})")
    print(f"  - Classes ({len(meta['model_classes'])}): {', '.join(meta['model_classes'])}")
    print(f"  - Artifact saved to {DEFAULT_MODEL_FILE}")
    print(f"  - Metadata saved to {DEFAULT_METADATA_FILE}")


if __name__ == "__main__":
    main()
