"""PHASE 2 — Status-driven propagation state machine tests.

Acceptance from the phased plan, Phase 2:
- new_case on p1, continues/ends_here/unrelated mix on p2, fused-narrative case
- deterministic propagation semantics + carry-over across pages
- boundary queue emitted but inert (queue length == ends_here transitions)
- LLM-failure fallback == old behavior ({} page -> legacy-propagate carry-over)
- _process_qcms wiring: end-to-end merged-file path with a mocked client
- audit notes: real linkage decisions only (unrelated never noted)
"""
import json
import os
import sys
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from cc_redesign_fixtures import (
    P1_TEXT, P1_QCMS, SEC_A_TEXT, SEC_B_TEXT, SEC_A_QCM, SEC_B_QCM,
    mock_client, status_response,
)
from modules.utils.cost_tracker import CostTracker
from modules.step3_metadata import Step3Metadata

CARRY = "CAS CLINIQUE 1\r\nNarrative carried over from page N."

def _info(st, label=None, text=None):
    return {"status": st, "label": label, "text": text}

def _make():
    return Step3Metadata(CostTracker())


def _test_state_machine_full_semantics():
    print("\n--- P2.1: five-status state machine semantics ---")
    sm = _make()
    qcms = [{"number": 1}, {"number": 2}, {"number": 3}, {"number": 4}, {"number": 5}]
    cc_map = {
        1: _info("new_case", "CAS CLINIQUE 1", "Narrative one."),
        2: _info("continues"),
        3: _info("ends_here"),
        4: _info("new_case", "CAS CLINIQUE 2", "Narrative two."),
        5: _info("uncertain"),
    }
    upd, carry, notes, bq = sm._propagate_cas_clinique([dict(q) for q in qcms], cc_map, None)
    assert upd[0]["cas"] == "CAS CLINIQUE 1\r\nNarrative one."
    assert upd[1]["cas"] == upd[0]["cas"]
    assert upd[1]["case_belonging_check"] == "continues: detector confirmed the carried-over case"
    assert "cas" not in upd[2]
    assert upd[2]["case_belonging_check"] == "ends_here: case does not inform this question"
    assert upd[3]["cas"] == "CAS CLINIQUE 2\r\nNarrative two.", "next case restarts cleanly"
    assert upd[4]["cas"] == upd[3]["cas"], "uncertain inherits running case"
    assert upd[4]["case_belonging_check"].startswith("uncertain")
    assert carry == upd[3]["cas"], "carry-over == running case at end"
    assert len(bq) == 1 and bq[0]["case_cas"] == "CAS CLINIQUE 1\r\nNarrative one."
    assert bq[0]["trigger_number"] == 3
    print("OK new_case->continues->ends_here->new_case->uncertain all applied exactly once each.")


def _test_transition_frequency_not_qcm_volume():
    print("\n--- P2.2: boundary queue length == ends_here transitions ---")
    sm = _make()
    # 10 QCMs, 2 ends_here -> exactly 2 queued entries, regardless of QCM count
    qcms = [{"number": n} for n in range(1, 11)]
    cc_map = {1: _info("new_case", "C", "N"),
              6: _info("new_case", "C2", "N2")}   # second case (first closed at Q4)
    for n in (4, 8): cc_map[n] = _info("ends_here")
    _upd, _c, _n, bq = sm._propagate_cas_clinique(qcms, cc_map, None)
    assert len(bq) == 2, bq
    # ends_here with nothing running queues NOTHING (no transition happened)
    _u2, _c2, _n2, bq2 = sm._propagate_cas_clinique(
        [{"number": 1}], {1: _info("ends_here")}, None)
    assert bq2 == [], "no running case -> no boundary to check"
    print("OK bounded by case endings, never by QCM volume.")


def _test_failure_fallback_is_legacy():
    print("\n--- P2.3: LLM-failure page degrades to legacy-propagate ---")
    sm = _make()
    # detector returns {} on failure; all listed numbers -> uncertain -> legacy
    upd, carry, notes, bq = sm._propagate_cas_clinique(
        [{"number": 1}, {"number": 2}, {"number": 3}], {}, CARRY)
    assert upd[0]["cas"] == CARRY and upd[1]["cas"] == CARRY and upd[2]["cas"] == CARRY
    assert carry == CARRY, "carry-over survives a failed page (never relinked/never cleared)"
    assert bq == [], "no ends_here can fire from a failed page"
    assert all("uncertain" in upd[i]["case_belonging_check"] for i in (0, 1, 2))
    # same at detector level: garbage response -> {}
    with patch.object(sm, "client", mock_client("bla bla")):
        assert sm._detect_cc_sequential_page("page text", [1, 2]) == {}
    print("OK failed page == old blind behavior; nothing clears, nothing closes.")


def _test_cross_page_full_flow():
    print("\n--- P2.4: synthetic 2-page carry-over (p1 new_case, p2 mix) ---")
    sm = _make()
    # page 1: one case starts, carries
    up1, carry1, _, bq1 = sm._propagate_cas_clinique(
        [dict(q) for q in [{"number": 3}, {"number": 4}]],
        {3: _info("new_case", "CAS CLINIQUE 1", "Salma story."),
         4: _info("continues")}, None)
    assert up1[0]["cas"].startswith("CAS CLINIQUE 1") and carry1 == up1[0]["cas"]
    # page 2: continues, then ends, then standalone
    up2, carry2, _, bq2 = sm._propagate_cas_clinique(
        [{"number": 5}, {"number": 6}, {"number": 7}],
        {5: _info("continues"), 6: _info("ends_here"), 7: _info("unrelated")},
        carry1)
    assert up2[0]["cas"] == carry1
    assert "cas" not in up2[1] and "cas" not in up2[2]
    assert carry2 is None
    assert len(bq2) == 1
    # page 3: nothing running; new_case restarts
    up3, carry3, _, bq3 = sm._propagate_cas_clinique(
        [{"number": 8}, {"number": 9}],
        {8: _info("new_case", "CAS CLINIQUE 2", "New story."),
         9: _info("continues")}, carry2)
    assert up3[0]["cas"].startswith("CAS CLINIQUE 2") and carry3 == up3[0]["cas"]
    assert "case_belonging_check" not in up2[2], "unrelated stays unnoted"
    print("OK full cross-page sequence: start -> continue -> end -> restart.")


def _test_unrelated_unnoted_rules():
    print("\n--- P2.5: audit-note population rules (Fix 2 contract) ---")
    sm = _make()
    upd, _c, notes, _b = sm._propagate_cas_clinique(
        [{"number": 1}, {"number": 2}, {"number": 3}, {"number": 4}],
        {1: _info("new_case", "C", "N"), 3: _info("continues"),
         4: _info("unrelated")}, None)
    assert "case_belonging_check" not in upd[3], "unrelated -> NO audit note"
    assert "case_belonging_check" in upd[0] and "case_belonging_check" in upd[2]
    # continues-with-nothing-running -> no-op, unnoted (degrades, cannot confirm void)
    upd2, carry2, notes2, _b2 = sm._propagate_cas_clinique(
        [{"number": 9}], {9: _info("continues")}, None)
    assert "cas" not in upd2[0] and "case_belonging_check" not in upd2[0]
    print("OK unrelated never noted; orphan 'continues' degrades silently.")


def _test_fused_narrative_new_case():
    print("\n--- P2.6: fused-narrative classification still attaches as new_case ---")
    sm = _make()
    entries = [{"number": 22, "status": "new_case", "cas_label": "CAS CLINIQUE",
                "cas_text": "Madame Benali, 62 ans, diabetique type 2..."}]
    with patch.object(sm, "client", mock_client(status_response(entries)["content"])):
        cc_map = sm._detect_cc_sequential_page("PAGE TEXT", [22])
    upd, carry, notes, _bq = sm._propagate_cas_clinique(
        [{"number": 22}], cc_map, None)
    assert upd[0]["cas"].startswith("CAS CLINIQUE\r\n"), upd[0]
    print("OK fused-narrative detector verdict attaches via new_case.")


def _test_process_qcms_wiring_e2e():
    print("\n--- P2.7: _process_qcms merged-file wiring (end-to-end, mocked) ---")
    sm = _make()
    # two page-groups inside ONE merged file: p77 (no case), p78 (case involving Q1 #repeat)
    merged_qcms = [
        {"uid": "77_1_0", "page": 77, "number": 1},
        {"uid": "78_1_0", "page": 78, "number": 1},
        {"uid": "78_2_1", "page": 78, "number": 2},
    ]

    def side_effect(prompt, model=None, max_tokens=None, **kw):
        if "Fatima" in prompt:
            return status_response([
                {"number": 1, "status": "new_case", "cas_label": "CAS CLINIQUE 1",
                 "cas_text": "Fatima, 29 ans..."},
                {"number": 2, "status": "continues"}])
        return status_response([{"number": 1, "status": "unrelated"}])

    import tempfile, shutil
    tmp = tempfile.mkdtemp()
    try:
        # write step1 texts
        s1 = os.path.join(tmp, "step1_extraction", "accepted")
        os.makedirs(s1, exist_ok=True)
        for n, t in ((77, SEC_A_TEXT), (78, SEC_B_TEXT)):
            with open(os.path.join(s1, f"page_{n}.txt"), "w", encoding="utf-8") as f:
                f.write(t)
        s2 = os.path.join(tmp, "step2_qcm", "accepted")
        os.makedirs(s2, exist_ok=True)
        merged_file = os.path.join(s2, "all_qcms.json")
        with open(merged_file, "w", encoding="utf-8") as f:
            json.dump(merged_qcms, f, ensure_ascii=False)

        calls = []
        def captured_side(prompt, model=None, max_tokens=None, **kw):
            calls.append(prompt)
            return side_effect(prompt, model=model, max_tokens=max_tokens)

        with patch.object(sm, "client") as mc:
            mc.generate_completion.side_effect = captured_side
            sm.run(step2_dir=s2, step1_dir=s1, auto_mode=True,
                   config={"year": {"strategy": "skip"},
                           "clinical_case": {"strategy": "per_group"}})
            assert len(calls) == 2, f"expected 2 page calls (p77, p78), got {len(calls)}"
            assert "Fatima" in calls[1], "p78 prompt embeds its raw page text"
        saved_path = os.path.join(ROOT, "output", "step3_metadata", "accepted", "all_qcms.json")
        with open(saved_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert "cas" not in saved[0], "p77 QCM stays case-free"
        assert saved[1]["cas"].startswith("CAS CLINIQUE 1\r\n")
        assert saved[2]["cas"] == saved[1]["cas"]
        assert saved[1]["case_belonging_check"].startswith("new_case:")
        assert sm._cc_boundary_pending_queue == [], "no ends_here -> no queued transitions"
        # teardown: this e2e wrote into the repo output dir (no-context
        # `Step3Metadata.run` defaults) — remove the stub to keep `output/` clean
        import shutil as _r
        _r.rmtree(os.path.join(ROOT, "output", "step3_metadata"), ignore_errors=True)
    finally:
        import shutil as _sh
        _sh.rmtree(tmp, ignore_errors=True)
    print("OK wiring: page-loop carry-over + status propagation + boundary stash.")


def _run_all():
    _test_state_machine_full_semantics()
    _test_transition_frequency_not_qcm_volume()
    _test_failure_fallback_is_legacy()
    _test_cross_page_full_flow()
    _test_unrelated_unnoted_rules()
    _test_fused_narrative_new_case()
    _test_process_qcms_wiring_e2e()
    print("\n" + "=" * 60)
    print("ALL PHASE 2 PROPAGATION TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()
