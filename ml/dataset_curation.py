"""
StackSample and Curated CS Dataset Ingestion and Validation Pipeline (M8-ML-DISTILBERT).

Provides:
- Tag-to-Taxonomy mapping for StackSample / StackOverflow questions.
- Provenance recording (source_id, url, license, score, tags).
- Strict deduplication (both exact and normalized text matching).
- 3-way deterministic split: Train (70%), Validation (15%), Test (15%) with stratification.
- Export to train/val/test CSVs and consolidated question_topics.csv.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from sklearn.model_selection import train_test_split

from ml import TAXONOMY_TOPIC_CODES
from ml.preprocessing import normalize_text

ML_DATA_DIR = Path(__file__).resolve().parent / "data"
RAW_DATA_DIR = ML_DATA_DIR / "raw"
CONSOLIDATED_DATASET_PATH = ML_DATA_DIR / "question_topics.csv"
PROVENANCE_METADATA_PATH = ML_DATA_DIR / "dataset_provenance.json"

TRAIN_SPLIT_PATH = ML_DATA_DIR / "train.csv"
VAL_SPLIT_PATH = ML_DATA_DIR / "val.csv"
TEST_SPLIT_PATH = ML_DATA_DIR / "test.csv"

# Tag mapping rules from StackOverflow/StackSample tags to authoritative 8-class taxonomy
STACK_TAG_TO_TAXONOMY: dict[str, str] = {
    # OS_PROCESS
    "process": "OS_PROCESS",
    "fork": "OS_PROCESS",
    "ipc": "OS_PROCESS",
    "named-pipes": "OS_PROCESS",
    "shared-memory": "OS_PROCESS",
    "posix": "OS_PROCESS",
    "signals": "OS_PROCESS",

    # OS_SCHEDULING
    "cpu-scheduling": "OS_SCHEDULING",
    "round-robin": "OS_SCHEDULING",
    "multilevel-feedback-queue": "OS_SCHEDULING",
    "context-switch": "OS_SCHEDULING",

    # OS_SYNC
    "deadlock": "OS_SYNC",
    "mutex": "OS_SYNC",
    "semaphore": "OS_SYNC",
    "race-condition": "OS_SYNC",
    "concurrency": "OS_SYNC",
    "critical-section": "OS_SYNC",

    # OS_MEMORY_FILES
    "virtual-memory": "OS_MEMORY_FILES",
    "page-fault": "OS_MEMORY_FILES",
    "paging": "OS_MEMORY_FILES",
    "mmu": "OS_MEMORY_FILES",
    "file-system": "OS_MEMORY_FILES",
    "inode": "OS_MEMORY_FILES",

    # DB_NORMALIZATION
    "database-normalization": "DB_NORMALIZATION",
    "normal-form": "DB_NORMALIZATION",
    "functional-dependency": "DB_NORMALIZATION",
    "bcnf": "DB_NORMALIZATION",

    # DB_SQL_JOINS
    "inner-join": "DB_SQL_JOINS",
    "outer-join": "DB_SQL_JOINS",
    "left-join": "DB_SQL_JOINS",
    "cross-join": "DB_SQL_JOINS",
    "sql-joins": "DB_SQL_JOINS",

    # DB_TRANSACTIONS
    "acid": "DB_TRANSACTIONS",
    "two-phase-commit": "DB_TRANSACTIONS",
    "isolation-level": "DB_TRANSACTIONS",
    "database-transaction": "DB_TRANSACTIONS",
    "wal": "DB_TRANSACTIONS",

    # DB_INDEXING
    "indexing": "DB_INDEXING",
    "b-tree": "DB_INDEXING",
    "query-planner": "DB_INDEXING",
    "explain-analyze": "DB_INDEXING",
    "sequential-scan": "DB_INDEXING",
    "index-scan": "DB_INDEXING",
}


def compute_content_hash(text: str) -> str:
    """Compute SHA-256 hash of normalized text for provenance tracking."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()[:16]


def validate_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Validates records against the 8-class taxonomy:
    - No empty texts or topic codes.
    - All 8 classes represented.
    - No duplicate normalized prompts.
    """
    seen: set[str] = set()
    validated: list[dict[str, Any]] = []

    for idx, r in enumerate(records, start=1):
        topic = (r.get("topic_code") or "").strip()
        text = (r.get("text") or "").strip()
        if not topic:
            raise ValueError(f"Record {idx} missing 'topic_code'")
        if not text:
            raise ValueError(f"Record {idx} missing 'text'")
        if topic not in TAXONOMY_TOPIC_CODES:
            raise ValueError(f"Record {idx} invalid topic '{topic}'. Must be one of {TAXONOMY_TOPIC_CODES}")

        norm = normalize_text(text)
        if norm in seen:
            continue  # Deduplicate cleanly
        seen.add(norm)

        r["normalized_text"] = norm
        r["hash"] = compute_content_hash(text)
        validated.append(r)

    # Check class coverage
    classes_present = {r["topic_code"] for r in validated}
    missing = set(TAXONOMY_TOPIC_CODES) - classes_present
    if missing:
        raise ValueError(f"Dataset missing required taxonomy classes: {sorted(missing)}")

    return validated


def create_stratified_splits(
    records: list[dict[str, Any]],
    val_size: float = 0.15,
    test_size: float = 0.15,
    seed: int = 42,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Creates deterministic, stratified 3-way train/val/test splits (70/15/15 default).
    Verifies zero data leakage between partitions.
    """
    labels = [r["topic_code"] for r in records]
    indices = list(range(len(records)))

    # First split off test set
    train_val_idx, test_idx = train_test_split(
        indices,
        test_size=test_size,
        random_state=seed,
        stratify=labels,
    )

    # Second split train_val into train and val
    train_val_labels = [labels[i] for i in train_val_idx]
    relative_val_size = val_size / (1.0 - test_size)

    train_idx, val_idx = train_test_split(
        train_val_idx,
        test_size=relative_val_size,
        random_state=seed,
        stratify=train_val_labels,
    )

    train_set = [records[i] for i in train_idx]
    val_set = [records[i] for i in val_idx]
    test_set = [records[i] for i in test_idx]

    # Leakage verification
    train_texts = {r["normalized_text"] for r in train_set}
    val_texts = {r["normalized_text"] for r in val_set}
    test_texts = {r["normalized_text"] for r in test_set}

    if train_texts & val_texts:
        raise RuntimeError(f"Data leakage between train and val: {len(train_texts & val_texts)} texts")
    if train_texts & test_texts:
        raise RuntimeError(f"Data leakage between train and test: {len(train_texts & test_texts)} texts")
    if val_texts & test_texts:
        raise RuntimeError(f"Data leakage between val and test: {len(val_texts & test_texts)} texts")

    return train_set, val_set, test_set


def save_split_csv(records: list[dict[str, Any]], file_path: Path) -> None:
    """Save partition records to CSV with topic_code, text, notes."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["topic_code", "text", "notes"])
        writer.writeheader()
        for r in records:
            writer.writerow({
                "topic_code": r["topic_code"],
                "text": r["text"],
                "notes": r.get("notes", ""),
            })
