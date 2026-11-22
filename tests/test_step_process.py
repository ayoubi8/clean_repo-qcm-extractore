"""Phase 5 — step runner (thread / child process) + cost recording fixes.
Plan: docs/plans/phase5-step-runner-process-plan.md."""
import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import step_process as sp  # noqa: E402
from modules.utils.cost_tracker import CostTracker, bucket_calls, cost_step_bucket  # noqa: E402


def _run(core, mode, should_stop=lambda: False, overlay=None, cancel_after=None):
    logs, events = [], []
    tracker = CostTracker()
    spec = {"step_id": "2", "user_id": "u1", "project": "p", "config": {},
            "run_id": "r", "overlay": overlay or {}, "core": f"step_process_fakes:{core}"}

    async def main():
        task = asyncio.ensure_future(sp.run_core(
            spec, tracker=tracker, context=None, should_stop=should_stop,
            on_log=logs.append, on_event=events.append, mode=mode))
        if cancel_after is not None:
            await asyncio.sleep(cancel_after)
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            events.append({"type": "_cancelled"})
    asyncio.run(main())
    return logs, events, tracker


@pytest.mark.parametrize("mode", ["thread", "process"])
def test_ok_logs_in_order_and_costs(mode):
    logs, events, tracker = _run("ok_core", mode)
    assert [l["text"] for l in logs] == ["line 1", "line 2"]
    types = [e["type"] for e in events]
    assert "step_ok" in types and types[-1] == "finished"
    if mode == "process":
        costs = next(e for e in events if e["type"] == "costs")["calls"]
        assert {c["step"] for c in costs} == {"step2_batch_p1-3", "cc_checker"}
        tracker.merge_calls(costs)
    assert tracker.get_total_summary()["total_cost"] == pytest.approx(0.30)


def test_process_gets_its_own_key():
    logs, _, _ = _run("env_core", "process", overlay={"OPENROUTER_API_KEY": "user-key-1"})
    assert logs[0]["text"] == "key=user-key-1|user-key-1"


@pytest.mark.parametrize("mode", ["thread", "process"])
def test_cooperative_stop(mode):
    t0 = time.monotonic()
    _, events, _ = _run("stop_core", mode, should_stop=lambda: time.monotonic() - t0 > 0.3)
    assert "stopped" in [e["type"] for e in events]


@pytest.mark.parametrize("mode", ["thread", "process"])
def test_error(mode):
    _, events, _ = _run("raise_core", mode)
    err = [e for e in events if e["type"] == "error"]
    assert err and "boom" in err[0]["error"]


def test_crash_is_contained():
    logs, events, _ = _run("crash_core", "process")
    assert logs[0]["text"] == "about to crash"
    err = [e for e in events if e["type"] == "error"]
    assert err and "exit code 3" in err[0]["error"]


def test_cancel_kills_stubborn_child(monkeypatch):
    monkeypatch.setenv("STEP_CANCEL_GRACE_S", "0.5")
    before = set(__import__("multiprocessing").active_children())
    _, events, _ = _run("stubborn_core", "process", cancel_after=3.0)
    assert events[-1]["type"] == "_cancelled"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        alive = [p for p in __import__("multiprocessing").active_children() if p not in before]
        if not alive:
            break
        time.sleep(0.2)
    assert not alive, "child still alive after grace + terminate"


def test_semaphore_queues(monkeypatch):
    monkeypatch.setenv("MAX_STEP_PROCESSES", "1")
    monkeypatch.setattr(sp, "_sem", None)
    logs_all = []

    async def main():
        def one():
            spec = {"step_id": "2", "user_id": "u", "project": "p", "config": {}, "run_id": "r",
                    "overlay": {}, "core": "step_process_fakes:ok_core"}
            return sp.run_core(spec, tracker=CostTracker(), context=None, should_stop=lambda: False,
                               on_log=logs_all.append, on_event=lambda e: None, mode="process")
        await asyncio.gather(one(), one())
    asyncio.run(main())
    assert any("Waiting for a free step runner" in l.get("text", "") for l in logs_all)
    monkeypatch.setattr(sp, "_sem", None)


# ── costs ───────────────────────────────────────────────────────────────────

def test_cost_buckets():
    assert cost_step_bucket("step1") == "1"
    assert cost_step_bucket("step1_5_p1-2") == "1.5"
    assert cost_step_bucket("step1_6_text_fix") == "1.6"
    assert cost_step_bucket("step2_batch_p3-5") == "2"
    assert cost_step_bucket("step3_meta") == "3"
    assert cost_step_bucket("cc_checker") == "3"
    assert cost_step_bucket("step6_all_pages_scan") == "6"
    assert cost_step_bucket("step7_cat") == "7"
    assert cost_step_bucket("weird") is None


def test_calls_since_counts_only_this_run():
    t = CostTracker()
    t.log_api_call("step6_ai", "m", {"prompt": 1, "completion": 1}, 1.0)   # earlier run
    snap = t.snapshot()
    t.log_api_call("step6_all_pages_scan", "m", {"prompt": 10, "completion": 2}, 0.5)
    t.log_api_call("step6_page3_ai", "m", {"prompt": 5, "completion": 1}, 0.25)
    b = bucket_calls(t.calls_since(snap), "6")
    assert b == {"6": {"cost": 0.75, "tokens": 18, "calls": 2}}


def test_step2_run_rows_include_cascade_and_drop_foreign():
    calls = [{"step": "step2_batch_p1-2", "cost": 0.1, "tokens": {"prompt": 1, "completion": 1}},
             {"step": "cc_checker", "cost": 0.2, "tokens": {}},
             {"step": "step6_ai", "cost": 9.0, "tokens": {}}]       # another step's parallel run
    b = bucket_calls(calls, "2")
    assert set(b) == {"2", "3"} and b["3"]["cost"] == 0.2


def test_record_step_costs_inserts_rows(monkeypatch):
    import importlib
    import real_api
    api = importlib.reload(real_api)
    inserted = []

    class T:
        def insert(self, rows):
            inserted.extend(rows if isinstance(rows, list) else [rows])
            return self

        def execute(self):
            return self

    class SB:
        def table(self, name):
            assert name == "costs"
            return T()
    monkeypatch.setattr(api, "_resolve_project_id", lambda u, p: "pid")
    monkeypatch.setattr(api, "get_supabase", lambda: SB())
    api._record_step_costs("u", "p", "2", [
        {"step": "step2_batch_p1-2", "cost": 0.1, "tokens": {"prompt": 3, "completion": 2}},
        {"step": "step3_meta", "cost": 0.05, "tokens": {"prompt": 1, "completion": 1}}])
    assert sorted((r["step_number"], r["cost_usd"], r["tokens"]) for r in inserted) == \
        [("2", 0.1, 5), ("3", 0.05, 2)]


def test_cost_file_summary_groups_steps():
    import importlib
    import real_api
    api = importlib.reload(real_api)
    data = {"models": {"m": {"cost": 0.6, "tokens": {"prompt": 6, "completion": 6}}},
            "steps": {"step2_batch_p1-2": [{"cost": 0.2, "tokens": {"prompt": 2, "completion": 2}}],
                      "step2_batch_p3-4": [{"cost": 0.3, "tokens": {"prompt": 3, "completion": 3}}],
                      "cc_checker": [{"cost": 0.1, "tokens": {"prompt": 1, "completion": 1}}]}}
    s = api._summary_from_cost_file(data)
    assert set(s["per_step"]) == {"2", "3"}
    assert s["per_step"]["2"]["call_count"] == 2
    assert s["total_cost"] == pytest.approx(0.6) and s["total_tokens"] == 12


def test_project_cost_summary_prefers_real_amounts(monkeypatch, tmp_path):
    import importlib
    import real_api
    api = importlib.reload(real_api)
    monkeypatch.setattr(api, "_all_cost_rows", lambda u, n: [{"step_number": "2", "cost_usd": 0, "tokens": 0}])
    monkeypatch.setattr(api, "file_exists", lambda k: True)
    monkeypatch.setattr(api, "read_file", lambda k: json.dumps(
        {"steps": {"step2_batch_p1": [{"cost": 0.4, "tokens": {"prompt": 1, "completion": 1}}]}}))
    s = api._project_cost_summary("u", "p", allow_tracker=False)
    assert s["total_cost"] == pytest.approx(0.4)          # $0 SQL rows ignored
    monkeypatch.setattr(api, "_all_cost_rows", lambda u, n: [{"step_number": "2", "cost_usd": 1.5, "tokens": 9}])
    assert api._project_cost_summary("u", "p", allow_tracker=False)["total_cost"] == 1.5


# ── zip download ────────────────────────────────────────────────────────────

def test_results_zip(monkeypatch, tmp_path):
    import importlib
    import io
    import zipfile
    import real_api
    monkeypatch.setenv("QCM_OUTPUT_ROOT", str(tmp_path))
    api = importlib.reload(real_api)
    for proj in ("a", "b"):
        d = tmp_path / "u1" / proj / "step6_corrections"
        d.mkdir(parents=True)
        (d / "3_corrections_x.xlsx").write_bytes(b"xlsx-" + proj.encode())
        (d / "mbset_import_x.xlsx").write_bytes(b"mb")
        (d / "corrected_qcms.json").write_text("[]")
        (d / "correction_map.json").write_text("{}")
    listing = [{"name": n, "size_bytes": 1, "created_at": "2026-11-22 10:00"} for n in
               ("3_corrections_x.xlsx", "mbset_import_x.xlsx", "corrected_qcms.json", "correction_map.json")]
    monkeypatch.setattr(api, "get_step_output_files",
                        lambda name, sid, user: {"files": listing if sid == "6" else []})
    user = {"id": "u1"}

    def names(files):
        r = api.download_results_zip({"projects": ["a", "b"], "steps": ["6"], "files": files}, user)
        with zipfile.ZipFile(r.path) as z:
            return sorted(z.namelist())
    assert names("xlsx") == ["a/step6/3_corrections_x.xlsx", "a/step6/mbset_import_x.xlsx",
                             "b/step6/3_corrections_x.xlsx", "b/step6/mbset_import_x.xlsx"]
    assert "a/step6/corrected_qcms.json" in names("results")
    assert "a/step6/correction_map.json" in names("all")
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        api.download_results_zip({"projects": ["a"], "steps": ["2"], "files": "xlsx"}, user)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        api.download_results_zip({"projects": ["../u2"], "steps": ["6"], "files": "xlsx"}, user)
    assert e.value.status_code in (400, 404)
