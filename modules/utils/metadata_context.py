"""Shared taxonomy loader + prompt-builder for Step 3 metadata detection.

Used by both step3_metadata._extract_metadata_with_ai and
ai_metadata_detector.detect_all_fields so the two paths stay in sync.

The LLM is the *recommender*; the Python helpers are the *validator* — they
canonicalize the LLM's free-text answer against the closed taxonomy list and
reject hallucinations to None.
"""
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Optional

TAXONOMY_FILE = Path(__file__).parent / "metadata_taxonomy.json"


@lru_cache(maxsize=1)
def load_taxonomy() -> dict:
    """Load + cache the Algerian medical exam taxonomy."""
    with open(TAXONOMY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def build_context_block() -> str:
    """Render the taxonomy as a deterministic text block for the LLM prompt."""
    tax = load_taxonomy()
    faculties = ", ".join(tax["valid_faculties"])
    lines = [
        f"SYSTEM: {tax['system_instruction']}",
        f"VALID FACULTIES: {faculties}",
        "VALID MODULES BY LEVEL:",
    ]
    for level, modules in tax["valid_modules"].items():
        lines.append(f"  {level}: {', '.join(modules)}")
    lines.append("RULES:")
    for r in tax["rules"]:
        lines.append(f"  - {r}")
    return "\n".join(lines)


def _strip_accents(s: str) -> str:
    """Remove diacritics for case/accent-tolerant comparison."""
    if not s:
        return ""
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def normalize_module(value: Optional[str]) -> Optional[str]:
    """Case-insensitive, accent-tolerant match against valid_modules.
    Returns the canonical module name (exactly as written in the taxonomy)
    or None when the LLM hallucinated a name outside the closed list."""
    if not value:
        return None
    tax = load_taxonomy()
    target = _strip_accents(value).lower()
    for level, modules in tax["valid_modules"].items():
        for m in modules:
            if _strip_accents(m).lower() == target:
                return m
    return None


def normalize_year(value: Optional[str]) -> Optional[str]:
    """Apply the year rule: '2025/2026' -> '2025', '2024' stays '2024'."""
    if not value:
        return None
    v = str(value).strip()
    if "/" in v:
        return v.split("/")[0].strip()
    return v


def normalize_faculty(value: Optional[str]) -> Optional[str]:
    """Case/accent-tolerant match against valid_faculties. Returns canonical or None."""
    if not value:
        return None
    tax = load_taxonomy()
    target = _strip_accents(value).lower()
    for f in tax["valid_faculties"]:
        if _strip_accents(f).lower() == target:
            return f
    return None


def find_faculty_in_text(text: str) -> Optional[str]:
    """Scan page text for any valid_faculties mention (accent-tolerant word match).
    Returns the canonical faculty name or None. Useful as a fallback when the
    LLM omits the faculty but it's clearly in the document header."""
    if not text:
        return None
    tax = load_taxonomy()
    stripped = _strip_accents(text).lower()
    for f in tax["valid_faculties"]:
        # word-boundary match on the accent-stripped, lowercased form
        pat = r"\b" + re.escape(_strip_accents(f).lower()) + r"\b"
        if re.search(pat, stripped):
            return f
    return None


def derive_source(module: Optional[str], faculty: Optional[str],
                  is_residanat: bool = False) -> Optional[str]:
    """Apply the source-derivation rule.
    - Externat: module matched -> 'Externat {Faculty}'
    - Residanat: no module OR is_residanat flag -> 'Residanat {Faculty}'
    Returns None when faculty is unknown (no source can be derived)."""
    if not faculty:
        return None
    if module and not is_residanat:
        return f"Externat {faculty}"
    return f"Residanat {faculty}"