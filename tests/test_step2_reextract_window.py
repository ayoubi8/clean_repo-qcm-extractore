"""Tests for the forward-only [P, P+1] re-extraction window
(modules/step2_qcm_extract_batch.py::_reextract_for_incomplete).

A QCM flagged incomplete (proposition count below the dynamic threshold —
possibly split across a page break) is re-run through the LLM. Spillover
only ever flows FORWARD (P -> P+1), so the window must be [P, P+1]:
P-1 holds at most the already-captured stem (pure token overhead +
duplicate-extraction noise).
"""
import os
import sys
import shutil
import tempfile
from pathlib import Path

# Force UTF-8 on Windows
sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))

from modules.utils.cost_tracker import CostTracker
from modules.step2_qcm_extract_batch import Step2QCMExtractBatch


def _make_batch(n_pages: int = 4):
    tmp = Path(tempfile.mkdtemp())
    for p in range(1, n_pages + 1):
        (tmp / f"page_{p}.txt").write_text(f"page {p} text", encoding="utf-8")
    return Step2QCMExtractBatch(CostTracker()), tmp


def _stub_extractor(batch, seen: dict, full_props: int = 5):
    """Stub the LLM call: record the window, return a completed QCM."""
    def fake_concat(files):
        seen["files"] = [f.name for f in files]
        return "BLOB"
    def fake_batch(full_text, start_page, end_page, config=None):
        seen["range"] = (start_page, end_page)
        return [{"number": 7,
                 "propositions": {k: v for k, v in
                                  zip("ABCDE", ["a", "b", "c", "d", "e"])}}]
    batch._concatenate_pages = fake_concat
    batch._extract_all_qcms_batch = fake_batch


def _incomplete_qcm(page: int):
    return {"number": 7, "page": page, "propositions": {"A": "a", "B": "b"}}


def _test_window_middle_page():
    print("\n--- Test 1: middle page -> [P, P+1], never P-1 ---")
    batch, tmp = _make_batch()
    try:
        seen = {}
        _stub_extractor(batch, seen)
        res = batch._reextract_for_incomplete(
            [_incomplete_qcm(2)], list(tmp.glob("page_*.txt")), {})
        assert seen["files"] == ["page_2.txt", "page_3.txt"], seen
        assert seen["range"] == (2, 3), seen
        assert len(res[0]["propositions"]) == 5
        assert res[0]["page"] == 2, "original page stamp preserved"
        print("✅ window [2, 3]; improved match wins; page stamp kept.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_window_boundaries():
    print("\n--- Test 2: first/last page boundaries ---")
    batch, tmp = _make_batch()
    try:
        seen = {}
        _stub_extractor(batch, seen)
        batch._reextract_for_incomplete(
            [_incomplete_qcm(1)], list(tmp.glob("page_*.txt")), {})
        assert seen["files"] == ["page_1.txt", "page_2.txt"], seen
        assert seen["range"] == (1, 2), seen

        seen.clear()
        batch._reextract_for_incomplete(
            [_incomplete_qcm(4)], list(tmp.glob("page_*.txt")), {})
        assert seen["files"] == ["page_4.txt"], seen
        assert seen["range"] == (4, 4), seen
        print("✅ first page -> [1, 2]; last page -> [P] alone.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_no_improvement_keeps_original():
    print("\n--- Test 3: no improvement -> original QCM kept ---")
    batch, tmp = _make_batch()
    try:
        seen = {}
        def fake_concat(files):
            seen["files"] = [f.name for f in files]
            return "BLOB"
        def fake_batch(full_text, start_page, end_page, config=None):
            # Still incomplete: same 2 props as the original.
            return [{"number": 7, "propositions": {"A": "a", "B": "b"}}]
        batch._concatenate_pages = fake_concat
        batch._extract_all_qcms_batch = fake_batch
        res = batch._reextract_for_incomplete(
            [_incomplete_qcm(2)], list(tmp.glob("page_*.txt")), {})
        assert seen["files"] == ["page_2.txt", "page_3.txt"], seen
        assert len(res[0]["propositions"]) == 2, "original kept verbatim"
        print("✅ window still forward-only; original kept on no improvement.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_all():
    _test_window_middle_page()
    _test_window_boundaries()
    _test_no_improvement_keeps_original()

    print("\n" + "=" * 60)
    print("ALL step2_reextract_window TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()
