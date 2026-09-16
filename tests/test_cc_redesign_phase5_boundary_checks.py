"""PHASE 5 — bounded boundary check (`ends_here` reconciliation) tests.

Acceptance from the phased plan, Phase 5:
- One verification call per transition (per case-ending, NOT per QCM volume)
- Boundary QCM resolution: the entry immediately AFTER the trigger, cross-file
- Skips without calls: no following QCM; boundary already linked elsewhere
- YES ⇒ `cas` re-attached + note; NO/unresolved ⇒ unlink stands + note; no
  relink ever on technical failure
- Re-attached QCMs then carry cas (join normal chain building organically)
- Idempotency: same transitions + same uid set -> second run skipped
- Cascade wiring: Step 3's queue consumed; boundary runs between Step 3 and
  the checker; a boundary failure never blocks the cascade (soft-fail)
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from modules.clinical_case_checker import (
    run_boundary_checks, run_clinical_case_checker,
    BOUNDARY_QUEUE_FILENAME, BOUNDARY_AUDIT_FILENAME,
)
from modules.post_step2_metadata import run_post_step2_metadata
from modules.step3_metadata import Step3Metadata
from modules.utils.cost_tracker import CostTracker

CASE = "CAS CLINIQUE 1\r\nSalma, 56 ans, sous Amiodarone, ictère fébrile."


def _q(uid, number, text="Q ?", cas=None, page=1):
    d = {"uid": uid, "page": page, "number": number, "text": text,
         "propositions": {"a": "P1", "b": "P2"}}
    if cas:
        d["cas"] = cas
    return d


class _Ctx:
    def __init__(self, base: Path):
        self.base_path = base
        self.name = "p5"
    def get_path(self, step, sub=""):
        p = self.base_path / step
        if sub:
            p = p / sub
        p.mkdir(parents=True, exist_ok=True)
        return p


def _seed(tmp: Path):
    d = tmp / "step3_metadata" / "accepted"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_queue(tmp: Path, transitions):
    root = tmp / "step3_metadata"
    root.mkdir(parents=True, exist_ok=True)
    (root / BOUNDARY_QUEUE_FILENAME).write_text(
        json.dumps({"transitions": transitions}, ensure_ascii=False), encoding="utf-8")


def _client(plan):
    c = MagicMock()
    it = iter(plan)
    async def gen(prompt, **kw):
        try:
            applies = next(it)
        except StopIteration:
            applies = "fail"
        if applies == "fail":
            raise RuntimeError("dead provider")
        return {"content": json.dumps({"applies": applies, "confidence": 0.9}),
                "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "cost": 0.0}
    c.generate_completion_async = AsyncMock(side_effect=gen)
    return c


def _test_boundary_relink():
    print("\n--- P5.1: YES boundary verdict re-attaches cas ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        d = _seed(tmp)
        (d / "page_1.json").write_text(json.dumps([
            _q("u1", 1, "Q1", cas=CASE), _q("u2", 2, "Q2", cas=CASE),
            _q("u3", 3, "Q3"),   # the ends_here trigger
            _q("u4", 4, "Q4"),   # boundary QCM — carries NO cas
        ], ensure_ascii=False), encoding="utf-8")
        root = tmp / "step3_metadata"
        (root / BOUNDARY_QUEUE_FILENAME).write_text(json.dumps({"transitions": [
            {"case_cas": CASE, "trigger_page": 1, "trigger_number": 3, "trigger_uid": "u3"},
            {"case_cas": CASE, "trigger_page": 1, "trigger_number": 12, "trigger_uid": "zz"},
        ]}), encoding="utf-8")

        client = _client([True])   # only the resolvable transition gets a call
        with patch("modules.clinical_case_checker.OpenRouterClient", return_value=client):
            res = run_boundary_checks(MagicMock(), _Ctx(tmp))
        assert res["status"] == "ok", res
        assert res["stats"]["calls"] == 1, res["stats"]      # one call per CALLABLE transition
        assert res["stats"]["no_trigger"] == 1
        data = json.loads((d / "page_1.json").read_text(encoding="utf-8"))
        b = [q for q in data if q["uid"] == "u4"][0]
        assert b["cas"] == CASE, "cas re-attached on confirmed boundary"
        assert b["case_belonging_check"].startswith("boundary re-check YES")
        assert data[2].get("cas") is None, "trigger stays unlinked"
        print("OK bounded call; re-attached; trigger note untouched.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_boundary_no_and_unresolved():
    print("\n--- P5.2: NO and unresolved never relink ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        d = _seed(tmp)
        (d / "page_1.json").write_text(json.dumps([
            _q("u1", 1, "Q1", cas=CASE),
            _q("u2", 2, "Q2"),               # boundary of T1 -> plan says NO
            _q("u3", 3, "Q3", cas=CASE),
            _q("u4", 4, "Q4"),               # END of T2 -> provider dead (unresolved)
            _q("u5", 5, "Q5"),               # boundary of T2
        ], ensure_ascii=False), encoding="utf-8")
        root = tmp / "step3_metadata"
        (root / BOUNDARY_QUEUE_FILENAME).write_text(json.dumps({"transitions": [
            {"case_cas": CASE, "trigger_page": 1, "trigger_number": 1, "trigger_uid": "u1"},
            {"case_cas": CASE, "trigger_page": 1, "trigger_number": 3, "trigger_uid": "u3"},
        ]}), encoding="utf-8")
        # plan: [fallback? none -> NO resolved], [both models fail -> unresolved]
        client = _client([False, "fail", "fail"])
        with patch("modules.clinical_case_checker.OpenRouterClient", return_value=client):
            res = run_boundary_checks(MagicMock(), _Ctx(tmp))
        assert res["stats"]["no_relink"] == 1 and res["stats"]["unresolved"] == 1
        data = json.loads((d / "page_1.json").read_text(encoding="utf-8"))
        u2 = [q for q in data if q["uid"] == "u2"][0]
        u4 = [q for q in data if q["uid"] == "u4"][0]
        assert "cas" not in u2 and u2["case_belonging_check"].startswith("boundary re-check NO")
        assert "cas" not in u4 and "failure" in u4["case_belonging_check"]
        print("OK NO/unresolved keep the unlink; notes recorded.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_resolvers_no_call_cases():
    print("\n--- P5.3: skip cases burn ZERO calls ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        d = _seed(tmp)
        # trigger LAST in doc (page_2.json final QCM) + boundary already linked
        (d / "page_1.json").write_text(json.dumps([
            _q("u1", 1, "Q1", cas=CASE), _q("u2", 2, "Q2", cas=CASE),  # boundary already linked
        ], ensure_ascii=False), encoding="utf-8")
        (d / "page_2.json").write_text(json.dumps([_q("u3", 5, "Q5", cas=CASE)]),
                                       encoding="utf-8")
        root = tmp / "step3_metadata"
        (root / BOUNDARY_QUEUE_FILENAME).write_text(json.dumps({"transitions": [
            {"case_cas": CASE, "trigger_page": 1, "trigger_number": 1, "trigger_uid": "u1"},
            {"case_cas": CASE, "trigger_page": 2, "trigger_number": 5, "trigger_uid": "u3"},
        ]}), encoding="utf-8")
        client = _client([])   # would explode on any call
        with patch("modules.clinical_case_checker.OpenRouterClient", return_value=client):
            res = run_boundary_checks(MagicMock(), _Ctx(tmp))
        assert res["stats"]["calls"] == 0, res
        assert res["stats"]["already_linked"] == 1
        assert res["stats"]["no_following_qcm"] == 1
        client.generate_completion_async.assert_not_called()
        print("OK already_linked + last-of-document consume no verify calls.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_cross_file_resolution():
    print("\n--- P5.4: boundary after a page break resolves cross-file ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        d = _seed(tmp)
        (d / "page_1.json").write_text(json.dumps([
            _q("u1", 1, "Q1", cas=CASE), _q("u2", 2, "Q2"),   # ends_here at last of p1
        ]), encoding="utf-8")
        (d / "page_2.json").write_text(json.dumps([
            _q("u3", 3, "Q3"),   # FIRST of the next file = the boundary
        ]), encoding="utf-8")
        root = tmp / "step3_metadata"
        (root / BOUNDARY_QUEUE_FILENAME).write_text(json.dumps({"transitions": [
            {"case_cas": CASE, "trigger_page": 1, "trigger_number": 2, "trigger_uid": "u2"},
        ]}), encoding="utf-8")
        client = _client([True])
        with patch("modules.clinical_case_checker.OpenRouterClient", return_value=client):
            prompts_seen = []
            async def capture(prompt, **kw):
                prompts_seen.append(prompt)
                return {"content": json.dumps({"applies": True, "confidence": 0.8}),
                        "usage": {}, "cost": 0.0}
            client.generate_completion_async = AsyncMock(side_effect=capture)
            res = run_boundary_checks(MagicMock(), _Ctx(tmp))
        assert res["stats"]["relinked"] == 1, res
        data2 = json.loads((d / "page_2.json").read_text(encoding="utf-8"))
        assert data2[0]["cas"] == CASE, "cross-file boundary QCM re-linked"
        assert "Q3" in prompts_seen[0], "the boundary QCM (u3) was the one verified"
        print("OK narrative→next-page leak is caught by the boundary check.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_idempotent_skip():
    print("\n--- P5.5: identical re-run is skipped ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        d = _seed(tmp)
        (d / "page_1.json").write_text(json.dumps([
            _q("u1", 1, "Q1", cas=CASE), _q("u2", 2, "Q2"),
        ], ensure_ascii=False), encoding="utf-8")
        root = tmp / "step3_metadata"
        (root / BOUNDARY_QUEUE_FILENAME).write_text(json.dumps({"transitions": [
            {"case_cas": CASE, "trigger_page": 1, "trigger_number": 1, "trigger_uid": "u1"},
        ]}), encoding="utf-8")
        client = _client([True])
        with patch("modules.clinical_case_checker.OpenRouterClient", return_value=client):
            first = run_boundary_checks(MagicMock(), _Ctx(tmp))
            second = run_boundary_checks(MagicMock(), _Ctx(tmp))
        assert first["status"] == "ok" and second["status"] == "skipped", (first, second)
        print("OK same queue + same QCM set → skip (no double relinks).")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_step3_writes_queue():
    print("\n--- P5.6: Step 3 persists the transition queue file ---")
    sm = Step3Metadata(CostTracker())
    try:
        with patch.object(sm, "context", None):
            pass
        # direct unit call: _save_boundary_transitions
        sm2 = Step3Metadata(CostTracker())
        import tempfile, shutil as _sh
        t2 = Path(tempfile.mkdtemp())
        try:
            class C(_Ctx):
                pass
            sm2.context = C(t2)
            sm2._save_boundary_transitions([
                {"case_cas": CASE, "trigger_page": 3, "trigger_number": 7,
                 "trigger_uid": "u9"}])
            f = (t2 / "step3_metadata" / BOUNDARY_QUEUE_FILENAME)
            q = json.loads(f.read_text(encoding="utf-8"))
            assert q["transitions"][0]["trigger_number"] == 7
        finally:
            _sh.rmtree(t2, ignore_errors=True)
        print("OK queue persisted at step3_metadata root (not accepted/).")
    finally:
        pass


def _test_cascade_order_and_soft_fail():
    print("\n--- P5.7: cascade fires boundary BETWEEN step3 and checker; soft-fail ---")
    order = []
    tmp = Path(tempfile.mkdtemp())
    try:
        from unittest.mock import patch as _p
        def fake_boundary(tracker, context):
            order.append("boundary")
            return {"status": "no_transitions"}
        def fake_checker(tracker, context):
            order.append("checker")
            return {"status": "no_cases"}
        ctx = _Ctx(tmp)
        # minimal accepted step2 data
        s2 = ctx.get_path("step2_qcm", "accepted")
        (s2 / "all_qcms.json").write_text(json.dumps([
            {"uid": "1_1_0", "page": 1, "number": 1, "text": "t",
             "propositions": {"a": "x"}}]), encoding="utf-8")
        with _p("modules.post_step2_metadata.Step3Metadata"), \
             _p("modules.clinical_case_checker.run_boundary_checks", new=fake_boundary), \
             _p("modules.clinical_case_checker.run_clinical_case_checker", new=fake_checker), \
             _p("modules.post_step2_metadata.run_clinical_case_checker", new=fake_checker), \
             _p("modules.post_step2_metadata.run_post_step3_build",
                new=lambda *a, **k: {"status": "ok", "step5": {"total_qcms": 1, "xlsx_file": ""}}), \
             _p("modules.post_step2_metadata.run_hint_detection",
                new=lambda context: {"status": "not_applicable"}), \
             _p("modules.post_step2_metadata.run_cas_text_split",
                new=lambda context: {"status": "not_applicable"}):
            res = run_post_step2_metadata(None, ctx, "u", "p",
                                          step3_config={"fields": {"clinical_case": {"strategy": "per_group"}}})
        assert order == ["boundary", "checker"], order
        assert res["boundary"]["status"] == "no_transitions"
        print("OK boundary runs after Step 3, before the checker.")

        # soft-fail: a boundary error must NOT block checker/build
        order2 = []
        def exploding_boundary(tracker, context):
            order2.append("boundary")
            raise RuntimeError("boom")
        ctx2 = _Ctx(Path(tempfile.mkdtemp()))
        s2b = ctx2.get_path("step2_qcm", "accepted")
        (s2b / "all_qcms.json").write_text(json.dumps([
            {"uid": "1_1_0", "page": 1, "number": 1, "text": "t",
             "propositions": {"a": "x"}}]), encoding="utf-8")
        def fake_checker2(tracker, context):
            order2.append("checker")
            return {"status": "no_cases"}
        with _p("modules.post_step2_metadata.Step3Metadata"), \
             _p("modules.clinical_case_checker.run_boundary_checks", new=exploding_boundary), \
             _p("modules.post_step2_metadata.run_clinical_case_checker", new=fake_checker2), \
             _p("modules.post_step2_metadata.run_hint_detection",
                new=lambda context: {"status": "not_applicable"}), \
             _p("modules.post_step2_metadata.run_cas_text_split",
                new=lambda context: {"status": "not_applicable"}):
            res2 = run_post_step2_metadata(None, ctx2, "u", "p",
                                           step3_config={"fields": {"clinical_case": {"strategy": "per_group"}}})
        assert order2 == ["boundary", "checker"], order2
        assert res2["boundary"]["status"] == "error"
        # soft-fail contract: the checker still ran despite the boundary error
        assert res2["cc_check"]["status"] == "no_cases", res2
        print("OK boundary failure never blocks the cascade (soft-fail contract).")
    finally:
        import shutil as _s
        _s.rmtree(tmp, ignore_errors=True)


def _run_all():
    _test_boundary_relink()
    _test_boundary_no_and_unresolved()
    _test_resolvers_no_call_cases()
    _test_cross_file_resolution()
    _test_idempotent_skip()
    _test_step3_writes_queue()
    _test_cascade_order_and_soft_fail()
    print("\n" + "=" * 60)
    print("ALL PHASE 5 BOUNDARY CHECK TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()
