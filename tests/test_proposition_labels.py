"""Tests for Phase 5 — dual proposition labeling (A-E and 1-5).

Covers the Phase 5 contract (antigravity_redo_phases.md):
- The Step 2 extraction prompt teaches BOTH labeling styles with the exact
  mapping a=1, b=2, c=3, d=4, e=5 ("1" and "A" both go to the "a" column)
- Deterministic enforcement at the save boundary: numeric (1-5) and
  uppercase (A-E) proposition keys are normalized onto canonical a-e,
  values preserved, unknown keys passed through (no data loss)
- Numeric-keyed LLM output flows through the real extraction path
  (prompt -> mock LLM -> parse -> _save_batch_results_accumulate) and lands
  in all_qcms.json keyed a-e
- Healed propositions map into the A-E template columns via Step 5
"""
import os
import sys
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Force UTF-8 on Windows
sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))

from modules.utils.cost_tracker import CostTracker
from modules.step2_qcm_extract_batch import Step2QCMExtractBatch


class FakeContext:
    """Minimal ProjectContext stand-in backed by a temp directory."""

    def __init__(self, base: Path):
        self.base_path = base
        self.name = "testproj"

    def get_path(self, step: str, sub: str = "") -> Path:
        p = self.base_path / step
        if sub:
            p = p / sub
        p.mkdir(parents=True, exist_ok=True)
        return p


# ─────────────────────────────────────────────────────────────────────────────
# Normalizer unit tests
# ─────────────────────────────────────────────────────────────────────────────

def _test_numeric_keys_route_to_letters():
    print("\n--- Test 1: 1-5 keys route onto a-e columns ---")
    props = {"1": "p1", "2": "p2", "3": "p3", "4": "p4", "5": "p5"}
    out = Step2QCMExtractBatch._normalize_proposition_keys(props)
    assert out == {"a": "p1", "b": "p2", "c": "p3", "d": "p4", "e": "p5"}, out
    assert list(out.keys()) == ["a", "b", "c", "d", "e"], "canonical order"
    print(f"✅ numeric -> {out}")


def _test_uppercase_keys_route_to_lowercase():
    print("\n--- Test 2: A-E keys route onto a-e columns ---")
    out = Step2QCMExtractBatch._normalize_proposition_keys({"A": "x", "B": "y", "E": "z"})
    assert out == {"a": "x", "b": "y", "e": "z"}, out
    print(f"✅ uppercase -> {out}")


def _test_collision_letter_wins():
    print("\n--- Test 3: canonical letter wins on collision ---")
    out = Step2QCMExtractBatch._normalize_proposition_keys({"1": "num", "a": "let"})
    assert out == {"a": "let"}, out
    out = Step2QCMExtractBatch._normalize_proposition_keys({"A": "up", "a": "low"})
    assert out == {"a": "low"}, out
    print("✅ existing lowercase key beats numeric/uppercase equivalent.")


def _test_unknown_keys_passthrough():
    print("\n--- Test 4: unknown keys pass through (no data loss) ---")
    out = Step2QCMExtractBatch._normalize_proposition_keys(
        {"a": "pa", "f": "pf", "6": "p6", "note": "n"})
    assert out["f"] == "pf" and out["6"] == "p6" and out["note"] == "n"
    assert out["a"] == "pa"
    assert Step2QCMExtractBatch._normalize_proposition_keys(None) is None
    assert Step2QCMExtractBatch._normalize_proposition_keys("text") == "text"
    print("✅ f/6/note kept; non-dict passes through.")


def _test_sanitize_heals_numeric_props():
    print("\n--- Test 5: _sanitize_qcms heals numeric-keyed QCMs ---")
    st = Step2QCMExtractBatch(CostTracker())
    qcms = [{"page": 1, "number": 1, "text": "Q1?",
             "propositions": {"1": "p1", "2": "p2", "3": "p3", "4": "p4", "5": "p5"}}]
    healed = st._sanitize_qcms(qcms)
    assert set(healed[0]["propositions"].keys()) == {"a", "b", "c", "d", "e"}
    assert healed[0]["propositions"]["a"] == "p1"
    assert healed[0]["propositions"]["e"] == "p5"
    print("✅ sanitize boundary normalizes proposition keys.")


# ─────────────────────────────────────────────────────────────────────────────
# Real extraction path (mocked LLM): prompt content + end-to-end healing
# ─────────────────────────────────────────────────────────────────────────────

FAKE_NUMERIC_RESPONSE = json.dumps([
    {"page": 1, "number": 1, "text": "Q1 numeric labeled?",
     "propositions": {"1": "Premiere", "2": "Deuxieme", "3": "Troisieme",
                      "4": "Quatrieme", "5": "Cinquieme"}},
    {"page": 1, "number": 2, "text": "Q2 letter labeled?",
     "propositions": {"a": "alpha", "b": "beta", "c": "gamma"}},
], ensure_ascii=False)


def _test_prompt_teaches_both_styles():
    print("\n--- Test 6: prompt teaches BOTH A-E and 1-5 with exact mapping ---")
    captured = {}

    def fake_generate(prompt, model=None, max_tokens=None, **kw):
        captured["prompt"] = prompt
        return {"content": FAKE_NUMERIC_RESPONSE, "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "cost": 0.0}

    st = Step2QCMExtractBatch(CostTracker())
    st.client = MagicMock()
    st.client.generate_completion = MagicMock(side_effect=fake_generate)
    st.client.estimate_cost = MagicMock(return_value=0.0)

    result = st._extract_all_qcms_batch("=== PAGE 1 ===\nQ1...", 1, 1)
    assert len(result) == 2, f"expected 2 QCMs, got {len(result)}"

    p = captured["prompt"]
    assert "NUMBERS (1, 2, 3, 4, 5)" in p, "prompt must mention numeric labeling"
    assert "a=1, b=2, c=3, d=4, e=5" in p, "prompt must teach the exact mapping"
    assert '"1" and label "A" both go to the "a" field' in p, "prompt must route 1 and A to a"
    assert 'keyed "a"-"e"' in p, "output format must demand a-e keys"
    assert "Never invent a \"1\"-\"5\" key" in p
    print("✅ prompt carries the dual-labeling rule + mapping + output note.")


def _test_end_to_end_numeric_extraction_healed():
    print("\n--- Test 7: numeric-keyed LLM output lands in all_qcms.json as a-e ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        ctx = FakeContext(tmp)
        st = Step2QCMExtractBatch(CostTracker(), project_context=ctx)
        st.client = MagicMock()
        st.client.generate_completion = MagicMock(
            return_value={"content": FAKE_NUMERIC_RESPONSE,
                          "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                          "cost": 0.0})
        st.client.estimate_cost = MagicMock(return_value=0.0)

        extracted = st._extract_all_qcms_batch("=== PAGE 1 ===\nQ1...", 1, 1)
        assert len(extracted) == 2
        st._save_batch_results_accumulate(extracted)

        saved = json.loads((ctx.get_path("step2_qcm", "accepted") / "all_qcms.json")
                           .read_text(encoding="utf-8"))
        q1, q2 = saved[0], saved[1]
        # Numeric-labeled QCM healed onto a-e, values preserved
        assert list(q1["propositions"].keys()) == ["a", "b", "c", "d", "e"]
        assert q1["propositions"]["a"] == "Premiere"
        assert q1["propositions"]["e"] == "Cinquieme"
        # Letter-labeled QCM unchanged
        assert q2["propositions"] == {"a": "alpha", "b": "beta", "c": "gamma"}
        print("✅ end-to-end: numeric output normalized at the save boundary.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_healed_props_map_to_template_columns():
    print("\n--- Test 8: healed propositions fill A-E template columns ---")
    from modules.step5_builder import Step5Builder

    builder = Step5Builder(CostTracker())
    template = {"Num": 0, "Text": "...", "A": "Option A", "B": "Option B",
                "C": "Option C", "D": "Option D", "E": "Option E"}
    qcm = {"number": 1, "text": "Q1?",
           "propositions": {"a": "Premiere", "b": "Deuxieme", "c": "Troisieme",
                            "d": "Quatrieme", "e": "Cinquieme"}}
    mapped = builder._map_to_template(qcm, template)
    assert mapped["A"] == "Premiere" and mapped["E"] == "Cinquieme", mapped
    print("✅ Step 5 maps healed a-e props into A-E columns.")


def _run_all():
    _test_numeric_keys_route_to_letters()
    _test_uppercase_keys_route_to_lowercase()
    _test_collision_letter_wins()
    _test_unknown_keys_passthrough()
    _test_sanitize_heals_numeric_props()
    _test_prompt_teaches_both_styles()
    _test_end_to_end_numeric_extraction_healed()
    _test_healed_props_map_to_template_columns()

    print("\n" + "=" * 60)
    print("ALL proposition_labels TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()
