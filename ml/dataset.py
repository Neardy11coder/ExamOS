"""
Dataset loader and stratified splitting utilities for topic classification (M4-ML-1).
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from sklearn.model_selection import train_test_split

from ml import TAXONOMY_TOPIC_CODES
from ml.preprocessing import normalize_text

DEFAULT_DATASET_PATH = Path(__file__).resolve().parent / "data" / "question_topics.csv"
DEFAULT_SPLIT_SEED = 42
DEFAULT_TEST_SIZE = 0.20


def load_dataset(csv_path: Path | str | None = None) -> list[dict[str, str]]:
    """
    Loads and validates the topic classification dataset.

    Checks:
    - Exactly all 8 taxonomy topics are present.
    - No empty prompts or topic codes.
    - No duplicate normalized prompts.
    """
    path = Path(csv_path) if csv_path else DEFAULT_DATASET_PATH
    if not path.is_file():
        raise FileNotFoundError(f"Dataset CSV not found at {path}")

    records: list[dict[str, str]] = []
    seen_texts: set[str] = set()

    with open(path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader, start=1):
            topic = (row.get("topic_code") or "").strip()
            raw_text = (row.get("text") or "").strip()
            notes = (row.get("notes") or "").strip()

            if not topic:
                raise ValueError(f"Row {idx} is missing 'topic_code'")
            if not raw_text:
                raise ValueError(f"Row {idx} is missing 'text'")
            if topic not in TAXONOMY_TOPIC_CODES:
                raise ValueError(f"Row {idx} has unrecognized topic '{topic}'. Must be one of {TAXONOMY_TOPIC_CODES}")

            normalized = normalize_text(raw_text)
            if normalized in seen_texts:
                raise ValueError(f"Duplicate question text found at row {idx}: '{raw_text}'")
            seen_texts.add(normalized)

            records.append({
                "topic_code": topic,
                "text": raw_text,
                "normalized_text": normalized,
                "notes": notes,
            })

    # Validate that every taxonomy topic is represented
    present_topics = {r["topic_code"] for r in records}
    missing_topics = set(TAXONOMY_TOPIC_CODES) - present_topics
    if missing_topics:
        raise ValueError(f"Dataset is missing required taxonomy classes: {sorted(missing_topics)}")

    return records


def get_stratified_split(
    records: list[dict[str, str]],
    test_size: float = DEFAULT_TEST_SIZE,
    seed: int = DEFAULT_SPLIT_SEED,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """
    Performs a deterministic, stratified train/test split.
    Prevents leakage by checking set disjointness.
    """
    labels = [r["topic_code"] for r in records]
    indices = list(range(len(records)))

    train_indices, test_indices = train_test_split(
        indices,
        test_size=test_size,
        random_state=seed,
        stratify=labels,
    )

    train_records = [records[i] for i in train_indices]
    test_records = [records[i] for i in test_indices]

    # Verify no overlap
    train_texts = {r["normalized_text"] for r in train_records}
    test_texts = {r["normalized_text"] for r in test_records}
    overlap = train_texts.intersection(test_texts)
    if overlap:
        raise RuntimeError(f"Data leakage detected between train and test splits: {len(overlap)} overlapping records.")

    return train_records, test_records
