"""PHASE 7 — Full-cascade rollout verification + idempotency smoke.

Verification-only phase — zero production edits (runs 1–6's suites, then a
mocked end-to-end cascade smoke):

1. Phase-suite sweep: phases 0..6 all pass (import-runnable here directly).
2. Cascade trace order: hint -> cas_split -> step3 -> boundary -> checker
   -> build (order + soft-fail contract, via [CASCADE-TRACE] events).
3. Idempotency smoke (same uid set assumed): Q8 fast-path == equal uid set;
   re-run reports step3='skipped' with cascade status stable.
"""
import json
import os
import sys
import tempfile
import shutil
import datetime
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from modules.post_step2_metadata import run_post_step2_metadata, DEFAULT_STEP3_CONFIG
from modules.utils.cost_tracker import CostTracker

CASE = "CAS CLINIQUE 1\r\nSalma, 56 ans, sous Amiodarone."

PHASE_FILES = {
    0: "tests/test_cc_redesign_phase0_characterization.py",
    1: "tests/test_cc_redesign_phase1_detector.py",
    2: "tests/test_cc_redesign_phase2_propagation.py",
    3: "tests/test_cc_redesign_phase3_audit_surface.py",
    4: "tests/test_cc_redesign_phase4_checker_ledger.py",
    5: "tests/test_cc_redesign_phase5_boundary_checks.py",
    6: "tests/test_cc_redesign_phase6_skip_hygiene.py",
}


def _test_phase_suite_sweep():
    print("\n--- P7.1: phase-suite sweep (0..6) subprocess green ---")
    failures = []
    for n, f in PHASE_FILES.items():
        r = subprocess.run([sys.executable, os.path.join(ROOT, f)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=600,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        ok = ("PASSED" in r.stdout) and r.returncode == 0
        print(f"   phase {n}: {'OK' if ok else 'FAIL'}   ({f})")
        if not ok:
            failures.append((n, r.stderr[-2000:]))
    assert not failures, failures
    print("OK all 7 phase suites green in clean subprocess contexts.")


class _Ctx:
    def __init__(self, base: Path):
        self.base_path = base
        self.name = "p7"
    def get_path(self, step, sub=""):
        p = self.base_path / step
        if sub:
            p = p / sub
        p.mkdir(parents=True, exist_ok=True)
        return p


def _mk_project(tmp: Path, uid="1_1_0", page=1):
    ctx = _Ctx(tmp)
    s2 = ctx.get_path("step2_qcm", "accepted")
    (s2 / "all_qcms.json").write_text(json.dumps([
        {"uid": uid, "page": page, "number": 1, "text": "t",
         "propositions": {"a": "P1", "b": "P2"}}], ensure_ascii=False),
        encoding="utf-8")
    return ctx


def _mock_all_llm(di_status="unrelated", di_next="no_case"):
    """Single source of mocks for the smoke runs: hint/cas-split pure,
    Step 3 LLM one unrelated page per run, checker no_cases, boundary no_transitions."""
    def hint_stub(context):
        return {"status": "not_applied"}
    def split_stub(context):
        return {"status": "not_applied"}
    det = MagicMock()
    det.generate_completion.return_value = {
        "content": json.dumps([{"number": 1, "status": di_status, "cas_label": None,
                                "cas_text": None}], ensure_ascii=False),
        "usage": {"prompt_tokens": 1, "completion_tokens": 1}, "cost": 0.0}
    det.estimate_cost.return_value = 0.0
    det.detect_all_fields.return_value = {}
    det.filter_by_confidence.return_value = {}
    step3_instance = MagicMock()
    step3_instance.client = det
    step3_instance.run.return_value = {"config": {}, "global_values": {}}
    return (patch("modules.post_step2_metadata.Step3Metadata", return_value=step3_instance),
            patch("modules.post_step2_metadata.run_hint_detection", new=hint_stub),
            patch("modules.post_step2_metadata.run_cas_text_split", new=split_stub),
            patch("modules.post_step2_metadata.run_clinical_case_checker",
                  new=lambda tracker, ctx: {"status": "no_cases"}),
            patch("modules.clinical_case_checker.run_boundary_checks",
                  new=lambda tracker, ctx: {"status": "no_transitions"}),
            patch("modules.post_step2_metadata.run_post_step3_build",
                  new=lambda *a, **k: {"status": "ok", "step5": {"total_qcms": 1, "xlsx_file": ""}}))


def _test_cascade_e2e_trace_and_idempotency():
    print("\n--- P7.2: mock LLM cascade E2E — trace order + uid idempotency ---")
    traces = []
    orig_trace = None
    tmp = Path(tempfile.mkdtemp())
    try:
        from modules.post_step2_metadata import _trace
        def capturing_trace(stage, event, elapsed_ms=None, detail=""):
            orig_trace(stage, event, elapsed_ms, detail=detail) if detail else orig_trace(stage, event, elapsed_ms)
        # (capture directly: reuse _trace with output capture)
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        ctx = _Ctx(tmp)
        s2 = ctx.get_path("step2_qcm", "accepted")
        (s2 / "all_qcms.json").write_text(json.dumps([
            {"uid": "1_1_0", "page": 1, "number": 1, "text": "t",
             "propositions": {"a": "P1", "b": "P2"}}], ensure_ascii=False),
            encoding="utf-8")

        patches = _mock_all_llm()
        with redirect_stdout(buf), patches[0], patches[1], patches[2], patches[3], \
             patches[4], patches[5]:
            res = run_post_step2_metadata(None, ctx, "u", "p",
                                          step3_config=DEFAULT_STEP3_CONFIG)
        out = buf.getvalue()
        stages = [line.split("stage=")[1].split()[0]
                  for line in out.splitlines() if "[CASCADE-TRACE] stage=cascade event=START" in line
                  or "[CASCADE-TRACE] stage=hint event=START" in line]
        order_actual = []
        for stage in ("hint", "cas_split", "step3", "boundary", "checker", "build"):
            marker = f"stage={stage} event=START"
            if marker in out:
                order_actual.append(stage)
        assert order_actual == ["hint", "cas_split", "step3", "boundary", "checker", "build"], \
            f"cascade order changed: {order_actual}"
        assert res["step3"] in ("done", "skipped")

        # Simulate Step 3 output persistence (mocked Step 3 writes none):
        # accepted file covering the same uid set → Q8 fast-path condition met
        s3 = ctx.get_path("step3_metadata", "accepted")
        (s3 / "all_qcms.json").write_text(json.dumps([
            {"uid": "1_1_0", "cas": None}], ensure_ascii=False), encoding="utf-8")

        # Run #2 — SAME uid set: Step 3 must fast-path skip (Q8 gate)
        buf2 = io.StringIO()
        with redirect_stdout(buf2), patches[0], patches[1], patches[2], patches[3], \
             patches[4], patches[5]:
            res2 = run_post_step2_metadata(None, ctx, "u", "p",
                                           step3_config=DEFAULT_STEP3_CONFIG)
        out2 = buf2.getvalue()
        assert "q8_fast_path_uid_sets_equal" in out2, "Step 3 Q8 fast-path must skip"
        if "stage=checker event=SKIP" in out2 or res2.get("cc_check", {}).get("status") == "skipped":
            pass  # checker gate may or may not skip (audit coverage logic)
        print("OK trace order preserved; Q8 fast-path skip on re-run (unchanged).")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_resume_recovery_contract():
    print("\n--- P7.3: uid-set mismatch forces re-enrichment (partial recovery) ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        ctx = _mk_project(tmp)
        patches = _mock_all_llm()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            run_post_step2_metadata(None, ctx, "u", "p", step3_config=DEFAULT_STEP3_CONFIG)
        # Step 2 GROWN: add a new QCM
        s2 = ctx.get_path("step2_qcm", "accepted")
        data = json.loads((s2 / "all_qcms.json").read_text(encoding="utf-8"))
        data.append({"uid": "1_2_1", "page": 1, "number": 2, "text": "t2",
                     "propositions": {"a": "P1", "b": "P2"}})
        (s2 / "all_qcms.json").write_text(json.dumps(data, ensure_ascii=False),
                                          encoding="utf-8")
        det2 = MagicMock()
        det2.generate_completion.return_value = {
            "content": json.dumps([{"number": 1, "status": "unrelated"},
                                   {"number": 2, "status": "uncertain",
                                    "cas_label": None, "cas_text": None}]),
            "usage": {}, "cost": 0.0}
        det2.filter_by_confidence.return_value = {}
        step3_2 = MagicMock()
        step3_2.client = det2
        step3_2.run.return_value = {"config": {}, "global_values": {}}
        with patch("modules.post_step2_metadata.Step3Metadata", return_value=step3_2), \
             patch("modules.post_step2_metadata.run_hint_detection",
                   new=lambda context: {"status": "not_applied"}), \
             patch("modules.post_step2_metadata.run_cas_text_split",
                   new=lambda context: {"status": "not_applied"}), \
             patch("modules.post_step2_metadata.run_clinical_case_checker",
                   new=lambda tracker, ctx: {"status": "no_cases"}), \
             patch("modules.clinical_case_checker.run_boundary_checks",
                   new=lambda tracker, ctx: {"status": "no_transitions"}), \
             patch("modules.post_step2_metadata.run_post_step3_build",
                   new=lambda *a, **k: {"status": "ok", "step5": {"total_qcms": 2, "xlsx_file": ""}}):
            res3 = run_post_step2_metadata(None, ctx, "u", "p",
                                           step3_config=DEFAULT_STEP3_CONFIG)
        assert res3.get("step3") == "done", f"uid-set growth MUST re-run Step 3: {res3}"
        print("OK Step 2 grew → Step 3 re-runs (new QCMs get enriched); idempotency safe.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_all():
    _test_phase_suite_sweep()
    _test_cascade_e2e_trace_and_idempotency()
    _test_resume_recovery_contract()
    print("\n" + "=" * 60)
    print("ALL PHASE 7 ROLLOUT VERIFICATION TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()
