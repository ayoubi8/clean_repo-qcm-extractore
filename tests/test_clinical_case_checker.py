"""Tests for the Phase 1 Clinical Case Checker (modules/clinical_case_checker.py)
and its wiring inside run_post_step2_metadata.

Covers the Phase 1 contract (antigravity_redo_phases.md + clinical_case_checker.md):
- Chain building over cascaded `cas` fields (consecutive same-case runs)
- Chains verified in PARALLEL (asyncio, semaphore cap), QCMs sequential
  within each chain; one simple verification question per QCM (cheap model)
- Single applies=false -> PROVISIONAL (link kept); two consecutive NOs ->
  case closes before the first NO, tail unlinked with zero extra LLM calls
- Lone NO followed by YES -> one §7 re-check of the suspicious QCM
- LLM failure    -> decision stays "unresolved"; linkage KEPT (never a silent
                     rejection); all-calls-failed flags status=error
- Idempotency: re-run over the same uid set is skipped
- Strategy gating in the cascade: runs only for clinical_case=per_group
- Soft-fail: a checker error never blocks the Step 4/5 build
"""
import asyncio
import os
import sys
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

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


def _mock_client_by_question(responses: dict, default_applies=True, delay: float = 0.0,
                             recheck_applies: bool | None = None):
    """OpenRouterClient mock (async path): inspect the prompt and answer from
    the `responses` {question_text: bool} map. §7 re-check prompts (marked by
    "re-checking one judgment") answer `recheck_applies` when set, else fall
    back to the question map."""
    client = MagicMock()
    async def gen_async(prompt, **kw):
        if delay:
            await asyncio.sleep(delay)
        if recheck_applies is not None and "re-checking one judgment" in prompt:
            return _ok(recheck_applies)
        for qtext, applies in responses.items():
            if qtext in prompt:
                return _ok(applies)
        return _ok(default_applies)
    client.generate_completion_async = AsyncMock(side_effect=gen_async)
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
        # QTWO's lone NO triggered one §7 re-check after QTHREE's YES
        # (3 verdict calls + 1 re-check call).
        assert res["stats"]["rechecked"] == 1, res["stats"]
        assert client.generate_completion_async.call_count == 4

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
        client.generate_completion_async = AsyncMock(side_effect=RuntimeError("model down"))
        with patch("modules.clinical_case_checker.OpenRouterClient", return_value=client):
            res = run_clinical_case_checker(CostTracker(), ctx)

        assert res["status"] == "error", res
        assert res["stats"]["unresolved"] == 2
        assert res["stats"]["verified"] == 0
        # primary + fallback attempted per QCM (async path)
        assert client.generate_completion_async.call_count == 4

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


# ─────────────────────────────────────────────────────────────────────────────
# Parallel + early-stop behavior (new)
# ─────────────────────────────────────────────────────────────────────────────

def _test_two_consecutive_no_closes_chain():
    print("\n--- Test 8: two consecutive NOs close the chain, tail costs zero calls ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        ctx = FakeContext(tmp)
        _seed_step3(ctx, "page_1.json", [
            {"uid": f"1_1_{i}", "page": 1, "number": i + 1, "text": f"Q{i + 1}",
             "cas": "CAS 1\r\nPatient A"}
            for i in range(5)
        ])
        # Q3, Q4 do NOT belong -> close at Q3; Q5 must never reach the LLM.
        client = _mock_client_by_question({"Q3": False, "Q4": False}, default_applies=True)
        with patch("modules.clinical_case_checker.OpenRouterClient", return_value=client):
            res = run_clinical_case_checker(CostTracker(), ctx)

        assert res["status"] == "ok", res
        assert res["stats"]["closed_early_chains"] == 1, res["stats"]
        assert res["stats"]["llm_calls_saved"] == 1, res["stats"]
        # Q1, Q2, Q3, Q4 verified; Q5 never touched by the LLM.
        assert client.generate_completion_async.call_count == 4, \
            client.generate_completion_async.call_count
        assert res["stats"]["unlinked"] == 3, res["stats"]  # Q3 + Q4 + Q5 tail

        data = json.loads((ctx.get_path("step3_metadata", "accepted") / "page_1.json").read_text(encoding="utf-8"))
        assert data[0]["cas"] == "CAS 1\r\nPatient A" and data[1]["cas"] == "CAS 1\r\nPatient A"
        assert all("cas" not in q for q in data[2:]), "Q3..Q5 must be unlinked"

        audit = json.loads((ctx.get_path("step3_metadata") / VERIFICATION_FILENAME).read_text(encoding="utf-8"))
        chain = audit["chains"][0]
        assert chain["closed_early"] is True
        assert chain["early_stop_reason"] == "two_consecutive_no"
        tail = [d for d in audit["decisions"] if d.get("after_close")]
        assert len(tail) == 1 and tail[0]["uid"] == "1_1_4"
        assert tail[0]["status"] == "unlinked_by_boundary"
        print("✅ chain closed on 2nd NO; tail unlinked with zero extra LLM calls.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_no_yes_recheck_keeps_link():
    print("\n--- Test 9: lone NO followed by YES → §7 re-check keeps link on YES ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        ctx = FakeContext(tmp)
        _seed_step3(ctx, "page_1.json", [
            {"uid": "1_1_0", "page": 1, "number": 1, "text": "QONE", "cas": "CAS 1\r\nPatient A"},
            {"uid": "1_1_1", "page": 1, "number": 2, "text": "QTWO", "cas": "CAS 1\r\nPatient A"},
            {"uid": "1_1_2", "page": 1, "number": 3, "text": "QTHREE", "cas": "CAS 1\r\nPatient A"},
        ])
        # Verdict pass: QTWO does NOT belong; but the §7 re-check says it DOES.
        client = _mock_client_by_question({"QTWO": False}, default_applies=True,
                                          recheck_applies=True)
        with patch("modules.clinical_case_checker.OpenRouterClient", return_value=client):
            res = run_clinical_case_checker(CostTracker(), ctx)

        assert res["status"] == "ok", res
        assert res["stats"]["unlinked"] == 0, res["stats"]
        assert res["stats"]["kept"] == 2, res["stats"]  # QONE + QTHREE decisive YES
        assert res["stats"]["rechecked"] == 1
        data = json.loads((ctx.get_path("step3_metadata", "accepted") / "page_1.json").read_text(encoding="utf-8"))
        assert all("cas" in q for q in data), "provisional NO overturned — all links kept"
        audit = json.loads((ctx.get_path("step3_metadata") / VERIFICATION_FILENAME).read_text(encoding="utf-8"))
        qtwo = [d for d in audit["decisions"] if d["uid"] == "1_1_1"][0]
        assert qtwo["rechecked"] is True and qtwo["provisional"] is True
        assert qtwo["corrected"] is False
        print("✅ §7 re-check overturned the NO — link kept.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_parallel_cap_five():
    print("\n--- Test 10: 7 chains run in parallel, max 5 concurrent ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        ctx = FakeContext(tmp)
        qcms = []
        for c in range(7):
            for q in range(2):
                qcms.append({"uid": f"{c}_{q}", "page": c + 1, "number": q + 1,
                             "text": f"C{c}Q{q}", "cas": f"CAS {c}\r\nPatient {c}"})
        _seed_step3(ctx, "page_1.json", qcms)

        state = {"in_flight": 0, "max_in_flight": 0, "calls": 0}
        client = MagicMock()
        async def gen_async(prompt, **kw):
            state["in_flight"] += 1
            state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
            try:
                await asyncio.sleep(0.05)
                return _ok(True)
            finally:
                state["in_flight"] -= 1
                state["calls"] += 1
        client.generate_completion_async = AsyncMock(side_effect=gen_async)
        with patch.dict(os.environ, {"CC_CHECKER_MAX_PARALLEL": "5"}), \
             patch("modules.clinical_case_checker.OpenRouterClient", return_value=client):
            res = run_clinical_case_checker(CostTracker(), ctx)

        assert res["status"] == "ok", res
        assert state["calls"] == 14, state
        assert 1 < state["max_in_flight"] <= 5, state  # parallel, capped at 5
        assert res["stats"]["llm_calls_made"] == 14
        print(f"✅ 7 chains verified with peak concurrency {state['max_in_flight']} (cap 5).")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_early_stop_off_unlinks_immediately():
    print("\n--- Test 11: CC_CHECKER_EARLY_STOP=0 → immediate per-QCM unlink, no re-check ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        ctx = FakeContext(tmp)
        _seed_step3(ctx, "page_1.json", [
            {"uid": "1_1_0", "page": 1, "number": 1, "text": "QONE", "cas": "CAS 1\r\nPatient A"},
            {"uid": "1_1_1", "page": 1, "number": 2, "text": "QTWO", "cas": "CAS 1\r\nPatient A"},
            {"uid": "1_1_2", "page": 1, "number": 3, "text": "QTHREE", "cas": "CAS 1\r\nPatient A"},
        ])
        client = _mock_client_by_question({"QTWO": False}, default_applies=True)
        with patch.dict(os.environ, {"CC_CHECKER_EARLY_STOP": "0"}), \
             patch("modules.clinical_case_checker.OpenRouterClient", return_value=client):
            res = run_clinical_case_checker(CostTracker(), ctx)

        assert res["status"] == "ok", res
        assert res["stats"]["unlinked"] == 1, res["stats"]
        assert res["stats"]["rechecked"] == 0, res["stats"]
        assert res["stats"]["closed_early_chains"] == 0
        # No §7 re-check call: exactly 3 verdict calls.
        assert client.generate_completion_async.call_count == 3
        data = json.loads((ctx.get_path("step3_metadata", "accepted") / "page_1.json").read_text(encoding="utf-8"))
        assert "cas" not in data[1] and data[0]["cas"] and data[2]["cas"]
        print("✅ early-stop off: immediate unlink, no re-check.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_unresolved_between_no_still_closes():
    print("\n--- Test 12: NO, unresolved, NO → still closes (no YES between) ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        ctx = FakeContext(tmp)
        _seed_step3(ctx, "page_1.json", [
            {"uid": f"1_1_{i}", "page": 1, "number": i + 1, "text": f"Q{i + 1}",
             "cas": "CAS 1\r\nPatient A"}
            for i in range(4)
        ])
        client = MagicMock()
        async def gen_async(prompt, **kw):
            if "QUESTION:\nQ3" in prompt:
                raise RuntimeError("model down")
            for qtext, applies in (("Q2", False), ("Q4", False)):
                if f"QUESTION:\n{qtext}" in prompt:
                    return _ok(applies)
            return _ok(True)
        client.generate_completion_async = AsyncMock(side_effect=gen_async)
        with patch("modules.clinical_case_checker.OpenRouterClient", return_value=client):
            res = run_clinical_case_checker(CostTracker(), ctx)

        assert res["status"] == "ok", res
        assert res["stats"]["closed_early_chains"] == 1, res["stats"]
        assert res["stats"]["unlinked"] == 2, res["stats"]  # Q2 + Q4
        assert res["stats"]["unresolved"] == 1, res["stats"]  # Q3 link kept
        # Q1, Q2, Q4 verdicts + Q3 primary+fallback attempts = 5 calls.
        assert client.generate_completion_async.call_count == 5, \
            client.generate_completion_async.call_count
        data = json.loads((ctx.get_path("step3_metadata", "accepted") / "page_1.json").read_text(encoding="utf-8"))
        assert data[0]["cas"] and data[2]["cas"] and "cas" not in data[1] and "cas" not in data[3]
        print("✅ unresolved neither confirms nor breaks the NO pair — chain closed.")
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
    _test_two_consecutive_no_closes_chain()
    _test_no_yes_recheck_keeps_link()
    _test_parallel_cap_five()
    _test_early_stop_off_unlinks_immediately()
    _test_unresolved_between_no_still_closes()

    print("\n" + "=" * 60)
    print("ALL clinical_case_checker TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()
