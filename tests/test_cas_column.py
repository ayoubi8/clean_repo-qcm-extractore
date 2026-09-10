"""Tests for Phase 4 Cas column split (modules/cas_text_split.py), its cascade
wiring, and the Step 8 Cas column.

Covers the Phase 4 contract (antigravity_redo_phases.md):
- Clinical-case narrative is removed from question text (exact + whitespace
  variant), while `cas`/`Cas` keeps it intact
- Standalone QCMs (no cas / narrative absent) are never touched
- Orphaned "CAS CLINIQUE n" header lines are dropped with the narrative
- Safety: text is never emptied and tiny narratives are never scrubbed
- Idempotent re-run (second run is a no-op)
- Cascade: split runs BEFORE Step 3, unconditionally (even with the
  clinical_case strategy skipped, legacy cas data is still split)
- Merged output: Cas holds the narrative, Text does not
- Step 8 custom export carries a dedicated Cas column after Question
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
from modules.cas_text_split import run_cas_text_split, split_cas_from_text
from modules.post_step2_metadata import run_post_step2_metadata, DEFAULT_STEP3_CONFIG

NARR = "Patient A, 45 ans, fievre aigue et douleur intense."
CAS = f"CAS CLINIQUE 1\r\n{NARR}"


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
# Pure-function tests
# ─────────────────────────────────────────────────────────────────────────────

def _test_exact_removal_keeps_cas():
    print("\n--- Test 1: exact narrative removed, cas intact ---")
    text = f"CAS CLINIQUE 1\r\n{NARR}\nQ1: Quel diagnostic ?"
    new_text, removed = split_cas_from_text(text, CAS)
    assert removed is True
    assert new_text == "Q1: Quel diagnostic ?", f"got: {new_text!r}"
    assert NARR not in new_text
    print(f"✅ scrubbed -> {new_text!r}.")


def _test_whitespace_variant_removal():
    print("\n--- Test 2: whitespace-variant narrative removed ---")
    text = "CAS CLINIQUE 1\nPatient A, 45 ans,\nfievre aigue et douleur intense.\nQ1: Quel diagnostic ?"
    cas = "CAS CLINIQUE 1\r\nPatient A,  45 ans, fievre aigue et   douleur intense."
    new_text, removed = split_cas_from_text(text, cas)
    assert removed is True, "normalized fallback must find the narrative"
    assert new_text == "Q1: Quel diagnostic ?", f"got: {new_text!r}"
    print(f"✅ normalized match -> {new_text!r}.")


def _test_standalone_untouched():
    print("\n--- Test 3: standalone QCMs never touched ---")
    # No cas at all
    new_text, removed = split_cas_from_text("Q2: Question standalone ?", None)
    assert (new_text, removed) == ("Q2: Question standalone ?", False)
    # Cas present but its narrative is nowhere in the text
    new_text, removed = split_cas_from_text("Q3: Autre question ?", CAS)
    assert (new_text, removed) == ("Q3: Autre question ?", False)
    print("✅ no cas / narrative absent -> untouched.")


def _test_orphan_label_dropped():
    print("\n--- Test 4: orphaned header line dropped with the narrative ---")
    text = f"CAS CLINIQUE 1 :\n{NARR}\n\nQ1: Diagnostic ?"
    new_text, removed = split_cas_from_text(text, CAS)
    assert removed is True
    assert new_text == "Q1: Diagnostic ?", f"got: {new_text!r}"
    print("✅ header + narrative gone, question kept.")


def _test_never_empties_and_short_guard():
    print("\n--- Test 5: safety — never empty text, never scrub tiny strings ---")
    # Text that IS the narrative -> keep original (must not empty out)
    new_text, removed = split_cas_from_text(NARR, CAS)
    assert (new_text, removed) == (NARR, False)
    # Tiny narrative could false-positive inside longer questions -> skipped
    new_text, removed = split_cas_from_text(
        "Q1: Short mention here ?", "CAS CLINIQUE\r\nShort.")
    assert removed is False
    print("✅ would-empty and short-narrative cases kept intact.")


# ─────────────────────────────────────────────────────────────────────────────
# Runner end-to-end (no LLM — hermetic)
# ─────────────────────────────────────────────────────────────────────────────

def _test_runner_splits_and_preserves_cas():
    print("\n--- Test 6: runner scrubs text, preserves cas ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        ctx = FakeContext(tmp)
        _seed_step2(ctx, "all_qcms.json", [
            {"uid": "1_1_0", "page": 1, "number": 1,
             "text": f"CAS CLINIQUE 1\r\n{NARR}\nQ1: Quel diagnostic ?",
             "cas": CAS,
             "propositions": {"a": "pa", "e": "pe"}},
            {"uid": "1_1_1", "page": 1, "number": 2, "text": "Q2: Standalone ?",
             "propositions": {"a": "pa"}},
        ])
        res = run_cas_text_split(ctx)
        assert res["status"] == "ok", res
        assert res["stats"] == {"qcms_scanned": 2, "qcms_with_cas": 1,
                                "qcms_scrubbed": 1}, res["stats"]

        data = _read_step2(ctx, "all_qcms.json")
        assert data[0]["text"] == "Q1: Quel diagnostic ?"
        assert data[0]["cas"] == CAS, "cas must stay intact"
        assert data[1]["text"] == "Q2: Standalone ?"
        assert "hint" not in data[0], "split must not touch unrelated keys"
        print("✅ text scrubbed, cas intact, standalone untouched.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_idempotent_rerun():
    print("\n--- Test 7: re-run over split data is a no-op ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        ctx = FakeContext(tmp)
        _seed_step2(ctx, "all_qcms.json", [
            {"uid": "1_1_0", "page": 1, "number": 1,
             "text": f"{NARR}\nQ1: Quel diagnostic ?", "cas": CAS},
        ])
        first = run_cas_text_split(ctx)
        assert first["status"] == "ok"
        before = (ctx.get_path("step2_qcm", "accepted") / "all_qcms.json").read_text(encoding="utf-8")
        second = run_cas_text_split(ctx)
        assert second["status"] == "ok"
        assert second["stats"]["qcms_scrubbed"] == 0
        after = (ctx.get_path("step2_qcm", "accepted") / "all_qcms.json").read_text(encoding="utf-8")
        assert before == after
        print("✅ idempotent: second run changes nothing.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
# Cascade wiring
# ─────────────────────────────────────────────────────────────────────────────

def _test_cascade_runs_split_before_step3_unconditionally():
    print("\n--- Test 8: split runs BEFORE Step 3, even with strategy=skip ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        ctx = FakeContext(tmp)
        _seed_step2(ctx, "all_qcms.json", [
            {"uid": "1_1_0", "page": 1, "number": 1,
             "text": f"CAS CLINIQUE 1\r\n{NARR}\nQ1: Quel diagnostic ?",
             "cas": CAS,
             "propositions": {"a": "pa", "e": "pe"}},
        ])
        # clinical_case=skip: proves the split is keyed on data, not strategy
        cfg = json.loads(json.dumps(DEFAULT_STEP3_CONFIG))
        cfg["fields"]["clinical_case"]["strategy"] = "skip"

        seen_by_step3 = {}

        def fake_step3_run(auto_mode=False, config=None, global_pages=None, **kw):
            data = _read_step2(ctx, "all_qcms.json")
            seen_by_step3["text"] = data[0]["text"]
            seen_by_step3["cas"] = data[0].get("cas")
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
            res = run_post_step2_metadata(CostTracker(), ctx, "u", "p", cfg)

        assert res["status"] == "ok", res
        assert res["cas_split"]["status"] == "ok", res
        assert seen_by_step3["text"] == "Q1: Quel diagnostic ?", \
            "Step 3 must see narrative-free text"
        assert seen_by_step3["cas"] == CAS, "Step 3 must still see intact cas"
        assert build_called["n"] == 1
        print("✅ split ran first + unconditionally; Step 3 saw clean Text, intact cas.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_split_soft_fail_never_blocks_build():
    print("\n--- Test 9: split failure soft-fails, build still chains ---")
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
             patch("modules.post_step2_metadata.run_cas_text_split",
                   side_effect=RuntimeError("split boom")), \
             patch("modules.post_step2_metadata.run_post_step3_build", side_effect=fake_build):
            MockSM.return_value.run = fake_step3_run
            res = run_post_step2_metadata(CostTracker(), ctx, "u", "p",
                                          json.loads(json.dumps(DEFAULT_STEP3_CONFIG)))

        assert res["status"] == "ok", "split failure must NOT fail the cascade"
        assert res["cas_split"]["status"] == "error"
        assert build_called["n"] == 1
        print("✅ split exception -> soft-fail, build chained.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
# Merged output + Step 8 export
# ─────────────────────────────────────────────────────────────────────────────

def _test_merged_cas_column_text_clean():
    print("\n--- Test 10: merged output — Cas holds narrative, Text does not ---")
    from modules.utils.project_context import ProjectContext
    from modules.post_step3_build import run_post_step3_build

    ctx = ProjectContext("test-cas-split-merged")
    accepted = ctx.get_path("step3_metadata", "accepted")
    for p in accepted.glob("*.json"):
        p.unlink()
    (accepted / "qcms_1.json").write_text(json.dumps([
        {"uid": "1_1_0", "page": 1, "number": 1,
         "text": "Q1: Quel diagnostic ?",
         "cas": CAS,
         "propositions": {"a": "pa", "b": "pb", "c": "pc", "d": "pd", "e": "pe"}},
    ]), encoding="utf-8")

    res = run_post_step3_build(CostTracker(), ctx)
    assert res.get("status") == "ok", f"Expected ok, got: {res}"

    merged = json.loads((ctx.get_path("step5_json", "merged_qcms.json")).read_text(encoding="utf-8"))
    assert merged[0]["Cas"] == CAS, f"Cas must hold the full case: {merged[0].get('Cas')!r}"
    assert NARR not in (merged[0]["Text"] or ""), "narrative must NOT be in Text"
    assert merged[0]["Text"] == "Q1: Quel diagnostic ?"
    print("✅ merged: Cas=narrative, Text=question only.")


def _test_step8_custom_export_has_cas_column():
    print("\n--- Test 11: Step 8 custom export carries dedicated Cas column ---")
    from modules.step8_matcher import Step8Matcher
    from modules.utils.cost_tracker import CostTracker as CT
    import openpyxl

    matcher = Step8Matcher(CT())
    assert "Cas" in Step8Matcher._slim({"Num": 1, "Text": "Q?", "Cas": CAS}), \
        "_slim records must keep Cas"

    tmp = Path(tempfile.mkdtemp())
    try:
        out = tmp / "custom_test.xlsx"
        matcher._save_custom_xlsx([{
            "qcm_id": "Q1",
            "source_qcm_full": {"Num": 1, "Text": "Q1: Quel diagnostic ?", "Cas": CAS,
                                "A": "pa", "Correct": "A"},
            "best_match": {"similarity": 0.95,
                           "ref_qcm": {"Num": 7, "Text": "Ref Q?", "Correct": "A", "Year": 2020}},
        }], out)
        assert out.exists(), "custom xlsx must be written"

        wb = openpyxl.load_workbook(out, read_only=True)
        headers = [c.value for c in next(wb.active.rows)]
        assert headers[2] == "Question" and headers[3] == "Cas", \
            f"Cas must sit right after Question: {headers}"
        row = [c.value for c in list(wb.active.rows)[1]]
        assert row[2] == "Q1: Quel diagnostic ?"
        assert row[3] == CAS, "Cas cell must hold the full case text"
        print(f"✅ custom export headers: {headers[:6]}...; Cas cell populated.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_all():
    _test_exact_removal_keeps_cas()
    _test_whitespace_variant_removal()
    _test_standalone_untouched()
    _test_orphan_label_dropped()
    _test_never_empties_and_short_guard()
    _test_runner_splits_and_preserves_cas()
    _test_idempotent_rerun()
    _test_cascade_runs_split_before_step3_unconditionally()
    _test_split_soft_fail_never_blocks_build()
    _test_merged_cas_column_text_clean()
    _test_step8_custom_export_has_cas_column()

    print("\n" + "=" * 60)
    print("ALL cas_column TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()
