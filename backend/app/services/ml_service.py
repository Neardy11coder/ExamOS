"""
ML Topic Classification Service (M4-ML-1).

Loads the trained TF-IDF + Logistic Regression pipeline artifact at startup
and exposes a single suggest_topic() function with graceful degradation.

Design rules (docs/07_AI_ML_DESIGN.md, docs/04_API_CONTRACT.md §8):
- The classifier is optional and advisory only. Absence or failure of the
  artifact must NEVER block question-bank or exam-authoring flows.
- If the model is missing, fails to load, or throws during prediction, the
  service returns available=False with an appropriate reason code.
- Confidence must meet ML_CONFIDENCE_THRESHOLD before a suggestion is emitted.
- Raw artifact paths, training records, or unconfirmed predictions are never
  returned to the caller.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.schemas.ml import TopicSuggestionDetails, TopicSuggestionResponse
from app.services.topic_service import TAXONOMY_TOPICS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reason codes returned when a suggestion is unavailable
# ---------------------------------------------------------------------------
REASON_LOW_CONFIDENCE = "LOW_CONFIDENCE"
REASON_MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
# Distinct load vs inference failure codes (spec FR-ML-011)
REASON_MODEL_LOAD_FAILED = "MODEL_LOAD_FAILED"
REASON_INFERENCE_FAILED = "INFERENCE_FAILED"
# Legacy alias kept for backward compatibility with tests that import MODEL_ERROR
REASON_MODEL_ERROR = "MODEL_ERROR"

# Build a code → name lookup from the authoritative taxonomy
_TOPIC_NAME_BY_CODE: dict[str, str] = {
    entry["code"]: entry["name"] for entry in TAXONOMY_TOPICS
}

# ---------------------------------------------------------------------------
# Module-level pipeline cache (lazy-loaded on first call)
# ---------------------------------------------------------------------------
_pipeline: Any | None = None
_pipeline_load_attempted: bool = False


def _get_taxonomy_codes() -> list[str]:
    """Return the authoritative taxonomy codes from the service layer."""
    return [entry["code"] for entry in TAXONOMY_TOPICS]


class _DistilBertPipelineWrapper:
    """Adapter wrapping a fine-tuned DistilBERT / HuggingFace or ONNX pipeline."""

    def __init__(self, model: Any, tokenizer: Any, classes: list[str]):
        self.model = model
        self.tokenizer = tokenizer
        self.classes_ = classes

    def predict_proba(self, texts: list[str]) -> list[list[float]]:
        import torch

        self.model.eval()
        inputs = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=128,
            return_tensors="pt",
        )
        with torch.no_grad():
            outputs = self.model(**inputs)
            logits = outputs.logits
            probs = torch.softmax(logits, dim=-1).tolist()
        return probs


def _load_distilbert_from_directory(dir_path: Path) -> Any | None:
    """Attempt loading a fine-tuned DistilBERT model and tokenizer from directory."""
    if not dir_path.is_dir():
        return None

    weights_file = dir_path / "model.safetensors"
    bin_file = dir_path / "pytorch_model.bin"
    if not (weights_file.exists() or bin_file.exists()):
        return None

    try:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(str(dir_path))
        model = AutoModelForSequenceClassification.from_pretrained(str(dir_path))
        classes = [model.config.id2label[i] for i in range(len(model.config.id2label))]
        logger.info("DistilBERT topic classifier loaded successfully from %s", dir_path)
        return _DistilBertPipelineWrapper(model, tokenizer, classes)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Found DistilBERT directory but failed to load: %s", type(exc).__name__)
        return None


def _load_pipeline() -> Any | None:
    """
    Load the topic classifier artifact once and cache it.
    Supports:
      1. DistilBERT fine-tuned model directory (PyTorch / Safetensors)
      2. Scikit-learn Pipeline artifact (.joblib)
      3. Fallback path if configured

    - Returns None when the artifact is absent or fails to load.
    - Returns None when the loaded model's classes are incompatible with the
      current taxonomy (e.g. retrained on a different class set).
    - Never raises; all failures are logged at WARNING level.
    """
    global _pipeline, _pipeline_load_attempted
    if _pipeline_load_attempted:
        return _pipeline

    _pipeline_load_attempted = True

    backend_dir = Path(__file__).resolve().parents[2]

    # Candidate paths to inspect in order
    candidate_raw_paths = [settings.ML_MODEL_PATH]
    fallback_path = getattr(settings, "ML_FALLBACK_MODEL_PATH", None)
    if fallback_path:
        candidate_raw_paths.append(fallback_path)

    loaded = None
    for raw_path in candidate_raw_paths:
        if not raw_path:
            continue
        artifact_path = Path(raw_path)
        if not artifact_path.is_absolute():
            artifact_path = (backend_dir / artifact_path).resolve()

        # Check 1: Directory with DistilBERT model
        if artifact_path.is_dir():
            distilbert_wrapper = _load_distilbert_from_directory(artifact_path)
            if distilbert_wrapper is not None:
                loaded = distilbert_wrapper
                break

        # Check 2: Single-file artifact (.joblib)
        elif artifact_path.is_file():
            try:
                import joblib  # type: ignore[import-untyped]
                loaded = joblib.load(artifact_path)
                logger.info("Loaded baseline ML pipeline from %s", artifact_path)
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to load artifact %s: %s", artifact_path, type(exc).__name__)

    if loaded is None:
        logger.warning(
            "No usable ML topic model artifact found (tried: %s). Topic suggestions will be unavailable.",
            candidate_raw_paths,
        )
        return None

    # Guard: model must contain all current taxonomy classes
    taxonomy_codes = set(_get_taxonomy_codes())
    model_classes = set(getattr(loaded, "classes_", []))
    if not taxonomy_codes.issubset(model_classes):
        missing = sorted(taxonomy_codes - model_classes)
        logger.warning(
            "ML model is incompatible with current taxonomy — missing classes: %s. "
            "Topic suggestions disabled. Retrain the model.",
            missing,
        )
        return None

    _pipeline = loaded
    return _pipeline


def suggest_topic(prompt: str, options: list[str] | None = None) -> TopicSuggestionResponse:
    """
    Predict the most likely taxonomy topic for a question prompt.

    Args:
        prompt:  The question text (already stripped of leading/trailing whitespace).
        options: Optional list of option texts to append for richer context.

    Returns:
        TopicSuggestionResponse with available=True and a suggestion when
        the model is present and confidence >= threshold, or available=False
        with a reason code otherwise.

    Raises:
        ValueError: if ML_CONFIDENCE_THRESHOLD is outside the valid [0.0, 1.0] range.
                    This is a configuration error and should surface at startup/test time.
    """
    threshold = settings.ML_CONFIDENCE_THRESHOLD
    if not (0.0 <= threshold <= 1.0):
        raise ValueError(
            f"ML_CONFIDENCE_THRESHOLD must be between 0.0 and 1.0, got {threshold!r}"
        )

    pipeline = _load_pipeline()

    if pipeline is None:
        return TopicSuggestionResponse(
            available=False,
            suggestion=None,
            reason=REASON_MODEL_NOT_FOUND,
        )

    # Build the input text: prompt + option texts (if any)
    parts = [prompt]
    if options:
        parts.extend(opt for opt in options if opt)
    input_text = " ".join(parts)

    try:
        # predict_proba returns shape (1, n_classes); use pure Python max to
        # avoid numpy dependency in the service layer (tests may pass plain lists).
        proba = pipeline.predict_proba([input_text])[0]
        classes = list(pipeline.classes_)

        best_idx, best_confidence_raw = max(
            enumerate(proba), key=lambda kv: kv[1]
        )
        best_code: str = classes[best_idx]
        best_confidence: float = float(best_confidence_raw)

        if best_confidence < threshold:
            return TopicSuggestionResponse(
                available=False,
                suggestion=None,
                reason=REASON_LOW_CONFIDENCE,
            )

        topic_name = _TOPIC_NAME_BY_CODE.get(best_code, best_code)

        return TopicSuggestionResponse(
            available=True,
            suggestion=TopicSuggestionDetails(
                topic_code=best_code,
                topic_name=topic_name,
                confidence=round(best_confidence, 4),
                threshold=threshold,
            ),
            reason=None,
        )

    except Exception as exc:  # noqa: BLE001
        logger.warning("ML prediction failed: %s", type(exc).__name__)
        return TopicSuggestionResponse(
            available=False,
            suggestion=None,
            reason=REASON_MODEL_ERROR,
        )


def reset_pipeline_cache() -> None:
    """
    Reset the module-level pipeline cache.

    Intended for testing only: allows injection of mock artifacts between tests
    without module reload.
    """
    global _pipeline, _pipeline_load_attempted
    _pipeline = None
    _pipeline_load_attempted = False
