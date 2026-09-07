"""Central model defaults for the active extraction pipeline.

Environment variables remain the source of truth in deployment. These
defaults only prevent different Step 6 paths from silently drifting apart.
"""

import os
from typing import Dict, Tuple


MODEL_DEFAULTS: Dict[str, Tuple[str, str]] = {
    "step1_ocr": (
        "qwen/qwen3-vl-30b-a3b-instruct",
        "qwen/qwen-2.5-vl-7b-instruct:free",
    ),
    "step6_text": (
        "nvidia/nemotron-3-nano-30b-a3b:free",
        "google/gemini-2.0-flash-lite-001",
    ),
    "step6_all_pages": (
        "google/gemini-2.5-flash-lite-preview-09-2025",
        "google/gemini-2.0-flash-001",
    ),
    "step6_auto_detect": (
        "deepseek/deepseek-v4-flash",
        "google/gemini-2.0-flash-001",
    ),
    "step6_reasoning": (
        "deepseek/deepseek-r1-distill-llama-70b",
        "deepseek/deepseek-r1",
    ),
}


ENV_KEYS: Dict[str, Tuple[str, str]] = {
    "step1_ocr": ("STEP1_MODEL", "STEP1_FALLBACK_MODEL"),
    "step6_text": ("STEP6_TEXT_MODEL", "STEP6_TEXT_FALLBACK_MODEL"),
    "step6_all_pages": (
        "STEP6_ALL_PAGES_MODEL",
        "STEP6_ALL_PAGES_FALLBACK_MODEL",
    ),
    "step6_auto_detect": (
        "STEP6_ALL_PAGES_MODEL",
        "STEP6_ALL_PAGES_FALLBACK_MODEL",
    ),
    "step6_reasoning": ("STEP6_AI_MODEL", "STEP6_AI_FALLBACK_MODEL"),
}


def get_model_pair(slot: str) -> Tuple[str, str]:
    """Return the configured primary/fallback pair for a pipeline slot."""
    if slot not in MODEL_DEFAULTS:
        raise KeyError(f"Unknown model policy slot: {slot}")

    primary_key, fallback_key = ENV_KEYS[slot]
    default_primary, default_fallback = MODEL_DEFAULTS[slot]
    primary = os.getenv(primary_key, "").strip() or default_primary
    fallback = os.getenv(fallback_key, "").strip() or default_fallback
    return primary, fallback
