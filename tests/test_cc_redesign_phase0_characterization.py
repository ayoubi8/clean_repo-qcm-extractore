"""PHASE 0 — Characterization tests: freeze TODAY's clinical-case behavior.

Behavior freeze for the Clinical Case Redesign v2 phased rollout. Zero
production edits — this file (and acc_fixtures) are the only artifacts.

Frozen contracts (as implemented TODAY in modules/step3_metadata.py):
F1. _detect_cc_sequential_page signature: (page_text, qcm_numbers) -> dict
F2. Response shape conversion: {num: "LABEL\r\ncas_text"} for listed entries
    with cas_text; None for entries without; numbers not listed: ABSENT
F3. "[]" response -> returns [] (empty list, pipeline treats as no triggers)
F4. No-JSON response -> {} (propagation then keeps carry-over for everyone)
F5. Model failure (both primary and fallback) -> {} ; fallback model tried
    after primary raises
F6. Prompt carries: the critical rules text, "QCM NUMBERS ON THIS PAGE:",
    and the raw page text
F7. _propagate_cas_clinine semantics: trigger replaces, then cascades until
    next trigger; carry-over applied at document start when provided; no
    "cas" key when nothing running; QCM number 0/None treated as unknown
F8. Cross-page carry-over: return-value carry-over == second call's input
F9. _detect_clinical_cases_document exists and returns [] on empty inputs
F10. Strategy G detection entry (_detect_clinical_cases) present with its
     per-page label/text/qcm_numbers contract

Runner: python tests/test_cc_redesign_phase0_characterization.py
(all assertions hard-fail; pytest-compatible via function collection)
"""
import json
import os
import sys
import unicodedata  # noqa: F401
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from cc_redesign_fixtures import (
    P1_TEXT, P1_QCMS, P5_TEXT_UNMARKED, P5_QCMS_UNMARKED,
    FUSED_PAGE_TEXT, FUSED_QCM, NO_CASE_PAGE_TEXT, NO_CASE_QCMS,
    SEC_A_TEXT, SEC_B_TEXT, SEC_A_QCM, SEC_B_QCM,
    mock_client, resp_now, empty_page_response,
)
from modules.utils.cost_tracker import CostTracker
from modules.step3_metadata import Step3Metadata


def _make_step3():
    return Step3Metadata(CostTracker())


# ── F1/F2: detector contract — REVISED AT PHASE 2 (deliberate change) ────────
# The detector now returns the raw 5-status map; legacy attach-behavior moved
# to the propagation state machine (tested in F7/F8 below).

def _test_detector_shapes_current_contract():
    print("\n--- F1/F2 (P2 baseline): detector returns the 5-status map ---")
    sm = _make_step3()
    entries = [
        {"number": 3, "status": "new_case", "cas_label": "CAS CLINIQUE 1",
         "cas_text": "Salma, 56 ans... cytolyse a 12N."},
        {"number": 4, "status": "continues", "cas_label": None, "cas_text": None},
        {"number": 6, "status": "ends_here", "cas_label": None, "cas_text": None},
        {"number": 8, "status": "unrelated", "cas_label": None, "cas_text": None},
    ]
    with patch.object(sm, "client", mock_client(json.dumps(entries, ensure_ascii=False))):
        out = sm._detect_cc_sequential_page(P1_TEXT, [3, 4, 6, 8])
    assert isinstance(out, dict), f"expected dict, got {type(out)}"
    assert out[3] == {"status": "new_case", "label": "CAS CLINIQUE 1",
                      "text": "Salma, 56 ans... cytolyse a 12N."}, out[3]
    assert out[4]["status"] == "continues" and out[6]["status"] == "ends_here"
    assert out[8]["status"] == "unrelated"
    print("OK detector returns {num: status-dict} (legacy attach lives in propagation).")


# ── F3/F4: degenerate responses — REVISED AT PHASE 1 (deliberate change) ──────
# "[]" now normalizes to all-None (complete decided page; propagation-equivalent
# to the old {}). Garbage stays {}.

def _test_detector_empty_and_garbage():
    print("\n--- F3/F4 (P1 baseline): '[]' and no-JSON responses ---")
    sm = _make_step3()
    with patch.object(sm, "client", mock_client("[]")):
        out = sm._detect_cc_sequential_page(NO_CASE_PAGE_TEXT, [7])
    assert out == {}, f"empty array must yield an empty status map: {out!r}"

    with patch.object(sm, "client", mock_client("des mots sans json du tout")):
        out2 = sm._detect_cc_sequential_page(NO_CASE_PAGE_TEXT, [7])
    assert out2 == {}, f"no-JSON response must yield legacy garbage fallback: {out2!r}"
    print("OK '[]' -> all-None (decided page); garbage -> {} (legacy-propagate mode).")


# ── F5: model failure path (primary raises, fallback tried) ──────────────────

def _test_detector_primary_failure_falls_back():
    print("\n--- F5: primary model failure -> fallback model used ---")
    sm = _make_step3()
    calls = []
    entries = [{"number": 3, "cas_label": "CAS CLINIQUE 1", "cas_text": "Salma..."}]

    def side_effect(prompt, model=None, **kw):
        calls.append(model)
        if len(calls) == 1:  # first call (primary) fails, regardless of env
            raise RuntimeError("primary down (simulated)")
        return resp_now(entries)

    with patch.object(sm, "client") as mc:
        mc.generate_completion.side_effect = side_effect
        out = sm._detect_cc_sequential_page(P1_TEXT, [3])
    assert out[3] == {"status": "new_case", "label": "CAS CLINIQUE 1", "text": "Salma..."}, out
    assert len(calls) == 2, f"expected primary+fallback calls, got {calls}"
    print(f"OK models tried in order: {calls}")


# ── F6: prompt content — REVISED AT PHASE 1 (deliberate change) ────────────────
# Original baseline froze the binary/start-only stateless prompt. Phase 1
# deliberately rewrites it into the 5-status state-aware classifier. This test
# now freezes the PHASE-1 prompt contract instead.

def _test_detector_prompt_content():
    print("\n--- F6 (P1 baseline): prompt is now state-aware 5-status ---")
    sm = _make_step3()
    captured = {}
    def side_effect(prompt, model=None, max_tokens=None, **kw):
        captured["prompt"] = prompt
        return empty_page_response(3)
    with patch.object(sm, "client") as mc:
        mc.generate_completion.side_effect = side_effect
        sm._detect_cc_sequential_page(P5_TEXT_UNMARKED, [5, 12])
    p = captured["prompt"]
    for status in ("new_case", "continues", "ends_here", "unrelated", "uncertain"):
        assert f'"{status}"' in p, f"missing status {status}"
    assert "QCM NUMBERS ON THIS PAGE: [5, 12]" in p
    assert "5/ Rachid" in p, "raw page text must be embedded"
    assert "FUSED-NARRATIVE RULE" in p
    assert "CURRENTLY ACTIVE CASE (carried over from an earlier page): NONE." in p, \
        "no carry-over input -> explicit NONE block"
    print("OK P1 prompt contract frozen (5 statuses, fused rule, NONE block).")


# ── F7: propagation semantics — REVISED AT PHASE 2 (deliberate change) ───────
# The propagation is now a status-driven state machine (see the Phase 2 test
# file for the full battery). This baseline keeps the invariants that matter
# across phases: explicit statuses, carry-over as initial state, no 'cas' key
# when nothing running, legacy degradation on uncertain / garbage pages.

def _info(st, label=None, text=None):
    return {"status": st, "label": label, "text": text}

def _test_propagation_semantics():
    print("\n--- F7 (P2 baseline): status-driven state machine invariants ---")
    sm = _make_step3()

    # new_case replaces + cascades; ends_here closes; uncertain legacy-degrades
    qcms = [{"number": 1}, {"number": 2}, {"number": 3}, {"number": 4}]
    cc_map = {1: _info("new_case", "CAS CLINIQUE 1", "N1"),
              2: _info("continues"),
              3: _info("ends_here"),
              4: _info("uncertain")}
    upd, carry, notes, bq = sm._propagate_cas_clinique([dict(q) for q in qcms], cc_map, None)
    assert upd[0]["cas"].startswith("CAS CLINIQUE 1"), "new_case attaches"
    assert upd[1]["cas"] == upd[0]["cas"], "continues keeps cascade"
    assert "cas" not in upd[2] and upd[2]["case_belonging_check"].startswith("ends_here"), \
        "ends_here detaches and audits"
    assert "cas" not in upd[3], "after ends_here nothing propagates"
    assert all(q.get("page", True) is not False for q in upd)
    assert bq and bq[0]["case_cas"].startswith("CAS CLINIQUE 1"), "boundary queued per transition"
    assert carry is None, "carry-over cleared after ends_here"

    # uncertain with a running case -> persists (safety valve)
    out2, carry2, n2, bq2 = sm._propagate_cas_clinique(
        [{"number": 1}, {"number": 2}], {1: _info("new_case", "C", "N"), 2: _info("uncertain")}, None)
    assert out2[1]["cas"] == out2[0]["cas"], "uncertain keeps the running case"
    assert "case_belonging_check" in out2[1] and not bq2

    # inheritance from carry-over + falsy-number handling unchanged
    out3, carry3, n3, bq3 = sm._propagate_cas_clinique(
        [{"number": 0}, {"number": None}], {}, "C\r\nN")
    assert out3[0]["cas"] == "C\r\nN" and out3[1]["cas"] == "C\r\nN"
    assert carry3 == "C\r\nN"

    # nothing running + no detector decision -> NO 'cas' key; missing entry is
    # normalized to uncertain, which IS a real linkage decision -> audited
    out4, carry4, n4, bq4 = sm._propagate_cas_clinique([{"number": 5}], {}, None)
    assert "cas" not in out4[0]
    assert out4[0].get("case_belonging_check", "").startswith("uncertain")
    assert carry4 is None and bq4 == []
    # EXPLICIT unrelated -> clean, no audit note at all
    upd5, carry5, n5, bq5 = sm._propagate_cas_clinique(
        [{"number": 5}], {5: _info("unrelated")}, None)
    assert "cas" not in upd5[0] and "case_belonging_check" not in upd5[0]
    print("OK new_case/continues/ends_here/uncertain/carry_over/unrelated-free all frozen.")


# ── F8: cross-page carry-over contract — REVISED AT PHASE 2 ─────────────────

SEC_B_QCMS_PLACEHOLDER = [{"uid": "78_1_0", "page": 78, "number": 1}]  # Q1 on p.78


def _test_two_page_carryover_chain():
    print("\n--- F8 (P2 baseline): page N narrative -> page N+1 questions ---")
    sm = _make_step3()
    narrative = "Fatima, 29 ans, premiere grossesse 8 SA..."
    p1_map = {1: _info("new_case", "CAS CLINIQUE 1", narrative),
              2: _info("continues")}
    up1, carry, n1, bq1 = sm._propagate_cas_clinique(
        [dict(q) for q in SEC_B_QCMS_PLACEHOLDER], p1_map, None)
    assert carry and carry.startswith("CAS CLINIQUE 1"), "carry == running case"
    print("   page 1: case starts at Q1, carries on Q2 via 'continues'")

    # page 2: detector EXPLICITLY confirms continuation (no more blind default)
    p2_map = {1: _info("continues"), 2: _info("uncertain")}
    up2, carry2, n2, bq2 = sm._propagate_cas_clinique([{"number": 1}, {"number": 2}], p2_map, carry)
    assert up2[0]["cas"] == carry, "cross-page QCM confirmed via explicit 'continues'"
    assert up2[1]["cas"] == carry, "uncertain degrades to legacy propagate"
    assert carry2 == carry
    assert not bq2, "no ends_here -> no boundary entries"
    print("OK carry-over flows page to page (now explicit, not assumed).")

# ends_here at a page start after the elbow carry-over end
def _test_ends_here_closes_carryover():
    print("\n--- F8b: ends_here closes a carried-over case at page start ---")
    sm = _make_step3()
    carry = "CAS CLINIQUE 1\r\nOld narrative."
    up, carryout, n, bq = sm._propagate_cas_clinique(
        [{"number": 7}, {"number": 8}],
        {7: _info("ends_here"), 8: _info("uncertain")}, carry)
    assert "cas" not in up[0], "carried case detached at ends_here"
    assert "cas" not in up[1], "no case running -> uncertain attaches nothing"
    assert carryout is None
    assert len(bq) == 1 and bq[0]["case_cas"] == carry, "one boundary entry per ending"
    print("OK carry-over consumption stops, boundary queued once.")


# ── F9: document-level variant presence+degenerate contract ──────────────────

def _test_document_variant_presence():
    print("\n--- F9: _detect_clinical_cases_document exists, degenerate inputs ---")
    sm = _make_step3()
    assert sm._detect_clinical_cases_document("", []) == []
    assert sm._detect_clinical_cases_document("text", []) == []
    print("OK empty inputs -> [] (dormant fallback path, untouched by plan).")


# ── F10: strategy-G single-call helper presence ──────────────────────────────

def _test_page_level_variant_presence():
    print("\n--- F10: _detect_clinical_cases page-variant contract ---")
    sm = _make_step3()
    entries = [{"label": "CAS CLINIQUE 1", "text": "Salma...", "qcm_numbers": [3]}]
    with patch.object(sm, "client", mock_client(json.dumps(entries))):
        out = sm._detect_clinical_cases(P1_TEXT, [3])
    assert out == entries, out
    with patch.object(sm, "client", mock_client("[]")):
        assert sm._detect_clinical_cases(NO_CASE_PAGE_TEXT, [7]) == []
    print("OK {label, text, qcm_numbers} list shape frozen (strategy G feed).")


# ── Placeholder: end-to-end 2-page carry-over cascade (filled in Phase 2) ─────

def _test_cascade_two_page_carryover_e2e():
    print("\n--- PLACEHOLDER: full _process_qcms 2-page e2e fills in Phase 2 ---")
    print("SKIP (placeholder by design — real wiring asserted from Phase 2 on)")


def _run_all():
    _test_detector_shapes_current_contract()
    _test_detector_empty_and_garbage()
    _test_detector_primary_failure_falls_back()
    _test_detector_prompt_content()
    _test_propagation_semantics()
    _test_two_page_carryover_chain()
    _test_ends_here_closes_carryover()
    _test_document_variant_presence()
    _test_page_level_variant_presence()
    _test_cascade_two_page_carryover_e2e()
    print("\n" + "=" * 60)
    print("ALL PHASE 0 CHARACTERIZATION TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()
