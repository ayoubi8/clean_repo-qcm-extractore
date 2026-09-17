"""CC Detection v4 â€” anchor-schema tests (V4-1/V4-2/V4-3).

Covers: the schema sniffer (v4 vs legacy), the anchor_num validation rule
(own page numbers / max+1 / anything else rejected), zero-QCM trailing
pages, anchor_text_clean incorporation (write-back incl. the cas_text_split
safety net), the detector: note (distinct from case_belonging_check), the
Num-gap predicate warning, and the end-to-end trailing â†’ pending â†’ merged
"Num" resolution (the user-required cross-page link).
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from tests.cc_redesign_fixtures import (  # noqa: E402
    anchor_response, anchor, TRAILING_NARRATIVE,
)
from modules.step3_metadata import Step3Metadata  # noqa: E402


def analyzer_for(content: str, calls: list = None):
    """Step3Metadata with a mocked client recording each call."""
    import types

    m = Step3Metadata.__new__(Step3Metadata)
    m.context = None
    m.cost_tracker = MagicMock()
    client = MagicMock()

    def gen(prompt, model=None, max_tokens=None, **kw):
        if calls is not None:
            calls.append({"prompt": prompt, "model": model})
        return {"content": content,
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "cost": 0.0}

    client.generate_completion.side_effect = gen
    m.client = client
    return m


# â”€â”€ V4-1 parser ------------------------------------------------------

def test_in_page_anchor_accepted():
    a = analyzer_for(json.dumps([
        {"anchor_num": 4, "cas_label": "CAS CLINIQUE",
         "cas_text": "Zhor, 77 ans, diabÃ©tique de type II.",
         "anchor_text_clean": "Bilan initial?", "note": "patient story"},
    ]))
    cc_map, trailing = a._parse_cc_response(
        json.dumps([{"anchor_num": 4, "cas_label": "CAS CLINIQUE",
                     "cas_text": "Zhor, 77 ans, diabÃ©tique de type II.",
                     "anchor_text_clean": "Bilan initial?",
                     "note": "patient story"}]),
        [1, 2, 3, 4, 5])
    assert cc_map[4]["status"] == "new_case"
    assert "diabÃ©tique" in cc_map[4]["text"]
    assert cc_map[4]["detector_note"] == "patient story"
    assert cc_map[4]["anchor_text_clean"] == "Bilan initial?"
    # unlisted numbers keep the shipped uncertainty semantics
    assert cc_map[1]["status"] == "uncertain"
    assert trailing is None


def test_max_plus1_routes_to_trailing():
    content = json.dumps([
        {"anchor_num": 12, "cas_label": "CAS CLINIQUE",
         "cas_text": TRAILING_NARRATIVE,
         "anchor_text_clean": None, "note": "trailing"}])
    cc_map, trailing = a2 = _quick_parse(content, [7, 8, 9, 10, 11])
    assert cc_map is not None
    assert trailing["text"] == TRAILING_NARRATIVE
    assert trailing["note"] == "trailing"
    # NO in-page new_case emitted for a trailing anchor
    assert all(v.get("status") != "new_case" for v in cc_map.values())


def _quick_parse(content, nums):
    a = analyzer_for(content)
    return a._parse_cc_response(content, nums)


def test_gap_anchor_rejected():
    content = json.dumps([{"anchor_num": 20,
                           "cas_text": "M. X, 50 ans, prÃ©senteâ€¦",
                           "cas_label": "CAS CLINIQUE"}])
    cc_map, trailing = _quick_parse(content, [1, 2, 3])
    assert trailing is None
    # no hard negative invented: rejected anchor simply absent
    assert all(cc_map[n]["status"] == "uncertain" for n in [1, 2, 3])


def test_zero_qcm_page_becomes_trailing():
    content = json.dumps([{"anchor_num": 1, "cas_label": "CAS CLINIQUE",
                           "cas_text": TRAILING_NARRATIVE}])
    cc_map, trailing = _quick_parse(content, [])
    assert cc_map == {} or cc_map is not None
    assert trailing["text"] == TRAILING_NARRATIVE


def test_legacy_schema_still_parses():
    content = json.dumps([
        {"number": 4, "status": "new_case", "cas_label": "CAS CLINIQUE",
         "cas_text": "Salma, 56 ans, traitÃ©e par Amiodaroneâ€¦"},
    ])
    cc_map, trailing = _quick_parse(content, [3, 4])
    assert cc_map[4]["status"] == "new_case"
    assert cc_map[3]["status"] == "uncertain"
    assert trailing is None


def test_garbage_json_is_failure():
    cc_map, trailing = _quick_parse("not json at all", [1, 2])
    assert cc_map is None and trailing is None


# â”€â”€ V4-2 prompt / detect call ---------------------------------------

def test_detect_returns_anchor_map_and_prompt_carries_rules():
    calls = []
    content = json.dumps([{"anchor_num": 4,
                           "cas_label": "CAS CLINIQUE",
                           "cas_text": "Salma, 56 ans, traitÃ©e par "
                                       "Amiodarone, consulte pour un "
                                       "ictÃ¨re fÃ©brile.",
                           "anchor_text_clean":
                               "Parmi les propositions suivantes, quelle la "
                               "plus probable ?",
                           "note": "patient narrative with history"}])
    a = analyzer_for(content, calls)
    m = a._detect_cc_sequential_page(
        "CAS CLINIQUE 1 : Salma... Q4. Parmi les propositions suivantes ?",
        [3, 4, 5])
    assert m[4]["status"] == "new_case"
    assert m[4]["anchor_text_clean"].startswith("Parmi")
    # v4 prompt surface (single call; reasoning-model default in V4-0)
    assert len(calls) == 1
    p = calls[0]["prompt"]
    assert "What IS a clinical case narrative" in p
    assert "anchor_num" in p and "anchor_text_clean" in p
    assert "HTA 38 30" in p               # OCR-noise counter-example present
    assert "Parmi les causes de syncope" in p  # stem counter-example present


def test_trailing_anchor_in_detect_output():
    content = json.dumps([{"anchor_num": 12, "cas_label": "CAS CLINIQUE",
                           "cas_text": TRAILING_NARRATIVE,
                           "anchor_text_clean": None,
                           "note": "page ends with narrative"}])
    a = analyzer_for(content)
    m = a._detect_cc_sequential_page(
        "Q11. ... derniÃ¨re question\n" + TRAILING_NARRATIVE,
        [7, 8, 9, 10, 11])
    assert m["_trailing"]["text"] == TRAILING_NARRATIVE


# â”€â”€ anchor_text_clean / detector note application â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _analyzer():
    return Step3Metadata.__new__(Step3Metadata)


def test_apply_anchor_extras_writes_clean_text_and_note():
    qcms = [{"uid": "u", "page": 1, "number": 4,
             "text": "Salma, 56 ans... Parmi les propositions ?"}]
    cc_map = {4: {"status": "new_case", "label": "CAS CLINIQUE",
                  "text": "Salma, 56 ans...",
                  "anchor_text_clean": "Parmi les propositions suivantes ?",
                  "detector_note": "patient narrative"}}
    _analyzer()._apply_anchor_extras(qcms, cc_map)
    assert qcms[0]["text"] == "Parmi les propositions suivantes ?"
    assert qcms[0]["cc_detector_note"] == "detector: patient narrative"
    # never conflated with the checker's own column
    assert "case_belonging_check" not in qcms[0]


def test_apply_anchor_extras_null_clean_runs_cas_text_split():
    from modules.step3_metadata import Step3Metadata as MA
    qcms = [{"uid": "u", "page": 1, "number": 4,
             "text": "Madame Benali, 62 ans, diabetique. Parmi les propositions "
                     "suivantes, la quel est vraie ?",
             "cas": "CAS CLINIQUE\r\nMadame Benali, 62 ans, diabetique."}]
    cc_map = {4: {"status": "new_case", "label": "CAS CLINIQUE",
                  "text": "Madame Benali, 62 ans, diabetique."}}
    MA._apply_anchor_extras(MA, qcms, cc_map)
    assert "Madame Benali" not in qcms[0]["text"]
    assert "Parmi les propositions" in qcms[0]["text"]


# â”€â”€ Num predicate â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_log_num_gap_warns_on_gap(capsys):
    from modules.step3_metadata import Step3Metadata as MA
    MA._log_num_gap(11, [15, 16])   # numbering gap — warn
    out = capsys.readouterr().out
    assert "Num gap" in out
    MA._log_num_gap(11, [12, 13])   # contiguous — silent
    assert "Num gap" not in capsys.readouterr().out


# â”€â”€ End-to-end: trailing â†’ pending â†’ merged "Num" claim â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

import os  # noqa: E402


def test_end_to_end_trailing_links_next_page_first_num(monkeypatch, tmp_path):
    """The user-required behavior: a case at the END of page 1 (zero QCMs
    after it) is linked to the NEXT page's first QCM based on the merged
    JSON's "Num" â€” and the checker-grade chain then forms on the right
    members. Drives _process_qcms over the merged all_qcms.json path."""
    import modules.step3_metadata as S3
    from modules.step3_metadata import Step3Metadata

    step2 = tmp_path / "step2_qcm" / "accepted"
    step2.mkdir(parents=True)
    step1 = tmp_path / "step1"
    step1.mkdir()

    # Page 1: QCMs 7..11, then the trailing narrative (no QCM after it).
    page1_text = "\n".join(
        [f"Q{n}. Question normale {n}\nA. a\nB. b\n" for n in range(7, 12)]
        + [TRAILING_NARRATIVE])
    # Page 2: the claiming QCM (Num 12) and its chain member (Num 13).
    page2_text = ("Q12. Quelles sont les complications attendues ?\nA. a\nB. b\n"
                  "Q13. Quelle est la suite de la prise en charge ?\nA. a\nB. b\n")
    (step1 / "page_1.txt").write_text(page1_text, encoding="utf-8")
    (step1 / "page_2.txt").write_text(page2_text, encoding="utf-8")

    qcms_page1 = [{"uid": f"u{n}", "page": 1, "Num": n,
                   "text": f"Question normale {n}"} for n in range(7, 12)]
    qcms_page2 = [{"uid": "u12", "page": 2, "Num": 12,
                   "text": "Quelles sont les complications attendues ?"},
                  {"uid": "u13", "page": 2, "Num": 13,
                   "text": "Quelle est la suite de la prise en charge ?"}]
    (step2 / "all_qcms.json").write_text(
        json.dumps(qcms_page1 + qcms_page2), encoding="utf-8")

    responses = [
        # page 1 call: anchor at max(7..11)+1 = 12 â†’ routed to _trailing
        json.dumps([{"anchor_num": 12, "cas_label": "CAS CLINIQUE",
                     "cas_text": TRAILING_NARRATIVE,
                     "anchor_text_clean": None,
                     "note": "page ends with a narrative"}]),
        # page 2 call: NO new narrative anchors â€” pending resolves instead
        json.dumps([]),
    ]
    calls = []

    class _Resp:
        def __init__(self, script):
            self.script = list(script)

    client = MagicMock()
    it = {"i": 0}

    def gen(prompt, model=None, max_tokens=None, **kw):
        i = it["i"]
        it["i"] += 1
        calls.append({"prompt": prompt, "model": model})
        content = responses[i] if i < len(responses) else "[]"
        return {"content": content,
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "cost": 0.0}

    client.generate_completion.side_effect = gen
    a = Step3Metadata.__new__(Step3Metadata)
    a.context = None
    a.cost_tracker = MagicMock()
    client.generate_completion.side_effect = gen
    client.estimate_cost = lambda model, usage: 0.0
    a.client = client
    from modules.utils.file_manager import FileManager
    a.file_manager = FileManager(base_dir=str(tmp_path))

    monkeypatch.setenv("STEP3_MODEL", "test/primary")
    monkeypatch.setenv("STEP3_FALLBACK_MODEL", "test/fallback")
    a._process_qcms(step2, step1, {"ClinicalCase": "CC"}, {})

    # Two detection calls fired: page 1 (anchor at max+1) and page 2 (pending).
    assert len(calls) == 2
    assert "What IS a clinical case narrative" in calls[0]["prompt"]
    # The page-1 prompt mentions the Num hand-off (V4 requirement).
    assert "Num" in calls[0]["prompt"]

    # Read the saved step-3 output and assert on the MERGED Num keys.
    saved = json.loads((tmp_path / "step3_metadata" / "accepted" /
                        "all_qcms.json").read_text(encoding="utf-8"))
    by_num = {q["Num"]: q for q in saved}

    # THE user requirement: Num 12 (next page's first QCM) carries the case.
    assert TRAILING_NARRATIVE in (by_num[12].get("cas") or "")
    assert by_num[12]["cas"].startswith("CAS CLINIQUE\r\n")
    # distinct cross-page note with the origin page visible
    assert by_num[12]["case_belonging_check"].startswith(
        "new_case (cross-page): narrative from page 1")

