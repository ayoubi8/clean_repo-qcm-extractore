"""Phase 5 — _run_step_task end to end through step_process (thread mode),
with the real step replaced by a stub: status, logs, cost rows, Step 2 cascade."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))


def _api(monkeypatch, tmp_path):
    import importlib
    import real_api
    api = importlib.reload(real_api)
    rows = []
    monkeypatch.setenv("STEP_RUNNER", "thread")
    monkeypatch.setattr(api, "_record_step_costs", lambda u, p, s, calls: rows.append((s, calls)))
    for name in ("_restore_step_input_from_storage", "_pre_run_sheets_sync", "_record_step_history",
                 "_record_step_result", "_upload_step_folder_to_storage", "_sync_project_tokens_to_db",
                 "_ensure_tracker_history"):
        monkeypatch.setattr(api, name, lambda *a, **k: (0, 0))
    monkeypatch.setattr(api, "_compute_step_badge", lambda *a: ("success", {}))
    monkeypatch.setattr(api, "_user_run_env", lambda uid: {"OPENROUTER_API_KEY": "k-" + uid})
    monkeypatch.setattr(api, "write_file", lambda *a, **k: None)
    monkeypatch.setattr(api, "file_exists", lambda *a, **k: False)
    return api, rows


def _run(api, step_id):
    jp = api.job_project("u1", "proj")

    async def main():
        task = asyncio.ensure_future(api._run_step_task("proj", "u1", step_id, {}))
        api.job_manager.set_running(jp, step_id, task)
        await task
    asyncio.run(main())
    return jp


def test_step_done_logs_and_costs(monkeypatch, tmp_path):
    api, rows = _api(monkeypatch, tmp_path)
    seen_key = []

    def fake_call_step(step_id, tracker, context, config, cancel_check=None):
        from modules.utils import run_env
        seen_key.append(run_env.getenv("OPENROUTER_API_KEY"))
        print("working on step 6")
        tracker.log_api_call("step6_all_pages_scan", "m", {"prompt": 3, "completion": 1}, 0.2)
    monkeypatch.setattr(api, "_call_step", fake_call_step)
    jp = _run(api, "6")
    assert api.job_manager.get_status(jp, "6") == "done"
    texts = [l["text"] for l in api.job_manager.get_logs(jp, "6")]
    assert "working on step 6" in texts and any("completed successfully" in t for t in texts)
    assert seen_key == ["k-u1"]
    step, calls = rows[-1]
    assert step == "6" and [c["step"] for c in calls] == ["step6_all_pages_scan"]


def test_step2_cascade_then_done(monkeypatch, tmp_path):
    api, rows = _api(monkeypatch, tmp_path)
    monkeypatch.setattr(api, "_call_step", lambda *a, **k: print("step 2 body"))

    def fake_cascade(tracker, context, user_id, project, step3_cfg, cancel_check, step_id, run_id):
        print("cascade line")
        tracker.log_api_call("cc_checker", "m", {"prompt": 1, "completion": 1}, 0.1)
        return {"status": "ok", "build": {"step5": {"total_qcms": 12}}}
    monkeypatch.setattr(api, "_cascade_with_telemetry", fake_cascade)
    jp = _run(api, "2")
    assert api.job_manager.get_status(jp, "2") == "done"
    assert api.job_manager.get_status(jp, "3") == "done"
    texts = [l["text"] for l in api.job_manager.get_logs(jp, "2")]
    assert "cascade line" in texts and any("12 QCMs merged" in t for t in texts)
    assert [c["step"] for c in rows[-1][1]] == ["cc_checker"]


def test_step_error(monkeypatch, tmp_path):
    api, _ = _api(monkeypatch, tmp_path)

    def boom(*a, **k):
        raise RuntimeError("model down")
    monkeypatch.setattr(api, "_call_step", boom)
    jp = _run(api, "7")
    assert api.job_manager.get_status(jp, "7") == "error"
    assert any("model down" in l["text"] for l in api.job_manager.get_logs(jp, "7"))
