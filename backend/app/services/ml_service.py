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


def _load_pipeline() -> Any | None:
    """
    Load the joblib pipeline artifact once and cache it.

    - Returns None when the artifact is absent or fails to load.
    - Returns None when the loaded model's classes are incompatible with the
      current taxonomy (e.g. retrained on a different class set).
    - Never raises; all failures are logged at WARNING level.
    """
    global _pipeline, _pipeline_load_attempted
    if _pipeline_load_attempted:
        return _pipeline

    _pipeline_load_attempted = True

    raw_path = settings.ML_MODEL_PATH
    artifact_path = Path(raw_path)
    if not artifact_path.is_absolute():
        backend_dir = Path(__file__).resolve().parents[2]
        artifact_path = (backend_dir / artifact_path).resolve()

    if not artifact_path.is_file():
        logger.warning(
            "ML model artifact not found. Topic suggestions will be unavailable."
        )
        return None

    try:
        import joblib  # type: ignore[import-untyped]

        loaded = joblib.load(artifact_path)

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
        logger.info("ML topic classifier loaded successfully.")
        return _pipeline
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load ML model: %s", type(exc).__name__)
        return None


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
