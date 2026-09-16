"""Cross-page trailing-narrative fix (CC_CROSS_PAGE_NARRATIVE_FIX_PLAN) tests.

Scenarios from the plan, all through the REAL `_process_qcms` merged path
with a mocked client:
1a  narrative at end of page N (zero QCMs) -> page N+1's QCM CLAIMS it
    (claims_pending_case: true) -> cas attached with the DISTINCT cross-page
    note in case_belonging_check.
1b  the pending candidate survives QCM-free middle pages (no re-affirmation,
    OQ-3 decision A) and resolves at the first QCM-bearing page.
1c  decline: the next page's QCM is unrelated -> candidate dropped
    permanently — a LATER page can no longer claim it; decline note on the
    deciding QCM only (per_group).
Regressions:
R1  normal same-page new_case note unchanged ("new_case: <label> starts
    this case").
R2  page with truly no narrative (and zero QCMs) creates NO pending.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from cc_redesign_fixtures import status_response
from modules.utils.cost_tracker import CostTracker
from modules.step3_metadata import Step3Metadata

NARR = "Salma, 56 ans, sous Amiodarone depuis 3 ans, presente un ictere febrile."

def _q(uid, number, text="Q ?", page=1):
    return {"uid": uid, "page": page, "number": number, "text": text,
            "propositions": {"a": "P1", "b": "P2"}}


def _make():
    return Step3Metadata(CostTracker())


def _seed(tmp: Path, qcms, page_texts: dict):
    s1 = tmp / "step1_extraction" / "accepted"; s1.mkdir(parents=True, exist_ok=True)
    for page_num, text in page_texts.items():
        (s1 / f"page_{page_num}.txt").write_text(text, encoding="utf-8")
    s2 = tmp / "step2_qcm" / "accepted"; s2.mkdir(parents=True, exist_ok=True)
    (s2 / "all_qcms.json").write_text(json.dumps(qcms, ensure_ascii=False),
                                      encoding="utf-8")
    return str(s2), str(s1)


def _run(tmp: Path, qcms, page_texts, client):
    sm = _make()
    s2, s1 = _seed(tmp, qcms, page_texts)
    with patch.object(sm, "client", client):
        sm.run(step2_dir=s2, step1_dir=s1, auto_mode=True,
               config={"year": {"strategy": "skip"},
                       "clinical_case": {"strategy": "per_group"}})
    return sm, json.loads(
        (Path(ROOT) / "output" / "step3_metadata" / "accepted" / "all_qcms.json")
        .read_text(encoding="utf-8"))


def _client(responses):
    """responses: list of dicts (status_response outputs) consumed per page, in
    page order."""
    it = iter(responses)
    calls = []

    class _P:
        def generate_completion(self, prompt, model=None, max_tokens=None, **kw):
            calls.append(prompt)
            try:
                r = next(it)
            except StopIteration:
                r = status_response([])
            return dict(r)
        @staticmethod
        def estimate_cost(model, usage):
            return 0.0

    return _P(), calls


def _cleanup():
    shutil.rmtree(os.path.join(ROOT, "output", "step3_metadata"), ignore_errors=True)


def _scenario_1a():
    print("\n--- H-1a: trailing narrative on a QCM-free page, claimed next page ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        qcms = [_q("2_1_0", 1, page=2)]   # the QCM lives entirely on the NEXT page
        page_texts = {1: f"{NARR}\n\n(blank page footer)", 2: "Q1. Question?\nA. p1\n"}
        r1 = status_response([], trailing={"label": "CAS CLINIQUE 1", "text": NARR})
        r2 = status_response([
            {"number": 1, "status": "continues", "cas_label": None,
             "cas_text": None, "claims_pending_case": True}])
        proxy, calls = _client([r1, r2])
        _sm, saved = _seed_run(tmp, qcms, page_texts, proxy)
        assert len(calls) == 2, f"expected 2 page calls: {len(calls)}"

        # page-1 call is QA-free (zero QCM numbers listed)
        assert "none — this page holds no numbered questions" in calls[0]
        # page-2 prompt embeds the PENDING CASE block
        assert "PENDING CASE" in calls[1] and "Salma" in calls[1]

        q = saved[0]
        assert q["cas"].startswith("CAS CLINIQUE 1\r\n"), q.get("cas")
        assert q["cas"].endswith(NARR), repr(q["cas"])
        # DISTINCT cross-page note (not the same-page wording)
        note = q["case_belonging_check"]
        assert "cross-page" in note and "claimed by this question" in note
        assert "narrative from page 1" in note
        print("OK 1a: pending created by the narrative-only page; claimed next page.")
    finally:
        _cleanup()


def _seed_run(tmp, qcms, page_texts, proxy):
    sm = _make()
    s2, s1 = _seed(tmp, qcms, page_texts)
    with patch.object(sm, "client", proxy):
        sm.run(step2_dir=s2, step1_dir=s1, auto_mode=True,
               config={"year": {"strategy": "skip"},
                       "clinical_case": {"strategy": "per_group"}})
    saved = json.loads((Path(ROOT) / "output" / "step3_metadata" / "accepted" / "all_qcms.json")
                       .read_text(encoding="utf-8"))
    return sm, saved


def _scenario_1b():
    print("\n--- H-1b: pending survives QCM-free pages before the first QCM ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        qcms = [_q("3_1_0", 1, page=3)]
        page_texts = {1: f"{NARR}", 2: "rien ici", 3: "Q1. Question?\nA. p\n"}
        r1 = status_response([], trailing={"label": "CAS CLINIQUE 1", "text": NARR})
        r2 = status_response([])                       # middle QCM-free page: no narrative
        r3 = status_response([
            {"number": 1, "status": "continues", "cas_label": None,
             "cas_text": None, "claims_pending_case": True}])
        proxy, calls = _client([r1, r2, r3])
        _sm, saved = _seed_run(tmp, qcms, page_texts, proxy)
        assert len(calls) == 3, len(calls)
        q = saved[0]
        assert q["cas"].startswith("CAS CLINIQUE 1\r\n"), q.get("cas")
        assert "narrative from page 1" in q["case_belonging_check"]
        print("OK 1b: pending persisted across the QCM-free middle page (re-affirmation-free).")
    finally:
        _cleanup()


def _scenario_1c():
    print("\n--- H-1c: decline — candidate dropped permanently, never retried ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        qcms = [_q("2_1_0", 1, page=2), _q("3_2_0", 2, page=3)]
        page_texts = {1: f"{NARR}",
                      2: "Q1. Independent question?\nA. p\n",
                      3: "Q2. Another independent question?\nA. p\n"}
        r1 = status_response([], trailing={"label": "CAS CLINIQUE 1", "text": NARR})
        r2 = status_response([{"number": 1, "status": "unrelated", "cas_label": None,
                               "cas_text": None}])
        # the LATER page never claimed the narrative (pending is gone anyway)
        r3 = status_response([{"number": 2, "status": "unrelated", "cas_label": None,
                               "cas_text": None}])
        proxy, calls = _client([r1, r2, r3])
        _sm, saved = _seed_run(tmp, qcms, page_texts, proxy)
        q2 = [x for x in saved if x.get("page") == 2][0]
        q3 = [x for x in saved if x.get("page") == 3][0]
        assert "cas" not in q2 and "cas" not in q3
        note = q2["case_belonging_check"]
        assert "declined" in note and "candidate dropped" in note, note
        assert "cross-page" in note
        assert "case_belonging_check" not in q3 or "claim" not in q3["case_belonging_check"]
        assert "narrative from page 1" not in q3.get("case_belonging_check", "")
        print("OK 1c: offered once, declined, candidate never retried on page 3.")
    finally:
        _cleanup()


def _regression_same_page():
    print("\n--- Regression A: ordinary same-page new_case is byte-identical ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        qcms = [_q("5_1_0", 1, page=5)]
        page_texts = {5: f"CAS CLINIQUE 1 :\n1/ {NARR}\nQ1. Question?\nA. p\n"}
        r1 = status_response([
            {"number": 1, "status": "new_case", "cas_label": "CAS CLINIQUE 1",
             "cas_text": NARR}])
        proxy, calls = _client([r1])
        _sm, saved = _seed_run(tmp, qcms, page_texts, proxy)
        q = saved[0]
        assert q["cas"] == "CAS CLINIQUE 1\r\n" + NARR, q.get("cas")
        assert q["case_belonging_check"].startswith("new_case:"), q["case_belonging_check"]
        assert "cross-page" not in q["case_belonging_check"], "same-page note unchanged"
        print("OK same-page trigger note unchanged (no cross-page marker).")
    finally:
        _cleanup()


def _regression_no_narrative():
    print("\n--- Regression B: a page with no narrative at all creates no pending ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        qcms = [_q("6_1_0", 1, page=6)]
        page_texts = {6: "Q1. Question?\nA. p\n"}
        r1 = status_response([{"number": 1, "status": "unrelated", "cas_label": None,
                               "cas_text": None}], trailing=None)
        proxy, calls = _client([r1])
        _sm, saved = _seed_run(tmp, qcms, page_texts, proxy)
        q = saved[0]
        assert "cas" not in q
        assert "case_belonging_check" not in q, "no pending was ever created"
        print("OK no narrative -> no pending, no note, no cas.")
    finally:
        _cleanup()


def _run_all():
    _scenario_1a()
    _scenario_1b()
    _scenario_1c()
    _regression_same_page()
    _regression_no_narrative()
    print("\n" + "=" * 60)
    print("ALL CROSS-PAGE NARRATIVE TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()
