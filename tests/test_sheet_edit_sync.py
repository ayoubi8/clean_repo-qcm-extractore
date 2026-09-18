"""Sheet-edit → build-chain sync verification tests.

Covers the cloud_sync (sync-from-sheets) propagation contract:

S1  merge_qcm_fields: sheet-safe field merge
    - text edits applied
    - empty strings / None never overwrite
    - list values exported as repr strings ("['a', 'b']") parse back to lists
    - dict values (propositions) survive unparseable sheet strings
S2  propagate_sheet_edits: a Step 2 sheet edit reaches
    step5_json/merged_qcms.json (Step 6 direct input),
    step2_qcm/accepted/merged_qcms.json (UI mirror) and
    step3_metadata/accepted/*.json (build source), with merged_* excluded.
S3  Step 6 Phase 1: a re-run merges ALL fields from corrected_qcms.json
    (Correct + text edits from the sibling propagation), not just Correct,
    and force_overwrite still clears only the Correct column.
"""
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from modules.utils.qcm_merge import qcm_key, merge_qcm_fields, propagate_sheet_edits


def _write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _test_s1_merge_qcm_fields():
    print("\n--- S1: merge_qcm_fields sheet-safe merge ---")
    target = {
        "Num": 1,
        "Text": "old text",
        "Tag": ["Externat", "2024"],
        "Year": 2024,
        "propositions": {"a": "pa", "b": "pb"},
        "Correct": "",
    }
    # Sheet row: values are strings (xlsx round-trip)
    source = {
        "Num": "1",
        "Text": "edited text",
        "Tag": "['Externat', '2024']",      # repr of the same list → no change
        "Year": "2025",                      # int target, string value → applied
        "propositions": "not a dict repr",   # dict target, unparseable → skipped
        "Correct": "ABC",
        "Exp": "   ",                        # whitespace-only → never overwrites
    }
    changed = merge_qcm_fields(target, source)
    assert target["Text"] == "edited text", target
    assert target["Correct"] == "ABC", target
    assert target["Year"] == "2025", target
    assert target["Tag"] == ["Externat", "2024"], target       # list preserved
    assert target["propositions"] == {"a": "pa", "b": "pb"}, target  # dict preserved
    assert target.get("Exp", "") == ""
    assert changed == 3, changed  # Text, Year, Correct

    # Type-matching list edit parses back
    target2 = {"Tag": ["Externat", "2024"]}
    merge_qcm_fields(target2, {"Tag": "['Externat', '2025']"})
    assert target2["Tag"] == ["Externat", "2025"], target2
    print("OK S1 — merge is field-level and sheet-safe.")


def _test_s2_propagate_sheet_edits():
    print("\n--- S2: propagate_sheet_edits reaches the whole build chain ---")
    tmp = tempfile.mkdtemp()
    root = Path(tmp)

    merged = [{
        "Num": 1, "Cas": "CAS 1", "Text": "old merged text",
        "A": "pa", "B": "pb", "Correct": "",
        "Tag": ["Externat", "2024"], "Year": 2024, "Type": "QCS",
    }]
    _write_json(root / "step5_json" / "merged_qcms.json", merged)
    _write_json(root / "step2_qcm" / "accepted" / "merged_qcms.json", merged)

    # Step 3 accepted: raw uid-keyed format (this is what a Step 2 re-run
    # rebuilds step5 merged from)
    step3_qcm = {
        "uid": "1_1_0", "page": 1, "number": 1,
        "text": "old raw text", "cas": "CAS 1",
        "propositions": {"a": "pa", "b": "pb"},
    }
    _write_json(root / "step3_metadata" / "accepted" / "page_1.json", [step3_qcm])
    # mirrored merged file must be excluded
    _write_json(root / "step3_metadata" / "accepted" / "merged_qcms.json", merged)

    # Edited sheet rows as sync-from-sheets builds them (all values strings)
    edited_rows = [
        {  # step-2 sheet row (uid-keyed)
            "uid": "1_1_0", "page": "1", "number": "1",
            "text": "edited raw text", "cas": "CAS 1",
        },
        {  # step-5/6 format row (Num-keyed)
            "Num": "1", "Text": "edited merged text", "Correct": "AB",
            "Tag": "['Externat', '2024']", "Year": "2024",
        },
    ]

    buf = io.StringIO()
    with redirect_stdout(buf):
        result = propagate_sheet_edits(root, edited_rows)

    changed = set(result["changed"])
    assert "step5_json/merged_qcms.json" in changed, changed
    assert "step2_qcm/accepted/merged_qcms.json" in changed, changed
    assert "step3_metadata/accepted/page_1.json" in changed, changed
    assert not any("merged_qcms.json" in c and "step3" in c for c in changed), changed

    s5 = _read_json(root / "step5_json" / "merged_qcms.json")[0]
    assert s5["Text"] == "edited merged text", s5
    assert s5["Correct"] == "AB", s5
    assert s5["Tag"] == ["Externat", "2024"], s5        # structured value intact
    assert s5["Year"] == 2024, s5                      # equal → untouched (type preserved)
    assert s5["Cas"] == "CAS 1", s5

    mirror = _read_json(root / "step2_qcm" / "accepted" / "merged_qcms.json")[0]
    assert mirror["Text"] == "edited merged text", mirror

    s3 = _read_json(root / "step3_metadata" / "accepted" / "page_1.json")[0]
    assert s3["text"] == "edited raw text", s3
    assert s3["propositions"] == {"a": "pa", "b": "pb"}, s3  # dict intact

    # Idempotent: re-propagating the same rows changes nothing
    buf2 = io.StringIO()
    with redirect_stdout(buf2):
        result2 = propagate_sheet_edits(root, edited_rows)
    assert result2["changed"] == [], result2
    print(f"OK S2 — build chain synced: {sorted(changed)}")


class _Ctx:
    """Minimal ProjectContext stand-in over a temp dir."""

    def __init__(self, base: Path):
        self.base_path = base

    def get_path(self, step, sub=""):
        p = self.base_path / step / sub if sub else self.base_path / step
        if "." not in p.name:
            p.mkdir(parents=True, exist_ok=True)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
        return p


def _test_s3_step6_full_field_merge():
    print("\n--- S3: Step 6 Phase 1 merges all fields from corrected_qcms.json ---")
    from modules.step6_corrections import Step6Corrections
    from modules.utils.cost_tracker import CostTracker

    tmp = Path(tempfile.mkdtemp())
    ctx = _Ctx(tmp)

    # Stale Step 5 input (what Step 6 loads)
    _write_json(ctx.get_path("step5_json") / "merged_qcms.json", [{
        "Num": 1, "Cas": "CAS 1", "Text": "stale text",
        "A": "pa", "B": "pb", "Correct": "",
        "Tag": ["Externat", "2024"], "Year": 2024, "Type": "QCS",
    }])
    # corrected_qcms.json as sync-from-sheets left it: corrections + the
    # user's text edits propagated from the Step 2 sheet
    _write_json(ctx.get_path("step6_corrections") / "corrected_qcms.json", [{
        "Num": 1, "Cas": "CAS 1", "Text": "edited text",
        "A": "pa", "B": "pb", "Correct": "AB",
        "Tag": ["Externat", "2024"], "Year": 2024, "Type": "QCS",
    }])

    step6 = Step6Corrections(CostTracker(), project_context=ctx)
    with patch.object(Step6Corrections, "_manual_entry", lambda self, qcms: qcms):
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = step6.run(auto_mode=True, config={"source": "manual"})

    out_path = Path(result["file"])
    out = _read_json(out_path)[0]
    assert out["Text"] == "edited text", out          # sheet edit survived re-run
    assert out["Correct"] == "AB", out                # correction survived re-run
    assert out["Tag"] == ["Externat", "2024"], out    # structured value intact
    out_log = buf.getvalue()
    assert "synced edit(s) from Google Sheets" in out_log, out_log
    print("OK S3a — re-run keeps corrections + sheet edits.")

    # force_overwrite: Correct cleared for re-extraction, text edits kept
    _write_json(ctx.get_path("step6_corrections") / "corrected_qcms.json", [{
        "Num": 1, "Cas": "CAS 1", "Text": "edited text",
        "A": "pa", "B": "pb", "Correct": "AB",
        "Tag": ["Externat", "2024"], "Year": 2024, "Type": "QCS",
    }])
    step6b = Step6Corrections(CostTracker(), project_context=ctx)
    with patch.object(Step6Corrections, "_manual_entry", lambda self, qcms: qcms):
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = step6b.run(
                auto_mode=True,
                config={"source": "manual", "force_overwrite": True})
    out = _read_json(Path(result["file"]))[0]
    assert out.get("Correct", "") == "", out           # Correct re-extracted
    assert out["Text"] == "edited text", out           # user text edit kept
    print("OK S3b — force_overwrite clears only Correct, edits kept.")


def _test_s4_key_compat():
    print("\n--- S4: qcm_key covers uid / Num / number variants ---")
    assert qcm_key({"uid": "1_1_0"}) == "1_1_0"
    assert qcm_key({"Num": 7}) == "7"
    assert qcm_key({"number": 3}) == "3"
    assert qcm_key({}) == ""
    assert qcm_key("not-a-dict") == ""
    print("OK S4 — key normalization consistent with sync-from-sheets.")


if __name__ == "__main__":
    _test_s1_merge_qcm_fields()
    _test_s2_propagate_sheet_edits()
    _test_s3_step6_full_field_merge()
    _test_s4_key_compat()
    print("\nALL SHEET-EDIT SYNC TESTS PASSED ✅")
