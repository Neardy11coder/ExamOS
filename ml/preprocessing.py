"""
Preprocessing and text normalization utilities for topic classification (M4-ML-1).
"""

from __future__ import annotations

import re


def normalize_text(text: str) -> str:
    """
    Normalizes whitespace and basic punctuation spacing while preserving technical terms.
    Preserves alphanumeric characters, common programming/system characters (_, -, /),
    and standard question terminology.
    """
    if not text:
        return ""

    # Replace newlines, tabs, and carriage returns with space
    cleaned = re.sub(r"[\r\n\t]+", " ", text)
    # Collapse consecutive spaces
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.lower()


def combine_prompt_and_options(prompt: str, options: list[str] | None = None) -> str:
    """
    Combines question prompt and optional option text into a single model input string.
    Does not take or expect answer keys or correctness flags.
    """
    normalized_prompt = normalize_text(prompt)
    if not options:
        return normalized_prompt

    cleaned_options = [normalize_text(opt) for opt in options if opt and opt.strip()]
    if not cleaned_options:
        return normalized_prompt

    return f"{normalized_prompt} options: {' '.join(cleaned_options)}"
