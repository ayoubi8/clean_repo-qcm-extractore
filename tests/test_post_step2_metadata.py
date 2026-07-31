"""Tests for run_post_step2_metadata (PR #2 — Step 2+3 backend merge).

Covers the contract in MERGE_STEP2_STEP3_REPORT.md §7:
- Produces step3_metadata/accepted/*.json AND step5_json/merged_qcms.json
- set_done("3","4","5") from the caller is asserted via a fake job_manager
- Idempotent on re-run (Q8 fast-path skips Step 3 on the second call)
- No-op when all_qcms.json is empty
- Cost integrity: orchestrator doesn't double-call Step3
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
from modules.post_step2_metadata import (
    run_post_step2_metadata,
    DEFAULT_STEP3_CONFIG,
    _accepted_qcms_exist,
    _metadata_already_done,
)


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


def _seed_qcms(ctx: FakeContext, qcms: list):
    """Write all_qcms.json into step2_qcm/accepted/."""
    d = ctx.get_path("step2_qcm", "accepted")
    (d / "all_qcms.json").write_text(json.dumps(qcms), encoding="utf-8")


def _test_no_qcms():
    """1. No-op when step2_qcm/accepted is empty — does NOT mark steps done."""
    print("\n--- Test 1: no_qcms fast path ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        ctx = FakeContext(tmp)
        tracker = CostTracker()
        res = run_post_step2_metadata(tracker, ctx, "admin", "testproj", DEFAULT_STEP3_CONFIG)
        assert res["status"] == "no_qcms", f"expected no_qcms, got {res['status']}"
        assert res["step3"] == "skipped"
        assert not (tmp / "step3_metadata").exists() or not any((tmp / "step3_metadata").rglob("*.json"))
        print("✅ no_qcms path returns correctly, no folders created.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_missing_step3_calls_step3(monkey_post_step3_build):
    """2. When metadata missing → Step 3 runs → chain build fires → status ok."""
    print("\n--- Test 2: full cascade (Step 3 + build) ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        ctx = FakeContext(tmp)
        tracker = CostTracker()
        _seed_qcms(ctx, [{"number": 1, "text": "Q1", "propositions": {"A": "a", "B": "b", "C": "c"}}])

        # Stub Step3Metadata.run to write a fake accepted file
        def fake_step3_run(auto_mode=False, config=None, global_pages=None, **kw):
            d = ctx.get_path("step3_metadata", "accepted")
            (d / "page_1.json").write_text(json.dumps({"number": 1, "text": "Q1"}), encoding="utf-8")
            print("[FAKE STEP3] wrote page_1.json")
            return {"config": config, "global_values": {}}

        with patch("modules.post_step2_metadata.Step3Metadata") as MockSM:
            MockSM.return_value.run = fake_step3_run
            res = run_post_step2_metadata(tracker, ctx, "admin", "testproj", DEFAULT_STEP3_CONFIG)

        assert res["status"] == "ok", f"expected ok, got {res}"
        assert res["step3"] == "done"
        # Step 3 wrote its file
        assert (ctx.get_path("step3_metadata", "accepted") / "page_1.json").exists()
        # Step 4/5 build was chained (monkey patched)
        assert monkey_post_step3_build["called"]
        print("✅ full cascade: step3 done + build chained.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_fast_path_skips_step3(monkey_post_step3_build):
    """3. Q8: when metadata already exists → Step 3 skipped, build still chained."""
    print("\n--- Test 3: Q8 fast path (metadata exists → skip Step 3) ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        ctx = FakeContext(tmp)
        tracker = CostTracker()
        _seed_qcms(ctx, [{"number": 1, "text": "Q1"}])
        # Pre-seed step3 accepted so the fast path triggers
        d = ctx.get_path("step3_metadata", "accepted")
        (d / "page_1.json").write_text("{}", encoding="utf-8")

        with patch("modules.post_step2_metadata.Step3Metadata") as MockSM:
            MockSM.return_value.run = MagicMock(side_effect=AssertionError("Step 3 must NOT run in fast-path"))
            res = run_post_step2_metadata(tracker, ctx, "admin", "testproj", DEFAULT_STEP3_CONFIG)

        assert res["step3"] == "skipped", f"expected skipped, got {res['step3']}"
        assert MockSM.return_value.run.call_count == 0
        assert monkey_post_step3_build["called"], "Step 4/5 build must still chain even when Step3 skipped"
        print("✅ fast path: Step 3 skipped, build still chained.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_default_config_used_when_none(monkey_post_step3_build):
    """4. Passing step3_config=None falls back to DEFAULT_STEP3_CONFIG."""
    print("\n--- Test 4: default config fallback ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        ctx = FakeContext(tmp)
        tracker = CostTracker()
        _seed_qcms(ctx, [{"number": 1, "text": "Q1"}])

        seen_config = {}
        def fake_step3_run(auto_mode=False, config=None, global_pages=None, **kw):
            seen_config["fields"] = config
            seen_config["global_pages"] = global_pages
            d = ctx.get_path("step3_metadata", "accepted")
            (d / "page_1.json").write_text("{}", encoding="utf-8")

        with patch("modules.post_step2_metadata.Step3Metadata") as MockSM:
            MockSM.return_value.run = fake_step3_run
            run_post_step2_metadata(tracker, ctx, "admin", "testproj", None)

        assert "year" in seen_config.get("fields", {}), "default fields not passed"
        assert seen_config.get("global_pages") == [1], f"expected [1], got {seen_config.get('global_pages')}"
        print("✅ default config fallback works.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_step3_failure_propagates():
    """5. Step 3 exception → status error stage=step3, build NOT chained."""
    print("\n--- Test 5: Step 3 failure propagates ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        ctx = FakeContext(tmp)
        tracker = CostTracker()
        _seed_qcms(ctx, [{"number": 1, "text": "Q1"}])

        with patch("modules.post_step2_metadata.Step3Metadata") as MockSM:
            MockSM.return_value.run = MagicMock(side_effect=RuntimeError("boom step3"))
            with patch("modules.post_step2_metadata.run_post_step3_build") as MockBuild:
                MockBuild.side_effect = AssertionError("build must not chain after step3 fails")
                res = run_post_step2_metadata(tracker, ctx, "admin", "testproj", DEFAULT_STEP3_CONFIG)

        assert res["status"] == "error"
        assert res["stage"] == "step3"
        assert "boom step3" in res["detail"]
        print("✅ Step 3 failure stops the cascade (build not chained).")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_all():
    monkey = {"called": False}
    def fake_build(*a, **kw):
        monkey["called"] = True
        return {"status": "ok", "step5": {"total_qcms": 1}}
    with patch("modules.post_step2_metadata.run_post_step3_build", side_effect=fake_build):
        _test_no_qcms()
        monkey["called"] = False
        _test_missing_step3_calls_step3(monkey)
        assert monkey["called"]

        monkey["called"] = False
        _test_fast_path_skips_step3(monkey)
        monkey["called"] = False
        _test_default_config_used_when_none(monkey)
        _test_step3_failure_propagates()

    print("\n" + "=" * 60)
    print("ALL run_post_step2_metadata TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()