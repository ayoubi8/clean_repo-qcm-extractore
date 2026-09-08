"""Stable names for user-facing pipeline result files."""

import json
import re
from pathlib import Path


def pdf_stem_for_context(context) -> str:
    """Return the uploaded PDF stem, with safe fallback for old projects."""
    fallback = "source"
    if context is None:
        return fallback

    base_path = getattr(context, "base_path", None)
    if base_path:
        metadata_path = Path(base_path) / "project.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            original_name = metadata.get("pdf_filename") or metadata.get("pdf_name")
            if original_name:
                fallback = Path(str(original_name)).stem or fallback
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    return re.sub(r"[^A-Za-z0-9._-]+", "_", fallback).strip("._") or "source"


def result_xlsx_name(kind: str, count: int, pdf_stem: str) -> str:
    """Build a stable, human-readable workbook filename."""
    if kind not in ("qcms", "corrections"):
        raise ValueError(f"Unsupported result kind: {kind}")
    label = "qcms" if kind == "qcms" else "corrections"
    return f"{int(count)}_{label}_{pdf_stem}.xlsx"
