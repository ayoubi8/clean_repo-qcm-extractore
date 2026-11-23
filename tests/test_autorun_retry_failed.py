"""Auto Run: truthful step state, "Retry failed", manual-run batch sync
(docs/plans/autorun-retry-speed-sheets-plan.md, phases 3-4)."""
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_KEY", "test-service-key")

import autorun_batch as ab  # noqa: E402
import real_api  # noqa: E402
import step_cache  # noqa: E402

UID = "retry-tester"
SEQ = ab.BATCH_SEQUENCE


@pytest.fixture(autouse=True)
def engine(tmp_path):
    step_cache.clear()
    ab._BATCH_TASKS.clear()
    ab._RETRY_TASKS.clear()
    ab._BATCH_SEMS.clear()
    for sid in SEQ:
        for name in ("A", "B", "C", "D", "E", "F", "G"):
            ab.job_manager._status.pop(ab.job_manager.key(ab.job_project(UID, name), sid), None) \
                if hasattr(ab.job_manager, "_status") else None
    with patch.object(ab, "OUTPUT_ROOT", tmp_path), \
         patch("storage_client.write_file", lambda *a, **k: None), \
         patch("storage_client.read_file", side_effect=FileNotFoundError), \
         patch.object(ab, "_mark_project_autorun", lambda *a, **k: None):
        yield tmp_path
    step_cache.clear()


class Runner:
    def __init__(self, fail=()):
        self.calls, self.active, self.max_active, self.fail = [], set(), 0, set(fail)

    async def run(self, project, uid, sid, cfg):
        self.active.add(project)
        self.max_active = max(self.max_active, len(self.active))
        self.calls.append((project, sid))
        await asyncio.sleep(0.01)
        self.active.discard(project)
        jp = ab.job_project(uid, project)
        if (project, sid) in self.fail:
            ab.job_manager.set_error(jp, sid)
        else:
            ab.job_manager.set_done(jp, sid)


def manifest(projects, batch_id="b1"):
    m = {"batch_id": batch_id, "created_at": "2026-11-23T00:00:00+00:00", "source": "drive",
         "state": "done_with_errors", "config_snapshot": {}, "projects": projects}
    ab.write_manifest(UID, m)
    return m


def rows(table):
    return lambda uid, project, sid: ({"badge": table[project][sid]}
                                      if sid in table.get(project, {}) else None)


def drive(start):
    async def main():
        result = start()
        while True:
            live = [t for t in [*ab._BATCH_TASKS.values(), *ab._RETRY_TASKS.values()] if not t.done()]
            if not live:
                break
            await asyncio.gather(*live)
        await asyncio.sleep(0)
        return result
    return asyncio.run(main())


def test_failed_row_beats_files_on_disk(engine):
    d = engine / UID / "A" / "step6_corrections"
    d.mkdir(parents=True)
    (d / "corrected_qcms.json").write_text(json.dumps([{"Num": 1, "Correct": "A"}]), encoding="utf-8")
    table = {"A": {**{s: "success" for s in SEQ}, "6": "error"}}
    with patch.object(real_api, "_latest_step_result_row", side_effect=rows(table)):
        assert ab.first_not_done_step(UID, "A") == "6"


def test_warning_step2_is_done_after_disk_wipe():
    table = {"A": {"1": "success", "1.5": "success", "1.6": "success", "2": "warning"}}
    with patch.object(real_api, "_latest_step_result_row", side_effect=rows(table)):
        assert ab.first_not_done_step(UID, "A") == "6"


def test_empty_folders_are_not_done(engine):
    (engine / UID / "A" / "step1_extraction" / "accepted").mkdir(parents=True)
    (engine / UID / "A" / "step6_corrections").mkdir(parents=True)
    with patch.object(real_api, "_latest_step_result_row", return_value=None):
        assert ab.first_not_done_step(UID, "A") == "1"


def test_null_only_corrections_are_not_done_locally(engine):
    d = engine / UID / "A" / "step6_corrections"
    d.mkdir(parents=True)
    (d / "corrected_qcms.json").write_text(json.dumps([{"Num": 1, "Correct": None}]), encoding="utf-8")
    assert ab._step_done_local(UID, "A", "6") is False
    assert ab.step6_counts(UID, "A") == {"corrected": 0, "total": 1}


def test_retry_failed_only_reruns_failed_steps_within_the_queue():
    done_until_6 = {**{s: "success" for s in SEQ}, "2": "warning", "6": "error"}
    names = ["A", "B", "C", "D", "E", "F"]
    manifest([{"name": n, "state": "error", "error_step": "6",
               "steps": {"6": {"state": "error"}}} for n in names]
             + [{"name": "G", "state": "done"}])
    table = {n: dict(done_until_6) for n in names}
    runner = Runner()

    async def fake(project, uid, sid, cfg):
        await runner.run(project, uid, sid, cfg)
        table[project][sid] = "success"

    with patch.object(real_api, "_latest_step_result_row", side_effect=rows(table)), \
         patch.object(ab, "_spawn_runtime_task", new=fake), \
         patch.dict(os.environ, {"AUTORUN_BATCH_CONCURRENCY": "2"}):
        result = drive(lambda: ab.retry_failed_projects(UID, "b1"))

    assert sorted(result["queued"]) == names
    assert sorted(runner.calls) == sorted((n, "6") for n in names)   # no Step 2 re-bill
    assert runner.max_active <= 2
    m = ab.read_manifest(UID, "b1")
    assert all(p["state"] == "done" for p in m["projects"]) and m["state"] == "done"


def test_retry_failed_while_batch_runs_shares_the_queue():
    manifest([{"name": "A", "state": "pending"}, {"name": "B", "state": "pending"},
              {"name": "C", "state": "error", "error_step": "6"},
              {"name": "D", "state": "error", "error_step": "6"}])
    table = {"C": {**{s: "success" for s in SEQ}, "6": "error"},
             "D": {**{s: "success" for s in SEQ}, "6": "error"}}
    runner = Runner()
    with patch.object(real_api, "_latest_step_result_row", side_effect=rows(table)), \
         patch.object(ab, "_spawn_runtime_task", new=lambda p, u, s, c: runner.run(p, u, s, c)), \
         patch.dict(os.environ, {"AUTORUN_BATCH_CONCURRENCY": "2"}):
        def start():
            assert ab.run_batch_task(UID, "b1")
            return ab.retry_failed_projects(UID, "b1")
        result = drive(start)
    assert sorted(result["queued"]) == ["C", "D"]
    assert runner.max_active <= 2
    assert [s for p, s in runner.calls if p == "C"] == ["6"]
    assert ab.read_manifest(UID, "b1")["state"] == "done"


def test_retry_failed_skips_completed_and_reports_nothing_to_do():
    manifest([{"name": "A", "state": "done", "corrections": {"corrected": 0, "total": 5}}])
    assert ab.retry_failed_projects(UID, "b1")["error"] == "nothing-to-retry"
    assert ab.read_manifest(UID, "b1")["projects"][0]["state"] == "done"


def test_stale_failure_does_not_repaint_a_requeued_chip():
    m = {"projects": [{"name": "A", "state": "running", "current_step": "2",
                       "steps": {"2": {"state": "running"}}}]}
    ab.merge_live_status(m, status_lookup=lambda n, s: "error" if s == "6" else "idle")
    assert m["projects"][0]["steps"]["6"]["state"] == "idle"


def test_manual_step6_success_completes_the_batch_card(engine):
    pdir = engine / UID / "A"
    (pdir / "step6_corrections").mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({"batch_id": "b1"}), encoding="utf-8")
    (pdir / "step6_corrections" / "corrected_qcms.json").write_text(
        json.dumps([{"Num": 1, "Correct": "A"}, {"Num": 2, "Correct": None}]), encoding="utf-8")
    manifest([{"name": "A", "state": "error", "error_step": "6", "error_message": "old"}])
    table = {"A": {s: "success" for s in SEQ}}
    with patch.object(real_api, "_latest_step_result_row", side_effect=rows(table)):
        ab.note_manual_step(UID, "A", "6", "done")
    m = ab.read_manifest(UID, "b1")
    p = m["projects"][0]
    assert p["state"] == "done" and "error_step" not in p and "error_message" not in p
    assert p["corrections"] == {"corrected": 1, "total": 2} and m["state"] == "done"


def test_manual_step_never_touches_a_pdf_the_engine_owns(engine):
    pdir = engine / UID / "A"
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({"batch_id": "b1"}), encoding="utf-8")
    manifest([{"name": "A", "state": "running", "current_step": "2"}])
    ab.note_manual_step(UID, "A", "6", "error", "boom")
    assert ab.read_manifest(UID, "b1")["projects"][0]["state"] == "running"


@pytest.mark.parametrize("a,b,same", [
    ("120_corrections_x.xlsx", "118_corrections_x.xlsx", True),
    ("120_qcms_x.xlsx", "120_corrections_x.xlsx", False),
    ("120_qcms_x.xlsx", "120_qcms_y.xlsx", False),
    ("", "120_qcms_x.xlsx", False),
])
def test_sheet_reuse_ignores_the_count(a, b, same):
    assert real_api._same_workbook(a, b) is same
