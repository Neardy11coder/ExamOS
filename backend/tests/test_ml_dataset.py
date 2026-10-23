"""
Dataset, pipeline, and split tests for ExamOS ML topic classifier (M4-ML-1).

Covers:
- All eight taxonomy classes present in the CSV (FR-ML-002)
- At least 20 samples per class (FR-ML-002)
- No duplicate normalized prompts (dataset integrity)
- Stratified split: no text overlap between train and test splits (FR-ML-004)
- Deterministic reproducibility: same seed produces identical splits (FR-ML-004)
- Full train + held-out evaluation round-trip reports non-trivial accuracy
- ml_service threshold validation (invalid range raises ValueError)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path setup: allow importing the ml package from the project root.
# The project layout is:
#   ExamOS/
#     ml/          <- Python package to test
#     backend/     <- this test lives here (run with CWD = backend/)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ml import TAXONOMY_TOPIC_CODES
from ml.dataset import load_dataset, get_stratified_split, DEFAULT_DATASET_PATH
from ml.preprocessing import normalize_text


# ---------------------------------------------------------------------------
# Dataset integrity tests
# ---------------------------------------------------------------------------

class TestDatasetIntegrity:
    """Verifies the CSV source has correct coverage and no duplicates."""

    @pytest.fixture(scope="class")
    def records(self):
        return load_dataset()

    def test_all_eight_taxonomy_classes_present(self, records):
        """Every one of the 8 taxonomy codes must appear in the dataset."""
        present = {r["topic_code"] for r in records}
        missing = set(TAXONOMY_TOPIC_CODES) - present
        assert not missing, f"Dataset missing taxonomy classes: {sorted(missing)}"

    def test_exactly_eight_classes_no_extras(self, records):
        """Dataset must contain exactly the 8 approved taxonomy codes."""
        extra = {r["topic_code"] for r in records} - set(TAXONOMY_TOPIC_CODES)
        assert not extra, f"Dataset contains unrecognized topic codes: {sorted(extra)}"

    def test_minimum_twenty_samples_per_class(self, records):
        """Each class must have at least 20 labeled examples."""
        from collections import Counter
        counts = Counter(r["topic_code"] for r in records)
        below = {code: counts[code] for code in TAXONOMY_TOPIC_CODES if counts[code] < 20}
        assert not below, f"Classes with fewer than 20 samples: {below}"

    def test_total_dataset_size_at_least_160(self, records):
        """Total dataset must be at least 160 samples (20 × 8)."""
        assert len(records) >= 160, f"Only {len(records)} rows found; need >= 160"

    def test_no_duplicate_normalized_prompts(self, records):
        """Duplicate question texts (post-normalization) are forbidden."""
        seen: set[str] = set()
        duplicates: list[str] = []
        for r in records:
            norm = r["normalized_text"]
            if norm in seen:
                duplicates.append(norm[:80])
            seen.add(norm)
        assert not duplicates, f"Duplicate prompts detected: {duplicates}"

    def test_no_empty_texts_or_codes(self, records):
        """All rows must have non-empty text and topic_code."""
        empties = [
            i for i, r in enumerate(records, start=1)
            if not r["text"].strip() or not r["topic_code"].strip()
        ]
        assert not empties, f"Empty text or topic_code at row indices: {empties}"

    def test_dataset_path_exists(self):
        """The default CSV file must exist on disk."""
        assert DEFAULT_DATASET_PATH.is_file(), (
            f"Dataset CSV not found at {DEFAULT_DATASET_PATH}"
        )


# ---------------------------------------------------------------------------
# Stratified split tests
# ---------------------------------------------------------------------------

class TestStratifiedSplit:
    """Verifies the split is clean, stratified, and reproducible."""

    @pytest.fixture(scope="class")
    def records(self):
        return load_dataset()

    def test_no_text_overlap_between_train_and_test(self, records):
        """train and test normalized texts must be completely disjoint."""
        train, test = get_stratified_split(records)
        train_texts = {r["normalized_text"] for r in train}
        test_texts = {r["normalized_text"] for r in test}
        overlap = train_texts & test_texts
        assert not overlap, (
            f"Data leakage: {len(overlap)} texts appear in both train and test splits"
        )

    def test_split_sizes_sum_to_total(self, records):
        """Train + test counts must equal the full dataset."""
        train, test = get_stratified_split(records)
        assert len(train) + len(test) == len(records)

    def test_all_classes_represented_in_test_split(self, records):
        """Every taxonomy class must appear in the test split (stratified)."""
        _, test = get_stratified_split(records)
        test_classes = {r["topic_code"] for r in test}
        missing = set(TAXONOMY_TOPIC_CODES) - test_classes
        assert not missing, f"Classes absent from test split: {sorted(missing)}"

    def test_all_classes_represented_in_train_split(self, records):
        """Every taxonomy class must appear in the training split."""
        train, _ = get_stratified_split(records)
        train_classes = {r["topic_code"] for r in train}
        missing = set(TAXONOMY_TOPIC_CODES) - train_classes
        assert not missing, f"Classes absent from train split: {sorted(missing)}"

    def test_split_is_deterministic_with_same_seed(self, records):
        """Same seed must produce identical train/test partitions on repeat calls."""
        train_a, test_a = get_stratified_split(records, seed=42)
        train_b, test_b = get_stratified_split(records, seed=42)
        assert [r["text"] for r in train_a] == [r["text"] for r in train_b]
        assert [r["text"] for r in test_a] == [r["text"] for r in test_b]

    def test_different_seeds_produce_different_splits(self, records):
        """Different seeds should (almost certainly) produce different partitions."""
        train_a, _ = get_stratified_split(records, seed=42)
        train_b, _ = get_stratified_split(records, seed=99)
        texts_a = [r["text"] for r in train_a]
        texts_b = [r["text"] for r in train_b]
        assert texts_a != texts_b, (
            "Seeds 42 and 99 produced identical splits — likely a seeding bug"
        )

    def test_approximate_80_20_ratio(self, records):
        """Test fraction should be close to 20% (within ±5%)."""
        train, test = get_stratified_split(records)
        ratio = len(test) / len(records)
        assert 0.15 <= ratio <= 0.25, (
            f"Test fraction {ratio:.2%} is far from the expected 20%"
        )


# ---------------------------------------------------------------------------
# Training and evaluation round-trip test
# ---------------------------------------------------------------------------

class TestTrainingRoundTrip:
    """Runs a full train+evaluate cycle and asserts the results are plausible."""

    def test_train_produces_pipeline_with_all_classes(self, tmp_path):
        """train_pipeline must produce a model with exactly the 8 taxonomy classes."""
        from ml.train import train_pipeline

        model_path = tmp_path / "classifier.joblib"
        meta_path = tmp_path / "metadata.json"

        meta = train_pipeline(
            output_model_path=model_path,
            output_metadata_path=meta_path,
        )
        assert set(meta["model_classes"]) == set(TAXONOMY_TOPIC_CODES)
        assert meta["train_samples"] > 0
        assert meta["test_samples"] > 0

    def test_evaluate_reports_non_trivial_accuracy(self, tmp_path):
        """Held-out accuracy on the 8-class problem should exceed random baseline (~12.5%)."""
        from ml.train import train_pipeline
        from ml.evaluate import evaluate_pipeline

        model_path = tmp_path / "classifier.joblib"
        meta_path = tmp_path / "metadata.json"
        report_path = tmp_path / "report.json"
        summary_path = tmp_path / "summary.md"

        train_pipeline(output_model_path=model_path, output_metadata_path=meta_path)
        results = evaluate_pipeline(
            model_path=model_path,
            metadata_path=meta_path,
            output_report_path=report_path,
            output_summary_path=summary_path,
        )

        accuracy = results["overall_metrics"]["accuracy"]
        macro_f1 = results["overall_metrics"]["macro_f1"]
        # Random classifier would score ~12.5% — we must do substantially better.
        assert accuracy > 0.25, (
            f"Accuracy {accuracy:.1%} is barely above random baseline. "
            "Check dataset quality."
        )
        assert macro_f1 > 0.0, "Macro F1 must be positive"
        # Every taxonomy class must appear in per_topic_metrics
        assert set(results["per_topic_metrics"].keys()) == set(TAXONOMY_TOPIC_CODES)

    def test_metadata_contains_required_fields(self, tmp_path):
        """Training metadata must include taxonomy_classes, library_versions, etc."""
        from ml.train import train_pipeline
        import json

        model_path = tmp_path / "classifier.joblib"
        meta_path = tmp_path / "metadata.json"
        train_pipeline(output_model_path=model_path, output_metadata_path=meta_path)

        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)

        required_keys = {
            "artifact_version",
            "trained_at",
            "taxonomy_classes",
            "model_classes",
            "dataset_total_samples",
            "train_samples",
            "test_samples",
            "split_seed",
            "library_versions",
            "pipeline_parameters",
        }
        assert required_keys.issubset(meta.keys()), (
            f"Metadata missing keys: {required_keys - set(meta.keys())}"
        )
        assert set(meta["taxonomy_classes"]) == set(TAXONOMY_TOPIC_CODES)


# ---------------------------------------------------------------------------
# ml_service configuration validation tests
# ---------------------------------------------------------------------------

class TestMLServiceConfigValidation:
    """Verifies threshold and configuration guard-rails in the service layer."""

    def test_invalid_threshold_raises_value_error(self, monkeypatch):
        """suggest_topic must raise ValueError when threshold is out of [0, 1]."""
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

        from app.services.ml_service import suggest_topic
        from app.services import ml_service
        from unittest.mock import MagicMock

        # Provide a plausible pipeline so the threshold check is reached
        fake_pipeline = MagicMock()
        fake_pipeline.classes_ = list(TAXONOMY_TOPIC_CODES)
        fake_pipeline.predict_proba.return_value = [[0.9] + [0.01] * 7]
        ml_service._pipeline = fake_pipeline
        ml_service._pipeline_load_attempted = True

        mock_settings = MagicMock()
        mock_settings.ML_CONFIDENCE_THRESHOLD = 1.5  # invalid

        monkeypatch.setattr(ml_service, "settings", mock_settings)

        with pytest.raises(ValueError, match="ML_CONFIDENCE_THRESHOLD"):
            suggest_topic("What is a process?")

        ml_service._pipeline = None
        ml_service._pipeline_load_attempted = False
