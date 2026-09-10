"""Tests for the Phase 1 Clinical Case Checker (modules/clinical_case_checker.py)
and its wiring inside run_post_step2_metadata.

Covers the Phase 1 contract (antigravity_redo_phases.md + clinical_case_checker.md):
- Chain building over cascaded `cas` fields (consecutive same-case runs)
- One simple verification question per QCM in every chain (cheap model)
- applies=false  -> that QCM ONLY is unlinked (cas removed), rest of chain kept
- LLM failure    -> decision stays "unresolved"; linkage KEPT (never a silent
                    rejection); all-calls-failed flags status=error
- Idempotency: re-run over the same uid set is skipped
- Strategy gating in the cascade: runs only for clinical_case=per_group
- Soft-fail: a checker error never blocks the Step 4/5 build
"""
import os
import sys
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Force UTF-8 on Windows
sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))

from modules.utils.cost_tracker import CostTracker
from modules.clinical_case_checker import (
    run_clinical_case_checker,
    _build_chains,
    _parse_verdict,
    VERIFICATION_FILENAME,
)
from modules.post_step2_metadata import run_post_step2_metadata, DEFAULT_STEP3_CONFIG


class FakeContext:
    """Minimal ProjectContext stand-in backed by a temp directory."""

    def __init__(self, base: Path):
        self.base_path = base
        self.name = "testproj"

    def get_path(self, step: str, sub: str = "") -> Path:
        p = self.base_path / step
        if sub:
            p = p / sub
        p.mkdir(parents=True, exist_ok=True)
        return p


def _seed_step3(ctx: FakeContext, filename: str, qcms: list):
    d = ctx.get_path("step3_metadata", "accepted")
    (d / filename).write_text(json.dumps(qcms), encoding="utf-8")


def _ok(applies: bool, confidence: float = 0.95) -> dict:
    return {"content": json.dumps({"applies": applies, "confidence": confidence}),
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "cost": 0.0}


def _mock_client_by_question(responses: dict, default_applies=True):
    """OpenRouterClient mock: inspect the prompt's QUESTION block and answer
    from the `responses` {question_text: bool} map."""
    client = MagicMock()
    def gen(prompt, **kw):
        for qtext, applies in responses.items():
            if qtext in prompt:
                return _ok(applies)
        return _ok(default_applies)
    client.generate_completion = MagicMock(side_effect=gen)
    return client


# ─────────────────────────────────────────────────────────────────────────────
# Pure-logic tests
# ─────────────────────────────────────────────────────────────────────────────

def _test_parse_verdict_variants():
    print("\n--- Test 1: _parse_verdict variants ---")
    assert _parse_verdict('{"applies": true, "confidence": 0.9}') == {"applies": True, "confidence": 0.9}
    assert _parse_verdict('```json\n{"applies": false, "confidence": 0.8}\n```') == {"applies": False, "confidence": 0.8}
    assert _parse_verdict('noise {"applies": "true"} noise') == {"applies": True, "confidence": None}
    assert _parse_verdict('{"applies": "false", "confidence": 2.5}') == {"applies": False, "confidence": 1.0}
    assert _parse_verdict('{"confidence": 0.5}') is None          # applies missing
    assert _parse_verdict('no json at all') is None
    assert _parse_verdict('{"applies": "maybe"}') is None         # not a bool
    print("✅ verdict parsing: valid/fenced/lenient/invalid all handled.")


def _test_build_chains():
    print("\n--- Test 2: _build_chains (consecutive same-case runs) ---")
    e = [(Path("f"), q) for q in [
        {"uid": "1"},                                   # no cas
        {"uid": "2", "cas": "CASE A"},                  # chain 1
        {"uid": "3", "cas": "CASE A"},
        {"uid": "4"},                                   # breaks the run
        {"uid": "5", "cas": "CASE A"},                  # SAME text, NEW chain (split)
        {"uid": "6", "cas": "CASE B"},                  # chain 3
        {"uid": "7", "cas": "CASE B"},
    ]]
    chains = _build_chains(e)
    assert len(chains) == 3, f"expected 3 chains, got {len(chains)}"
    assert [c["items"] for c in chains] == [[1, 2], [4], [5, 6]]
    print("✅ chains: consecutive runs split by case-less QCMs and re-occurrences.")


# ─────────────────────────────────────────────────────────────────────────────
# Checker end-to-end (mocked LLM)
# ─────────────────────────────────────────────────────────────────────────────

def _test_no_cases_no_llm():
    print("\n--- Test 3: no `cas` anywhere -> no_cases, zero LLM calls ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        ctx = FakeContext(tmp)
        _seed_step3(ctx, "page_1.json", [{"uid": "1_1_0", "page": 1, "number": 1, "text": "Q1"}])
        with patch("modules.clinical_case_checker.OpenRouterClient") as MockClient:
            res = run_clinical_case_checker(CostTracker(), ctx)
            assert res["status"] == "no_cases", res
            assert MockClient.call_count == 0
        print("✅ no_cases short-circuits before any LLM call.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_chain_verify_and_unlink():
    print("\n--- Test 4: verify chain + unlink rejected QCM only ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        ctx = FakeContext(tmp)
        _seed_step3(ctx, "page_1.json", [
            {"uid": "1_1_0", "page": 1, "number": 1, "text": "QONE",   "cas": "CAS 1\r\nPatient A", "propositions": {"a": "x", "b": "y"}},
            {"uid": "1_1_1", "page": 1, "number": 2, "text": "QTWO",   "cas": "CAS 1\r\nPatient A", "propositions": {"a": "x", "b": "y"}},
            {"uid": "1_1_2", "page": 1, "number": 3, "text": "QTHREE", "cas": "CAS 1\r\nPatient A", "propositions": {"a": "x", "b": "y"}},
        ])
        client = _mock_client_by_question({"QTWO": False}, default_applies=True)
        with patch("modules.clinical_case_checker.OpenRouterClient", return_value=client):
            res = run_clinical_case_checker(CostTracker(), ctx)

        assert res["status"] == "ok", res
        assert res["stats"]["verified"] == 3
        assert res["stats"]["unlinked"] == 1, res["stats"]

        # Reload the accepted file: ONLY uid 1_1_1 lost its cas
        data = json.loads((ctx.get_path("step3_metadata", "accepted") / "page_1.json").read_text(encoding="utf-8"))
        assert data[0]["cas"] == "CAS 1\r\nPatient A"
        assert "cas" not in data[1], "rejected QCM must be unlinked"
        assert data[2]["cas"] == "CAS 1\r\nPatient A"

        # Audit written at folder root (NOT accepted/) with the correction recorded
        audit = json.loads((ctx.get_path("step3_metadata") / VERIFICATION_FILENAME).read_text(encoding="utf-8"))
        assert set(audit["uid_set"]) == {"1_1_0", "1_1_1", "1_1_2"}
        corrected = [d for d in audit["decisions"] if d["corrected"]]
        assert len(corrected) == 1 and corrected[0]["uid"] == "1_1_1"
        assert audit["stats"]["unlinked"] == 1
        print("✅ chain verified; rejected QCM unlinked; audit + corrections written.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_unresolved_keeps_links_flags_error():
    print("\n--- Test 5: all LLM calls fail -> unresolved, links KEPT, status error ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        ctx = FakeContext(tmp)
        _seed_step3(ctx, "page_1.json", [
            {"uid": "1_1_0", "page": 1, "number": 1, "text": "Q1", "cas": "CAS 1\r\nPatient A"},
            {"uid": "1_1_1", "page": 1, "number": 2, "text": "Q2", "cas": "CAS 1\r\nPatient A"},
        ])
        client = MagicMock()
        client.generate_completion = MagicMock(side_effect=RuntimeError("model down"))
        with patch("modules.clinical_case_checker.OpenRouterClient", return_value=client):
            res = run_clinical_case_checker(CostTracker(), ctx)

        assert res["status"] == "error", res
        assert res["stats"]["unresolved"] == 2
        assert res["stats"]["verified"] == 0
        # primary + fallback attempted per QCM
        assert client.generate_completion.call_count == 4

        # Data untouched — a technical failure is never a rejection
        data = json.loads((ctx.get_path("step3_metadata", "accepted") / "page_1.json").read_text(encoding="utf-8"))
        assert all("cas" in q for q in data)
        print("✅ all-fail: status error, links kept, primary+fallback attempted.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_idempotent_skip():
    print("\n--- Test 6: same uid set already verified -> skipped, no LLM calls ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        ctx = FakeContext(tmp)
        qcms = [{"uid": "1_1_0", "page": 1, "number": 1, "text": "Q1", "cas": "CAS 1\r\nPatient A"}]
        _seed_step3(ctx, "page_1.json", qcms)

        with patch("modules.clinical_case_checker.OpenRouterClient",
                   return_value=_mock_client_by_question({})):
            first = run_clinical_case_checker(CostTracker(), ctx)
        assert first["status"] == "ok", first

        with patch("modules.clinical_case_checker.OpenRouterClient") as MockClient:
            second = run_clinical_case_checker(CostTracker(), ctx)
            assert second["status"] == "skipped", second
            assert MockClient.call_count == 0
        print("✅ idempotent skip on identical uid set.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
# Cascade wiring (post_step2_metadata)
# ─────────────────────────────────────────────────────────────────────────────

def _step3_config_with(strategy: str) -> dict:
    cfg = json.loads(json.dumps(DEFAULT_STEP3_CONFIG))
    cfg["fields"]["clinical_case"]["strategy"] = strategy
    return cfg


def _seed_step2(ctx: FakeContext, qcms: list):
    d = ctx.get_path("step2_qcm", "accepted")
    (d / "all_qcms.json").write_text(json.dumps(qcms), encoding="utf-8")


def _fake_step3_writes_accepted(ctx):
    def fake_step3_run(auto_mode=False, config=None, global_pages=None, **kw):
        d = ctx.get_path("step3_metadata", "accepted")
        (d / "page_1.json").write_text(json.dumps(
            [{"uid": "1_1_0", "page": 1, "number": 1, "text": "Q1", "cas": "CAS 1\r\nP"}
        ]), encoding="utf-8")
        return {"config": config, "global_values": {}}
    return fake_step3_run


def _test_cascade_gating_and_soft_fail():
    print("\n--- Test 7: cascade gating (per_group only) + checker soft-fail ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        build_called = {"n": 0}
        def fake_build(*a, **kw):
            build_called["n"] += 1
            return {"status": "ok", "step5": {"total_qcms": 1}}

        # 7a. strategy=skip -> checker NOT invoked
        ctx = FakeContext(tmp / "a")
        _seed_step2(ctx, [{"uid": "1_1_0", "page": 1, "number": 1, "text": "Q1"}])
        with patch("modules.post_step2_metadata.Step3Metadata") as MockSM, \
             patch("modules.post_step2_metadata.run_clinical_case_checker") as MockCC, \
             patch("modules.post_step2_metadata.run_post_step3_build", side_effect=fake_build):
            MockSM.return_value.run = _fake_step3_writes_accepted(ctx)
            res = run_post_step2_metadata(CostTracker(), ctx, "u", "p", _step3_config_with("skip"))
        assert res["cc_check"]["status"] == "not_enabled", res
        assert MockCC.call_count == 0, "checker must not run for strategy=skip"
        assert build_called["n"] == 1
        print("✅ 7a: skip strategy -> checker not invoked, build chained.")

        # 7b. strategy=per_group -> checker invoked, result surfaces in cc_check
        ctx = FakeContext(tmp / "b")
        _seed_step2(ctx, [{"uid": "1_1_0", "page": 1, "number": 1, "text": "Q1"}])
        with patch("modules.post_step2_metadata.Step3Metadata") as MockSM, \
             patch("modules.post_step2_metadata.run_clinical_case_checker",
                   return_value={"status": "ok", "stats": {"unlinked": 0}}) as MockCC, \
             patch("modules.post_step2_metadata.run_post_step3_build", side_effect=fake_build):
            MockSM.return_value.run = _fake_step3_writes_accepted(ctx)
            res = run_post_step2_metadata(CostTracker(), ctx, "u", "p", _step3_config_with("per_group"))
        assert res["status"] == "ok", res
        assert MockCC.call_count == 1
        assert res["cc_check"]["status"] == "ok"
        print("✅ 7b: per_group strategy -> checker invoked, cc_check surfaced.")

        # 7c. checker raises -> soft-fail: build still chained, status ok, cc_check=error
        ctx = FakeContext(tmp / "c")
        _seed_step2(ctx, [{"uid": "1_1_0", "page": 1, "number": 1, "text": "Q1"}])
        with patch("modules.post_step2_metadata.Step3Metadata") as MockSM, \
             patch("modules.post_step2_metadata.run_clinical_case_checker",
                   side_effect=RuntimeError("checker boom")) as MockCC, \
             patch("modules.post_step2_metadata.run_post_step3_build", side_effect=fake_build):
            MockSM.return_value.run = _fake_step3_writes_accepted(ctx)
            res = run_post_step2_metadata(CostTracker(), ctx, "u", "p", _step3_config_with("per_group"))
        assert res["status"] == "ok", "checker failure must NOT fail the cascade"
        assert res["cc_check"]["status"] == "error"
        assert "checker boom" in res["cc_check"]["detail"]
        assert build_called["n"] == 3, "build must still run after checker failure"
        print("✅ 7c: checker exception -> soft-fail, build chained, cc_check=error.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_all():
    _test_parse_verdict_variants()
    _test_build_chains()
    _test_no_cases_no_llm()
    _test_chain_verify_and_unlink()
    _test_unresolved_keeps_links_flags_error()
    _test_idempotent_skip()
    _test_cascade_gating_and_soft_fail()

    print("\n" + "=" * 60)
    print("ALL clinical_case_checker TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()
