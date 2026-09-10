"""Tests for Phase 3 Hint Detection (modules/hint_detector.py) and its wiring.

Covers the Phase 3 contract (antigravity_redo_phases.md):
- Spec example block -> exactly ["ABC", "ACD", "BCD", "CDE", "BDE"]
- Normalized combos (sorted + deduped): B(2+1) -> "AB"
- No hint block -> hint: [] and untouched text
- Hard constraint: raw hint lines are scrubbed out of proposition text
- Mid-field lookalikes and out-of-range digits are NOT hint lines
- Idempotent re-run (second run is a no-op)
- Cascade order: hint stage runs BEFORE Step 3 (fake Step 3 observes
  already-scrubbed propositions + hint arrays)
- Merged output: Step 5 maps hint -> Hint; XLSX column order puts Hint
  immediately after proposition E
"""
import os
import sys
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

# Force UTF-8 on Windows
sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))

from modules.utils.cost_tracker import CostTracker
from modules.hint_detector import (
    run_hint_detection,
    parse_qcm_hints,
    _parse_hint_line,
    _split_trailing_hints,
)
from modules.post_step2_metadata import run_post_step2_metadata, DEFAULT_STEP3_CONFIG

SPEC_BLOCK = "A(1+2+3)\nB(1+3+4)\nC(2+3+4)\nD(3+4+5)\nE(2+4+5)"
SPEC_EXPECTED = ["ABC", "ACD", "BCD", "CDE", "BDE"]


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


def _seed_step2(ctx: FakeContext, filename: str, qcms: list):
    d = ctx.get_path("step2_qcm", "accepted")
    (d / filename).write_text(json.dumps(qcms), encoding="utf-8")


def _read_step2(ctx: FakeContext, filename: str):
    return json.loads((ctx.get_path("step2_qcm", "accepted") / filename).read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────────────────────
# Pure-parser tests
# ─────────────────────────────────────────────────────────────────────────────

def _test_spec_example_exact():
    print("\n--- Test 1: spec example block -> exact expected array ---")
    qcm = {"uid": "1_1_0", "page": 1, "number": 1, "text": "Q1?",
           "propositions": {"a": "pa", "b": "pb", "c": "pc", "d": "pd",
                            "e": "pe\n" + SPEC_BLOCK}}
    combos, cleaned = parse_qcm_hints(qcm)
    assert combos == SPEC_EXPECTED, f"expected {SPEC_EXPECTED}, got {combos}"
    assert ("propositions", "e") in cleaned
    assert "A(1+2+3)" not in cleaned[("propositions", "e")]
    assert cleaned[("propositions", "e")] == "pe"
    print(f"✅ spec block -> {combos}, prop E scrubbed to 'pe'.")


def _test_normalized_edges():
    print("\n--- Test 2: normalized combos (sorted + deduped) ---")
    assert _parse_hint_line("B(2+1)") == "AB"
    assert _parse_hint_line("A(1+1+2)") == "AB"
    assert _parse_hint_line("E(5+4+3+2+1)") == "ABCDE"
    assert _parse_hint_line("C( 3 + 1 )") == "AC"
    print("✅ out-of-order/dup/whitespace combos normalized.")


def _test_no_hint_untouched():
    print("\n--- Test 3: no hint block -> hint [] and untouched text ---")
    qcm = {"uid": "1_1_0", "page": 1, "number": 1, "text": "Q1?",
           "propositions": {"a": "pa", "b": "pb", "c": "pc", "d": "pd", "e": "pe"}}
    combos, cleaned = parse_qcm_hints(qcm)
    assert combos == []
    assert cleaned == {}
    print("✅ plain QCM untouched.")


def _test_midtext_lookalike_kept():
    print("\n--- Test 4: mid-field lookalike is NOT a hint block ---")
    qcm = {"uid": "1_1_0", "page": 1, "number": 1, "text": "Q1?",
           "propositions": {"a": "pa", "e": "see B(1+3) above for details\npe tail"}}
    combos, cleaned = parse_qcm_hints(qcm)
    assert combos == []
    assert cleaned == {}, "non-trailing hint-like line must be left alone"
    print("✅ mid-field lookalike preserved.")


def _test_out_of_range_ignored():
    print("\n--- Test 5: out-of-range digits are NOT hint lines ---")
    assert _parse_hint_line("A(1+6)") is None
    assert _parse_hint_line("A(0+2)") is None
    assert _parse_hint_line("A(1+12)") is None
    assert _parse_hint_line("see A(1+2)") is None
    qcm = {"uid": "1_1_0", "page": 1, "number": 1, "text": "Q1?",
           "propositions": {"e": "pe\nA(1+6)"}}
    combos, cleaned = parse_qcm_hints(qcm)
    assert combos == [] and cleaned == {}
    print("✅ invalid lines ignored (and block the trailing run).")


# ─────────────────────────────────────────────────────────────────────────────
# Runner end-to-end (no LLM — hermetic)
# ─────────────────────────────────────────────────────────────────────────────

def _test_runner_scrub_and_hint_fields():
    print("\n--- Test 6: runner scrubs props, stamps hint, hard constraint holds ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        ctx = FakeContext(tmp)
        _seed_step2(ctx, "all_qcms.json", [
            {"uid": "1_1_0", "page": 1, "number": 1, "text": "Q1?",
             "propositions": {"a": "pa", "e": "pe text\n" + SPEC_BLOCK}},
            {"uid": "1_1_1", "page": 1, "number": 2, "text": "Q2?",
             "propositions": {"a": "pa", "e": "plain e"}},
        ])
        res = run_hint_detection(ctx)
        assert res["status"] == "ok", res
        assert res["stats"]["qcms_with_hints"] == 1
        assert res["stats"]["combos_total"] == 5

        data = _read_step2(ctx, "all_qcms.json")
        assert data[0]["hint"] == SPEC_EXPECTED
        assert data[1]["hint"] == []
        # Hard constraint: raw hint text must not survive in ANY proposition
        for q in data:
            for v in (q.get("propositions") or {}).values():
                assert "A(1+2+3)" not in (v or ""), "raw hint leaked into propositions"
                assert "B(1+3+4)" not in (v or "")
        assert data[0]["propositions"]["e"] == "pe text"
        print("✅ scrubbed + stamped; raw hint text nowhere in propositions.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_idempotent_rerun():
    print("\n--- Test 7: re-run over parsed data is a no-op ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        ctx = FakeContext(tmp)
        _seed_step2(ctx, "all_qcms.json", [
            {"uid": "1_1_0", "page": 1, "number": 1, "text": "Q1?",
             "propositions": {"e": "pe\n" + SPEC_BLOCK}},
        ])
        first = run_hint_detection(ctx)
        assert first["status"] == "ok"
        before = (ctx.get_path("step2_qcm", "accepted") / "all_qcms.json").read_text(encoding="utf-8")
        second = run_hint_detection(ctx)
        assert second["status"] == "ok"
        assert second["stats"]["fields_scrubbed"] == 0
        after = (ctx.get_path("step2_qcm", "accepted") / "all_qcms.json").read_text(encoding="utf-8")
        assert before == after, "second run must not rewrite anything"
        assert json.loads(after)[0]["hint"] == SPEC_EXPECTED
        print("✅ idempotent: second run changes nothing.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
# Cascade wiring
# ─────────────────────────────────────────────────────────────────────────────

def _step3_config_no_cc() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_STEP3_CONFIG))
    cfg["fields"]["clinical_case"]["strategy"] = "skip"  # keep test focused on hint
    return cfg


def _test_cascade_runs_hint_before_step3():
    print("\n--- Test 8: hint stage runs BEFORE Step 3 in the cascade ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        ctx = FakeContext(tmp)
        _seed_step2(ctx, "all_qcms.json", [
            {"uid": "1_1_0", "page": 1, "number": 1, "text": "Q1?",
             "propositions": {"a": "pa", "e": "pe\n" + SPEC_BLOCK}},
        ])

        seen_by_step3 = {}

        def fake_step3_run(auto_mode=False, config=None, global_pages=None, **kw):
            # Step 3 reads Step 2 output — assert it already sees scrubbed
            # propositions + hint arrays (i.e. hint ran first).
            data = _read_step2(ctx, "all_qcms.json")
            seen_by_step3["prop_e"] = data[0]["propositions"]["e"]
            seen_by_step3["hint"] = data[0].get("hint")
            d = ctx.get_path("step3_metadata", "accepted")
            (d / "page_1.json").write_text(json.dumps(data), encoding="utf-8")
            return {"config": config, "global_values": {}}

        build_called = {"n": 0}

        def fake_build(*a, **kw):
            build_called["n"] += 1
            return {"status": "ok", "step5": {"total_qcms": 1}}

        with patch("modules.post_step2_metadata.Step3Metadata") as MockSM, \
             patch("modules.post_step2_metadata.run_post_step3_build", side_effect=fake_build):
            MockSM.return_value.run = fake_step3_run
            res = run_post_step2_metadata(CostTracker(), ctx, "u", "p", _step3_config_no_cc())

        assert res["status"] == "ok", res
        assert res["hint"]["status"] == "ok", res
        assert res["hint"]["stats"]["qcms_with_hints"] == 1
        assert seen_by_step3["prop_e"] == "pe", "Step 3 must see scrubbed prop E"
        assert seen_by_step3["hint"] == SPEC_EXPECTED, "Step 3 must see hint arrays"
        assert build_called["n"] == 1
        print("✅ hint ran first: Step 3 observed scrubbed props + hint; build chained.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_hint_soft_fail_never_blocks_build():
    print("\n--- Test 9: hint failure soft-fails, build still chains ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        ctx = FakeContext(tmp)
        _seed_step2(ctx, "all_qcms.json", [{"uid": "1_1_0", "text": "Q1"}])

        build_called = {"n": 0}

        def fake_build(*a, **kw):
            build_called["n"] += 1
            return {"status": "ok", "step5": {"total_qcms": 1}}

        def fake_step3_run(auto_mode=False, config=None, global_pages=None, **kw):
            d = ctx.get_path("step3_metadata", "accepted")
            (d / "page_1.json").write_text(json.dumps([{"uid": "1_1_0", "text": "Q1"}]),
                                           encoding="utf-8")
            return {"config": config, "global_values": {}}

        with patch("modules.post_step2_metadata.Step3Metadata") as MockSM, \
             patch("modules.post_step2_metadata.run_hint_detection",
                   side_effect=RuntimeError("hint boom")), \
             patch("modules.post_step2_metadata.run_post_step3_build", side_effect=fake_build):
            MockSM.return_value.run = fake_step3_run
            res = run_post_step2_metadata(CostTracker(), ctx, "u", "p", _step3_config_no_cc())

        assert res["status"] == "ok", "hint failure must NOT fail the cascade"
        assert res["hint"]["status"] == "error"
        assert build_called["n"] == 1
        print("✅ hint exception -> soft-fail, build chained.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
# Merged output + XLSX column placement
# ─────────────────────────────────────────────────────────────────────────────

def _test_merged_hint_column_after_e():
    print("\n--- Test 10: merged output maps hint->Hint; XLSX puts Hint after E ---")
    from modules.utils.project_context import ProjectContext
    from modules.post_step3_build import run_post_step3_build
    from modules.utils.xlsx_exporter import _build_columns

    ctx = ProjectContext("test-hint-merged")
    tracker = CostTracker()
    accepted = ctx.get_path("step3_metadata", "accepted")
    for p in accepted.glob("*.json"):
        p.unlink()
    (accepted / "qcms_1.json").write_text(json.dumps([
        {"uid": "1_1_0", "page": 1, "number": 1, "text": "Q1?",
         "propositions": {"a": "pa", "b": "pb", "c": "pc", "d": "pd", "e": "pe"},
         "hint": SPEC_EXPECTED},
        {"uid": "1_1_1", "page": 1, "number": 2, "text": "Q2?",
         "propositions": {"a": "pa"},
         "hint": []},
    ]), encoding="utf-8")

    res = run_post_step3_build(tracker, ctx)
    assert res.get("status") == "ok", f"Expected ok, got: {res}"

    merged = json.loads((ctx.get_path("step5_json", "merged_qcms.json")).read_text(encoding="utf-8"))
    assert merged[0]["Hint"] == SPEC_EXPECTED, f"merged Hint wrong: {merged[0].get('Hint')}"
    # Empty hint arrays must NOT materialize as [] in merged output
    # (field-mapper skips empty values -> template default None kept).
    assert merged[1]["Hint"] is None

    cols = _build_columns(merged)
    assert "Hint" in cols, f"Hint column missing: {cols}"
    assert cols.index("Hint") == cols.index("E") + 1, \
        f"Hint must sit immediately after E: {cols}"
    print(f"✅ merged Hint mapped; XLSX column order: ...E, Hint, Correct... ({cols})")


def _run_all():
    _test_spec_example_exact()
    _test_normalized_edges()
    _test_no_hint_untouched()
    _test_midtext_lookalike_kept()
    _test_out_of_range_ignored()
    _test_runner_scrub_and_hint_fields()
    _test_idempotent_rerun()
    _test_cascade_runs_hint_before_step3()
    _test_hint_soft_fail_never_blocks_build()
    _test_merged_hint_column_after_e()

    print("\n" + "=" * 60)
    print("ALL hint_detector TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()
