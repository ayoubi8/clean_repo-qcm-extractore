"""Tests for Step8Matcher tag-merge & auto-dedup phase (PR-S8-1).

Covers the contract in STEP8_TAG_MERGE_PLAN.md §2:
- _produce_merge_outputs emits 3 new artifacts:
    <ref_name>_UPDATED.xlsx  (reference DB after merges + duplicate-row removal)
    merge_report.json        (audit log of every merge)
    unmerged_qcms.xlsx       (source QCMs not merged, skipped in self-scan)
- Auto-merge only fires for similarity >= auto_merge_floor (default 0.97)
- Self-scan filters self-row matches and produces no unmerged file
- _produce_merge_outputs MUST NOT call input()
"""
import builtins
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))


class FakeCtx:
    def __init__(self, base: Path):
        self.base_path = base
        self.name = "testproj"


def _make_matcher(floor: float = 0.97, self_scan: bool = False):
    from modules.step8_matcher import Step8Matcher
    m = Step8Matcher.__new__(Step8Matcher)
    m.auto_merge_floor = floor
    m.self_scan = self_scan
    m._source_label = "Step 6 (Corrected)"
    return m


def _record(src_idx: int, ref_idx, sim: float, src=None, ref=None):
    return {
        "qcm_id": f"q{src_idx}",
        "source_step": "Step 6 (Corrected)",
        "source_index": src_idx,
        "source_qcm": src or {},
        "source_qcm_full": src or {},
        "best_match": {
            "ref_index": ref_idx,
            "similarity": sim,
            "text_similarity": sim,
            "corr_similarity": None,
            "mode": "text_only",
            "ref_qcm": ref or {},
        },
        "all_candidates": [],
    }


def _test_no_merges_below_floor():
    """1. With floor=0.99 and best matches at 0.85, zero merges, all sources unmerged."""
    print("\n--- Test 1: no merges below floor ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        out = tmp / "step8_matches"
        out.mkdir()
        ref_path = tmp / "ref.xlsx"
        ref_path.write_bytes(b"")  # path stub; not read directly here

        ref_qcms = [{"Num": 1, "Text": "Q1", "Tag": '["Alger"]'}]
        src_qcms = [{"Num": 100, "Text": "Q100", "Tag": '["Oran"]'}]
        records = [_record(0, 0, 0.85, src=src_qcms[0], ref=ref_qcms[0])]

        m = _make_matcher(floor=0.99)
        # Patch the file writers to not require openpyxl/pandas in this environment
        with patch.object(type(m), "_write_df_xlsx", lambda self, rows, p: p.write_text("ok")), \
             patch.object(type(m), "_save_unmerged_xlsx", lambda self, rows, p: p.write_text("ok")):
            summary = m._produce_merge_outputs(records, ref_qcms, src_qcms, out, str(ref_path))

        assert summary["total_merges"] == 0, summary
        assert summary["total_deletions"] == 0
        assert summary["total_unmerged"] == 1, summary
        assert (out / "merge_report.json").exists()
        report = json.loads((out / "merge_report.json").read_text(encoding="utf-8"))
        assert report["total_merges"] == 0
        assert report["merges"] == []
        print("✅ floor respected when below threshold.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_merges_at_default_floor():
    """2. A 98% overlap → 1 merge, tags unioned, source excluded from unmerged."""
    print("\n--- Test 2: 1 merge at 98% ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        out = tmp / "step8_matches"; out.mkdir()
        ref_path = tmp / "modules-bio-chir-med.xlsx"

        ref_qcms = [{"Num": 1, "Text": "Q1", "Tag": '["Alger","2024"]'}]
        src_qcms = [{"Num": 100, "Text": "Q100", "Tag": '["Oran"]', "Year": 2025}]
        records = [_record(0, 0, 0.98, src=src_qcms[0], ref=ref_qcms[0])]

        m = _make_matcher(floor=0.97)
        with patch.object(type(m), "_write_df_xlsx", lambda self, rows, p: setattr(self, "_last_rows", rows)), \
             patch.object(type(m), "_save_unmerged_xlsx", lambda self, rows, p: setattr(self, "_last_unmerged", rows)):
            summary = m._produce_merge_outputs(records, ref_qcms, src_qcms, out, str(ref_path))

        assert summary["total_merges"] == 1, summary
        assert summary["total_deletions"] == 0  # normal mode never deletes
        assert summary["total_unmerged"] == 0
        # The merged tag combined ['Alger', '2024', 'Oran', '2025']
        report = json.loads((out / "merge_report.json").read_text(encoding="utf-8"))
        merged = report["merges"][0]
        assert merged["new_tag"] == ["Alger", "2024", "Oran", "2025"], merged["new_tag"]
        # The ref row's Tag was updated in-memory
        assert "Oran" in ref_qcms[0]["Tag"]
        assert "2025" in ref_qcms[0]["Tag"]
        # _UPDATED.xlsx path includes the ref filename stem
        assert summary["ref_updated_filename"] == "modules-bio-chir-med_UPDATED.xlsx"
        print("✅ one merge with tag union + Year appended.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_tier_grouping():
    """3. Mixed similarities (100, 99, 98, 96%) → 4 merges across 4 tiers."""
    print("\n--- Test 3: tier grouping ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        out = tmp / "step8_matches"; out.mkdir()
        ref_path = tmp / "ref.xlsx"

        ref_qcms = [
            {"Num": 1, "Text": "Q1", "Tag": '["a"]'},
            {"Num": 2, "Text": "Q2", "Tag": '["b"]'},
            {"Num": 3, "Text": "Q3", "Tag": '["c"]'},
            {"Num": 4, "Text": "Q4", "Tag": '["d"]'},
        ]
        src_qcms = [
            {"Num": 101, "Tag": '["x"]'},
            {"Num": 102, "Tag": '["y"]'},
            {"Num": 103, "Tag": '["z"]'},
            {"Num": 104, "Tag": '["w"]'},
        ]
        records = [
            _record(0, 0, 1.000,  src=src_qcms[0], ref=ref_qcms[0]),
            _record(1, 1, 0.9900, src=src_qcms[1], ref=ref_qcms[1]),
            _record(2, 2, 0.9800, src=src_qcms[2], ref=ref_qcms[2]),
            _record(3, 3, 0.9600, src=src_qcms[3], ref=ref_qcms[3]),
        ]
        m = _make_matcher(floor=0.95)
        with patch.object(type(m), "_write_df_xlsx", lambda self, rows, p: None), \
             patch.object(type(m), "_save_unmerged_xlsx", lambda self, rows, p: None):
            summary = m._produce_merge_outputs(records, ref_qcms, src_qcms, out, str(ref_path))

        assert summary["total_merges"] == 4
        tiers = summary["per_tier_stats"]
        assert tiers["100"]["merges"] == 1
        assert tiers["99"]["merges"] == 1
        assert tiers["98"]["merges"] == 1
        assert tiers["95_97"]["merges"] == 1
        print("✅ tiers correctly bucketed.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_self_scan_filters_selfmatch():
    """4. Self-scan with duplicate pair → one merge, one deletion, no unmerged file."""
    print("\n--- Test 4: self-scan ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        out = tmp / "step8_matches"; out.mkdir()
        ref_path = tmp / "ref.xlsx"

        ref_qcms = [
            {"Num": 1, "Text": "Q1", "Tag": '["Alger"]'},
            {"Num": 2, "Text": "Q1-dup", "Tag": '["Oran"]'},
        ]
        # In self-scan, source = ref. Q1's best non-self match is Q2 at 98%;
        # Q2's best non-self match is Q1 at 98%. The loop processes the
        # ONE highest pair first → merge Q1(src)->Q2(ref), delete Q1.
        # Q2's pair is then skipped (ref=Q1 is deleted).
        src_qcms = list(ref_qcms)
        records = [
            _record(0, 1, 0.98, src=src_qcms[0], ref=ref_qcms[1]),
            _record(1, 0, 0.98, src=src_qcms[1], ref=ref_qcms[0]),
        ]
        m = _make_matcher(floor=0.97, self_scan=True)
        with patch.object(type(m), "_write_df_xlsx", lambda self, rows, p: setattr(self, "_last_rows", rows)), \
             patch.object(type(m), "_save_unmerged_xlsx", lambda self, rows, p: setattr(self, "_called_unmerged", True)):
            summary = m._produce_merge_outputs(records, ref_qcms, src_qcms, out, str(ref_path))

        assert summary["total_merges"] == 1, summary
        assert summary["total_deletions"] == 1
        assert summary["self_scan"] is True
        assert summary["unmerged_filename"] is None
        report = json.loads((out / "merge_report.json").read_text(encoding="utf-8"))
        # The merged pair should be the first (Q1 src -> Q2 ref), so the
        # ref's tag comes first in the union: ['Oran', 'Alger']
        merged = report["merges"][0]
        assert merged["new_tag"] == ["Oran", "Alger"], merged
        # Q1 (src) was deleted; only Q2 (ref) survives with the combined tag
        assert "Alger" in ref_qcms[1]["Tag"]
        print("✅ self-scan: 1 merge, 1 deletion, no unmerged file.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_year_added_to_tag():
    """5. Source has Year=2025 not in ref.Tag → '2025' appended after merge."""
    print("\n--- Test 5: year import ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        out = tmp / "step8_matches"; out.mkdir()
        ref_path = tmp / "ref.xlsx"

        ref_qcms = [{"Num": 1, "Text": "Q1", "Tag": '["Alger"]', "Year": 2024}]
        src_qcms = [{"Num": 100, "Text": "Q100", "Tag": '["Oran"]', "Year": 2025}]
        records = [_record(0, 0, 0.985, src=src_qcms[0], ref=ref_qcms[0])]
        m = _make_matcher(floor=0.97)
        with patch.object(type(m), "_write_df_xlsx", lambda self, rows, p: None), \
             patch.object(type(m), "_save_unmerged_xlsx", lambda self, rows, p: None):
            summary = m._produce_merge_outputs(records, ref_qcms, src_qcms, out, str(ref_path))

        report = json.loads((out / "merge_report.json").read_text(encoding="utf-8"))
        merged = report["merges"][0]
        assert "2025" in merged["new_tag"], merged
        # Ref's existing Year (2024) was not a tag value, so it stays only in the Year column
        print("✅ year imported into new tag.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_first_come_first_served():
    """6. Two source QCMs both >= floor against the same ref → both merge into
       the same ref row (tags accumulate)."""
    print("\n--- Test 6: multiple sources → same ref ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        out = tmp / "step8_matches"; out.mkdir()
        ref_path = tmp / "ref.xlsx"

        ref_qcms = [{"Num": 1, "Text": "Q1", "Tag": '["base"]'}]
        src_qcms = [
            {"Num": 101, "Text": "Q101", "Tag": '["srcA"]'},
            {"Num": 102, "Text": "Q102", "Tag": '["srcB"]'},
        ]
        records = [
            _record(0, 0, 0.99, src=src_qcms[0], ref=ref_qcms[0]),
            _record(1, 0, 0.97, src=src_qcms[1], ref=ref_qcms[0]),
        ]
        m = _make_matcher(floor=0.97)
        with patch.object(type(m), "_write_df_xlsx", lambda self, rows, p: None), \
             patch.object(type(m), "_save_unmerged_xlsx", lambda self, rows, p: setattr(self, "_unmerged", rows)):
            summary = m._produce_merge_outputs(records, ref_qcms, src_qcms, out, str(ref_path))

        assert summary["total_merges"] == 2, summary
        assert summary["total_unmerged"] == 0
        # Both source tags accumulated into ref
        assert "srcA" in ref_qcms[0]["Tag"]
        assert "srcB" in ref_qcms[0]["Tag"]
        report = json.loads((out / "merge_report.json").read_text(encoding="utf-8"))
        # Each merge was logged with the cumulative new_tag at THAT moment
        new_tags = [me["new_tag"] for me in report["merges"]]
        assert ["base", "srcA"] == new_tags[0] or ["base", "srcA", "srcB"] in new_tags
        assert "srcB" in new_tags[-1], new_tags
        print("✅ two sources merged into the same ref row.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_input_never_called():
    """7. _produce_merge_outputs MUST NOT call input() (non-interactive on the server)."""
    print("\n--- Test 7: no input() calls ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        out = tmp / "step8_matches"; out.mkdir()
        ref_path = tmp / "ref.xlsx"

        ref_qcms = [{"Num": 1, "Text": "Q1", "Tag": '["a"]'}]
        src_qcms = [{"Num": 100, "Tag": '["x"]'}]
        records = [_record(0, 0, 0.99, src=src_qcms[0], ref=ref_qcms[0])]

        m = _make_matcher(floor=0.97)
        original_input = builtins.input
        calls = []
        def boom(prompt=""):
            calls.append(prompt)
            raise AssertionError(f"input() must not be called, got: {prompt!r}")
        builtins.input = boom
        try:
            with patch.object(type(m), "_write_df_xlsx", lambda self, rows, p: None), \
                 patch.object(type(m), "_save_unmerged_xlsx", lambda self, rows, p: None):
                m._produce_merge_outputs(records, ref_qcms, src_qcms, out, str(ref_path))
        finally:
            builtins.input = original_input
        assert calls == [], calls
        print("✅ zero input() calls during merge phase.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_all():
    _test_no_merges_below_floor()
    _test_merges_at_default_floor()
    _test_tier_grouping()
    _test_self_scan_filters_selfmatch()
    _test_year_added_to_tag()
    _test_first_come_first_served()
    _test_input_never_called()
    print("\n" + "=" * 60)
    print("ALL Step8Matcher merge tests PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()