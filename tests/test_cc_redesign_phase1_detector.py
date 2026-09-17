"""PHASE 1 — State-aware detector tests.

Acceptance from the phased plan, Phase 1:
- Parser `_parse_cc_statuses`: shape {num: {status,label,text}}, enum coercion
  (outside values -> "uncertain"), missing listed numbers -> "uncertain"
  (never silently dropped), empty array -> {}, simple old-shape fixture
  (no explicit status) still parses by inference.
- Status map -> legacy adapter: new_case -> "LABEL\\r\\ntext", all other
  statuses -> None, so the unchanged propagation contract holds.
- Prompt: carries the carry-over block IFF provided, fallback to "NONE"
  block, numbers list, raw page text, and the fused-narrative rule.
- Legacy behavior parity kept for: primary->fallback model order, garbage
  response -> {}, "[]" -> all-None normalization.
"""
import json
import sys
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from cc_redesign_fixtures import (
    P1_TEXT, NO_CASE_PAGE_TEXT, mock_client, status_response, resp_now,
)
from modules.utils.cost_tracker import CostTracker
from modules.step3_metadata import Step3Metadata

TRIGGER = "CAS CLINIQUE 1\r\nSalma, 56 ans..."          # legacy-shaped new_case
CARRY = "CAS CLINIQUE 1\r\nPatient sentinelle XZ-01."   # sentinel NOT in P1_TEXT


def _make():
    return Step3Metadata(CostTracker())


def _test_parser_shape_and_coercion():
    print("\n--- P1.1: _parse_cc_statuses shape, enum coercion, defaults ---")
    sm = _make()
    raw_keys = set(sm._CC_STATUSES)
    assert raw_keys == {"new_case", "continues", "ends_here", "unrelated", "uncertain"}

    m = sm._parse_cc_statuses(status_response([
        {"number": 3, "status": "new_case", "cas_label": "CAS CLINIQUE 1",
         "cas_text": "Salma..."},
        {"number": 4, "status": "continues", "cas_label": None, "cas_text": None},
        {"number": 6, "status": "ends_here", "cas_label": None, "cas_text": None},
        {"number": 8, "status": "unrelated", "cas_label": None, "cas_text": None},
    ])["content"], [3, 4, 6, 8, 99])
    assert m[3]["status"] == "new_case" and m[3]["label"] == "CAS CLINIQUE 1"
    assert m[4]["status"] == "continues"
    assert m[6]["status"] == "ends_here"
    assert m[8]["status"] == "unrelated"
    # listed but MISSING from response -> uncertain, never dropped
    assert m[99] == {"status": "uncertain", "label": None, "text": None}

    m2 = sm._parse_cc_statuses(
        '[{"number": 3, "status": "maybe_belong", "cas_label": null, "cas_text": null}]',
        [3])
    assert m2[3]["status"] == "uncertain", "outside enum coerced"
    print("OK shape, coercion, missing->uncertain all correct.")


def _test_parser_inference_and_empty():
    print("\n--- P1.2: status inference + empty array -> {} ---")
    sm = _make()
    # no explicit status: cas_text present -> new_case (old-shape compatible)
    m = sm._parse_cc_statuses(
        resp_now([{"number": 3, "cas_label": "CAS CLINIQUE 1", "cas_text": "Salma..."},
                  {"number": 4, "cas_label": None, "cas_text": None}])["content"],
        [3, 4])
    assert m[3]["status"] == "new_case" and m[4]["status"] == "uncertain"
    # empty array -> {} (nothing on page)
    assert sm._parse_cc_statuses("[]", [7]) == {}
    # unparsable -> None (detector then treats like legacy garbage -> {})
    assert sm._parse_cc_statuses("no json here at all", [7]) is None
    print("OK inference, empty array {}, unparsable None.")


def _test_adapter_legacy_parity():
    print("\n--- P1.3 (P2 baseline): detector output flows through the state machine ---")
    sm = _make()
    entries = [
        {"number": 3, "status": "new_case", "cas_label": "CAS CLINIQUE 1", "cas_text": "Salma..."},
        {"number": 4, "status": "continues", "cas_label": None, "cas_text": None},
        {"number": 6, "status": "ends_here", "cas_label": None, "cas_text": None},
        {"number": 8, "status": "uncertain", "cas_label": None, "cas_text": None},
    ]
    with patch.object(sm, "client", mock_client(status_response(entries)["content"])):
        cc_map = sm._detect_cc_sequential_page(P1_TEXT, [3, 4, 6, 8])
    assert cc_map[3]["status"] == "new_case" and cc_map[6]["status"] == "ends_here"
    upd, carry, notes, bq = sm._propagate_cas_clinique(
        [{"number": 3}, {"number": 4}, {"number": 6}, {"number": 8}], cc_map, None)
    assert upd[0]["cas"] == "CAS CLINIQUE 1\r\nSalma...", upd[0]
    assert upd[1]["cas"] == upd[0]["cas"], "only new_case attaches; downstream via explicit confirm"
    assert "cas" not in upd[2] and "cas" not in upd[3]
    assert len(bq) == 1, "one boundary entry for the ends_here transition"
    print("OK detector->propagation integration: only new_case attaches; boundary queued.")


def _test_carryover_prompt():
    print("\n--- P1.4: carry-over block in prompt IFF provided ---")
    sm = _make()
    captured = {}
    def side_effect(prompt, model=None, max_tokens=None, **kw):
        captured["prompt"] = prompt
        return status_response([{"number": 4, "status": "continues"}])
    with patch.object(sm, "client") as mc:
        mc.generate_completion.side_effect = side_effect
        sm._detect_cc_sequential_page(P1_TEXT, [4])          # no carry-over
        p_none = captured["prompt"]
        assert "CURRENTLY ACTIVE CASE (carried over from an earlier page): NONE." in p_none
        assert "Patient sentinelle XZ-01." not in p_none

        sm._detect_cc_sequential_page(P1_TEXT, [4], carry_over=CARRY)
        p_carry = captured["prompt"]
        assert "CURRENTLY ACTIVE CASE" in p_carry and "Patient sentinelle XZ-01." in p_carry
        assert "CURRENTLY ACTIVE CASE (carried over from an earlier page): NONE." not in p_carry
        # fused-narrative rule must always be present (v4: positive definition
        # carries the fused rule — CC Detection v4 deliberate swap)
        assert "What IS a clinical case narrative" in p_carry
        assert "FUSED" in p_carry and "FUSED" in p_none
        assert p_none != p_carry
    print("OK carry-over block present IFF provided; fused rule always in prompt.")


def _test_detector_garbage_and_failure_parity():
    print("\n--- P1.4 (P2 baseline): degenerate responses, failure order ---")
    sm = _make()
    with patch.object(sm, "client", mock_client("des mots sans json du tout")):
        assert sm._detect_cc_sequential_page(NO_CASE_PAGE_TEXT, [7]) == {}
    with patch.object(sm, "client", mock_client("[]")):
        assert sm._detect_cc_sequential_page(NO_CASE_PAGE_TEXT, [7]) == {}

    calls = []
    def side_effect(prompt, model=None, max_tokens=None, **kw):
        calls.append(model)
        if len(calls) == 1:
            raise RuntimeError("primary down (simulated)")
        return status_response([{"number": 3, "status": "new_case",
                                 "cas_label": "CAS CLINIQUE 1", "cas_text": "Salma..."}])
    with patch.object(sm, "client") as mc:
        mc.generate_completion.side_effect = side_effect
        out = sm._detect_cc_sequential_page(P1_TEXT, [3])
    assert out[3] == {"status": "new_case", "label": "CAS CLINIQUE 1", "text": "Salma..."}, out
    assert len(calls) == 2, calls
    print("OK garbage -> {}, '[]' -> {}, primary -> fallback order kept.")


def _run_all():
    _test_parser_shape_and_coercion()
    _test_parser_inference_and_empty()
    _test_adapter_legacy_parity()
    _test_carryover_prompt()
    _test_detector_garbage_and_failure_parity()
    print("\n" + "=" * 60)
    print("ALL PHASE 1 DETECTOR TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()
