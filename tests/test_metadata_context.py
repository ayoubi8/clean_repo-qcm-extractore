"""Tests for the Step 3 metadata taxonomy helpers (modules/utils/metadata_context.py).

Validates the contract documented in STEP3_METADATA_ENRICHMENT_PLAN.md:
- load_taxonomy caches and returns the required keys
- normalize_module / normalize_year / normalize_faculty are case + accent tolerant
  and reject hallucinations to None
- derive_source applies the Externat/Residanat rule
- find_faculty_in_text scans page text for a valid faculty mention
- build_context_block renders a deterministic block containing all faculties + levels
"""
import os
import sys
from pathlib import Path

# Force UTF-8 on Windows (emojis in print statements crash cp1252 console)
sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.utils.metadata_context import (
    load_taxonomy, build_context_block,
    normalize_module, normalize_year, normalize_faculty,
    find_faculty_in_text, derive_source,
)


def _test_load_taxonomy():
    print("\n--- Test 1: load_taxonomy ---")
    t1 = load_taxonomy()
    assert isinstance(t1, dict), "taxonomy should be a dict"
    for k in ("system_instruction", "valid_faculties", "valid_modules", "rules"):
        assert k in t1, f"missing key: {k}"
    assert len(t1["valid_faculties"]) == 15, f"expected 15 faculties, got {len(t1['valid_faculties'])}"
    assert len(t1["valid_modules"]) == 6, f"expected 6 levels, got {len(t1['valid_modules'])}"
    # cached (same object identity)
    t2 = load_taxonomy()
    assert t1 is t2, "load_taxonomy should return the cached object"
    print("✅ load_taxonomy returns required keys and is cached.")


def _test_normalize_module():
    print("\n--- Test 2: normalize_module ---")
    assert normalize_module("Cardiologie") == "Cardiologie"
    assert normalize_module("cardiologie") == "Cardiologie"
    assert normalize_module("CARDIOLOGIE") == "Cardiologie"
    assert normalize_module("Neurologie") == "Neurologie"
    assert normalize_module("Pédiatrie") == "Pédiatrie"
    assert normalize_module("pediatrie") == "Pédiatrie"
    assert normalize_module("Anatomie Pathologique") == "Anatomie Pathologique"
    # hallucination rejected
    assert normalize_module("SGBD") is None
    assert normalize_module("Databases") is None
    assert normalize_module("") is None
    assert normalize_module(None) is None
    print("✅ normalize_module is case/accent tolerant and rejects hallucinations.")


def _test_normalize_year():
    print("\n--- Test 3: normalize_year ---")
    assert normalize_year("2025/2026") == "2025"
    assert normalize_year("2024/2025") == "2024"
    assert normalize_year("2024") == "2024"
    assert normalize_year("  2023/2024  ") == "2023"
    assert normalize_year(None) is None
    assert normalize_year("") is None
    print("✅ normalize_year uses the START year of a YYYY/YYYY pair.")


def _test_normalize_faculty():
    print("\n--- Test 4: normalize_faculty ---")
    assert normalize_faculty("Oran") == "Oran"
    assert normalize_faculty("oran") == "Oran"
    assert normalize_faculty("ORAN") == "Oran"
    assert normalize_faculty("Tlemcen") == "Tlemcen"
    assert normalize_faculty("TLEMCEN") == "Tlemcen"
    assert normalize_faculty("Sétif") == "Sétif"
    assert normalize_faculty("setif") == "Sétif"
    assert normalize_faculty("Béjaïa") == "Béjaïa"
    assert normalize_faculty("bejaia") == "Béjaïa"
    # hallucination rejected
    assert normalize_faculty("Paris") is None
    assert normalize_faculty(None) is None
    print("✅ normalize_faculty is case/accent tolerant and rejects unknown faculties.")


def _test_find_faculty_in_text():
    print("\n--- Test 5: find_faculty_in_text ---")
    assert find_faculty_in_text("Université de Tlemcen, Faculté de Médecine") == "Tlemcen"
    assert find_faculty_in_text("EXAMEN - Université d'Oran") == "Oran"
    assert find_faculty_in_text("Sétif, Algérie") == "Sétif"
    # accent-tolerant even when text is OCR-mangled
    assert find_faculty_in_text("Universite de Bejaia") == "Béjaïa"
    # no mention
    assert find_faculty_in_text("This is a plain medical exam text with no city") is None
    assert find_faculty_in_text("") is None
    print("✅ find_faculty_in_text scans text + is accent tolerant.")


def _test_derive_source():
    print("\n--- Test 6: derive_source ---")
    # Externat: module matched
    assert derive_source("Cardiologie", "Oran") == "Externat Oran"
    assert derive_source("Neurologie", "Tlemcen") == "Externat Tlemcen"
    # Residanat: no module
    assert derive_source(None, "Oran") == "Residanat Oran"
    # Residanat: is_residanat flag overrides even when module matched
    assert derive_source("Cardiologie", "Oran", is_residanat=True) == "Residanat Oran"
    # No faculty → no source derivable
    assert derive_source("Cardiologie", None) is None
    assert derive_source(None, None) is None
    print("✅ derive_source applies Externat/Residanat rule.")


def _test_build_context_block():
    print("\n--- Test 7: build_context_block ---")
    block = build_context_block()
    assert isinstance(block, str)
    tax = load_taxonomy()
    # all 15 faculties appear
    for f in tax["valid_faculties"]:
        assert f in block, f"faculty {f} missing from context block"
    # all 6 level labels appear
    for level in tax["valid_modules"]:
        assert level in block, f"level label {level} missing from context block"
    # all modules appear
    for level, modules in tax["valid_modules"].items():
        for m in modules:
            assert m in block, f"module {m} missing from context block"
    # year rule
    assert "2025/2026" in block
    # deterministic — second call returns the same string
    assert build_context_block() == block
    print("✅ build_context_block renders all faculties, levels, modules, rules; deterministic.")


def _run_all():
    _test_load_taxonomy()
    _test_normalize_module()
    _test_normalize_year()
    _test_normalize_faculty()
    _test_find_faculty_in_text()
    _test_derive_source()
    _test_build_context_block()
    print("\n" + "=" * 60)
    print("ALL metadata_context TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()