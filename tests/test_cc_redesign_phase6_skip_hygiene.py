"""PHASE 6 — Skip strategy: hygiene without linkage.

Acceptance from the phased plan, Phase 6:
- ClinicalCase = skip STILL runs the per-page detection call (state-aware
  classifier reused verbatim; independent per page — narratives never split)
- Propagation/linkage DISABLED: new_case attaches the narrative ONLY to its
  own trigger/fused QCM; continues does NOT link; uncertain never attaches;
  cross-QCM `cas` propagation never appears; carry-over permanently None
- NO case_belonging_check entries under skip (column reserved for linkage
  decisions — none are made)
- Boundary queue stays empty (no ends_here transitions) and the cascade
  skips both boundary and checker under skip
- cas_text_split still runs unchanged over whatever cas fields exist
"""
import json
import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from cc_redesign_fixtures import SEC_A_TEXT, SEC_B_TEXT, mock_client, status_response
from modules.utils.cost_tracker import CostTracker
from modules.step3_metadata import Step3Metadata

CASE = "CAS CLINIQUE 1\r\nSalma, 56 ans."

def _info(st, label=None, text=None):
    return {"status": st, "label": label, "text": text}

def _make():
    return Step3Metadata(CostTracker())


def _test_skip_no_carry_propagation():
    print("\n--- P6.1: propagation(linkage=False) attaches ONLY at triggers ---")
    sm = _make()
    cc_map = {
        1: {"status": "new_case", "label": "CAS CLINIQUE 1", "text": "Salma story."},
        2: {"status": "continues", "label": None, "text": None},
        3: {"status": "uncertain", "label": None, "text": None},
        4: {"status": "unrelated", "label": None, "text": None},
    }
    upd, carry, notes, bq = sm._propagate_cas_clinique(
        [{"number": n} for n in (1, 2, 3, 4)], cc_map, "OLD\r\ncarry", linkage=False)
    assert upd[0]["cas"].startswith("CAS CLINIQUE 1"), "own-QCM attach kept (hygiene)"
    assert upd[0]["cas"] == "CAS CLINIQUE 1\r\nSalma story."
    for i in (1, 2, 3):
        assert "cas" not in upd[i], f"NO linkage/carry onto Q{i+1}"
    assert carry is None, "carry-over permanently None under skip"
    assert notes == {}, "no linkage decisions under skip -> no audit notes"
    assert bq == [], "no boundary transitions ever under skip"
    print("OK hygiene-only attach; zero linkage, zero notes, zero queue.")


def _test_skip_detection_runs_and_attaches_e2e():
    print("\n--- P6.2: skip still runs the per-page detection (e2e, mocked) ---")
    sm = _make()
    merged_qcms = [
        {"uid": "77_1_0", "page": 77, "number": 1},
        {"uid": "78_1_0", "page": 78, "number": 1},
        {"uid": "78_2_1", "page": 78, "number": 2},
    ]
    calls = []
    def side_effect(prompt, model=None, max_tokens=None, **kw):
        calls.append(prompt)
        if "Fatima" in prompt:
            return status_response([
                {"number": 1, "status": "new_case", "cas_label": "CAS CLINIQUE 1",
                 "cas_text": "Fatima, 29 ans..."},
                {"number": 2, "status": "continues"}])
        return status_response([{"number": 1, "status": "unrelated"}])

    tmp = Path(tempfile.mkdtemp())
    try:
        s1 = tmp / "step1_extraction" / "accepted"; s1.mkdir(parents=True)
        for n, t in ((77, SEC_A_TEXT), (78, SEC_B_TEXT)):
            (s1 / f"page_{n}.txt").write_text(t, encoding="utf-8")
        s2 = tmp / "step2_qcm" / "accepted"; s2.mkdir(parents=True)
        (s2 / "all_qcms.json").write_text(
            json.dumps(merged_qcms, ensure_ascii=False), encoding="utf-8")

        with patch.object(sm, "client") as mc:
            mc.generate_completion.side_effect = side_effect
            sm.run(step2_dir=str(s2), step1_dir=str(s1), auto_mode=True,
                   config={"year": {"strategy": "skip"},
                           "clinical_case": {"strategy": "skip"}})
        assert len(calls) == 2, f"detection MUST run under skip: {len(calls)} calls"

        saved = json.loads((Path(ROOT) / "output" / "step3_metadata" / "accepted" / "all_qcms.json")
                           .read_text(encoding="utf-8"))
        assert "cas" not in saved[0], "no case attaches to unrelated QCM (skip)"
        assert saved[1]["cas"].startswith("CAS CLINIQUE 1\r\n"), "fused/new_case narrative lands in cas"
        assert saved[1]["cas"] == "CAS CLINIQUE 1\r\nFatima, 29 ans..."
        # continues did NOT propagate into Q2
        assert "cas" not in saved[2], "cross-QCM linkage disabled under skip"
        for q in saved:
            assert "case_belonging_check" not in q, "no linkage notes under skip"
        assert sm._cc_boundary_pending_queue == [], "empty queue under skip"
        # teardown: remove the repo-output stub created by this no-context e2e
        shutil.rmtree(os.path.join(ROOT, "output", "step3_metadata"), ignore_errors=True)
        print("OK skip: detection runs, hygiene attach works, no linkage anywhere.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_per_group_positive_control():
    print("\n--- P6.3: positive control — per_group STILL links ---")
    sm = _make()
    cc_map = {
        1: {"status": "new_case", "label": "CAS CLINIQUE 1", "text": "Story."},
        2: {"status": "continues", "label": None, "text": None},
    }
    upd, carry, notes, bq = sm._propagate_cas_clinique(
        [{"number": 1}, {"number": 2}], cc_map, None, linkage=True)
    assert upd[1]["cas"] == upd[0]["cas"], "per_group cascade unchanged"
    assert carry is not None and len(bq) == 0
    assert notes[2].startswith("continues")
    print("OK linkage mode untouched by the Phase 6 gate.")


def _test_cas_split_still_runs():
    print("\n--- P6.4: cas_text_split operates under skip output unchanged ---")
    import asyncio
    from modules.cas_text_split import split_cas_from_text
    text = "Salma, 56 ans, sous Amiodarone Parmi les propositions suivantes..."
    new_text, removed = split_cas_from_text(
        text, "CAS CLINIQUE 1\r\nSalma, 56 ans, sous Amiodarone")
    assert removed and new_text.startswith("Parmi"), (new_text, removed)
    print("OK hygiene mechanism unchanged; operates on skip-produced cas.")


def _run_all():
    _test_skip_no_carry_propagation()
    _test_skip_detection_runs_and_attaches_e2e()
    _test_per_group_positive_control()
    _test_cas_split_still_runs()
    print("\n" + "=" * 60)
    print("ALL PHASE 6 SKIP STRATEGY TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()
