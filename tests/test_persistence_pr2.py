"""Tests for PR-2 SQL-first read pathways (PERSISTENCE_FIX_PLAN).

Covers the four updated read endpoints + the list_projects batch query:
- _latest_step_result_row (helpers + status/output flows)
- _all_step_history_rows → get_step_history reshaping
- _all_cost_rows → get_project_costs summary shape
- list_projects last_step batch query (SQL hit + SQL miss → fallback)

All supabase/storage interactions are mocked — no network, no HF.
"""
import json
import os
import sys
import uuid
import types
from unittest.mock import patch, MagicMock

sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "api"))


def _import_real_api():
    """Import real_api with stubbed deps so importing doesn't require creds."""
    for mod_name in [
        "google_auth_oauthlib", "google.oauth2", "google.auth",
        "googleapiclient", "yaml",
    ]:
        if mod_name not in sys.modules:
            try:
                __import__(mod_name)
            except Exception:
                sys.modules[mod_name] = types.ModuleType(mod_name)
    os.environ.setdefault("SUPABASE_URL", "http://localhost")
    os.environ.setdefault("SUPABASE_KEY", "test-service-key")
    import importlib
    import real_api
    importlib.reload(real_api)
    return real_api


def _import_project_manager():
    import project_manager
    return project_manager


# ---------------- helpers ----------------

def _test_latest_step_result_row_respects_step_filter():
    print("\n--- Test 1: _latest_step_result_row filters by step_id ---")
    real_api = _import_real_api()
    pid = str(uuid.uuid4())
    real_api._resolve_project_id = lambda u, p: pid
    captured = {}
    class FakeChain:
        def __init__(self): self._step = None
        def select(self, cols): captured["cols"] = cols; return self
        def eq(self, k, v):
            if k == "project_id": captured["pid"] = v
            elif k == "step_number": captured["step"] = v
            return self
        def order(self, *a, **k): return self
        def limit(self, n): return self
        def execute(self): return MagicMock(data=[{"id":"row1","step_number":captured.get("step"),"badge":"success","file_manifest":[],"storage_prefix":"uid/p/step2_qcm","created_at":"2026-08-05T14:28:31+00:00"}])
    fake_sb = MagicMock()
    fake_sb.table.return_value = FakeChain()
    real_api.get_supabase = lambda: fake_sb
    row = real_api._latest_step_result_row("uid", "exam1", "2")
    assert row is not None
    assert captured["step"] == "2", captured
    assert captured["cols"].startswith("id,step_number"), captured
    print(f"✅ filters by step_id={captured['step']}; returns row")


def _test_latest_step_result_row_no_step_returns_latest_overall():
    print("\n--- Test 2: _latest_step_result_row no step_id → latest row ---")
    real_api = _import_real_api()
    pid = str(uuid.uuid4())
    real_api._resolve_project_id = lambda u, p: pid
    eqs = []
    class FakeChain:
        def select(self, c): return self
        def eq(self, k, v):
            if k == "step_number": eqs.append(v)
            return self
        def order(self, *a, **k): return self
        def limit(self, n): return self
        def execute(self): return MagicMock(data=[{"id":"r9","step_number":"8","badge":"success","file_manifest":[{"path":"step8_matches.xlsx"}]}])
    fake_sb = MagicMock(); fake_sb.table.return_value = FakeChain()
    real_api.get_supabase = lambda: fake_sb
    row = real_api._latest_step_result_row("uid", "exam1")
    assert row["step_number"] == "8", row
    assert eqs == [], f"should not filter step_number when step_id is None; got {eqs}"
    print("✅ no step_id ⇒ no step filter, returns latest row")


def _test_latest_step_result_row_returns_none_when_project_missing():
    print("\n--- Test 3: _latest_step_result_row returns None if project unresolved ---")
    real_api = _import_real_api()
    real_api._resolve_project_id = lambda u, p: None
    real_api.get_supabase = MagicMock()
    row = real_api._latest_step_result_row("uid", "p", "2")
    assert row is None
    real_api.get_supabase.assert_not_called()
    print("✅ returns None when project not in SQL")


# ---------------- step status endpoint ----------------

def _test_get_step_status_sql_done_short_circuits_storage():
    print("\n--- Test 4: get_step_status SQL success → done, skips Storage walk ---")
    real_api = _import_real_api()
    # in-memory idle (simulating post-restart)
    real_api.job_manager = MagicMock()
    real_api.job_manager.get_status.return_value = "idle"
    real_api.step_output_exists = MagicMock(return_value=False)
    real_api._latest_step_result_row = MagicMock(return_value={
        "badge": "success", "file_manifest": [{"path":"x"}], "storage_prefix": "uid/p/step2_qcm"
    })
    storage_called = []
    real_api._check_step_done_in_storage = lambda *a, **k: storage_called.append(1) or False
    user = {"id": str(uuid.uuid4())}
    out = real_api.get_step_status("p", "2", user)
    assert out == {"status": "done", "output_exists": True}, out
    assert storage_called == [], "Storage walk should be skipped on SQL hit"
    print(f"✅ status={out['status']}; Storage fallback skipped")


def _test_get_step_status_sql_error_returns_error():
    print("\n--- Test 5: get_step_status SQL error badge → error ---")
    real_api = _import_real_api()
    real_api.job_manager = MagicMock(); real_api.job_manager.get_status.return_value = "idle"
    real_api.step_output_exists = MagicMock(return_value=False)
    real_api._latest_step_result_row = MagicMock(return_value={
        "badge": "error", "file_manifest": []
    })
    real_api._check_step_done_in_storage = MagicMock(return_value=False)
    out = real_api.get_step_status("p", "2", {"id": "u"})
    assert out["status"] == "error", out
    assert out["output_exists"] is False, out
    print(f"✅ status=error from SQL")


def _test_get_step_status_sql_miss_falls_back_to_storage():
    print("\n--- Test 6: get_step_status SQL miss → Storage fallback path ---")
    real_api = _import_real_api()
    real_api.job_manager = MagicMock(); real_api.job_manager.get_status.return_value = "idle"
    real_api.step_output_exists = MagicMock(return_value=False)
    real_api._latest_step_result_row = MagicMock(return_value=None)  # SQL miss
    real_api._check_step_done_in_storage = MagicMock(return_value=True)
    out = real_api.get_step_status("p", "2", {"id": "u"})
    assert out == {"status": "done", "output_exists": True}, out
    print("✅ SQL miss falls back to Storage, returns done")


# ---------------- step output listing endpoint ----------------

def _test_get_step_output_files_uses_file_manifest():
    print("\n--- Test 7: get_step_output_files uses SQL file_manifest when FS empty ---")
    real_api = _import_real_api()
    # Force local FS miss — step_dir does not exist
    real_api.Path = lambda *a, **k: MagicMock(
        exists=MagicMock(return_value=False),
        rglob=MagicMock(return_value=[]),
    )
    real_api._latest_step_result_row = MagicMock(return_value={
        "storage_prefix": "uid/p/step2_qcm",
        "file_manifest": [
            {"path": "accepted/page_1.json", "size_bytes": 100, "kind": "json"},
            {"path": "all_qcms.json", "size_bytes": 200, "kind": "json"},
        ],
        "created_at": "2026-08-05T14:28:31+00:00",
    })
    out = real_api.get_step_output_files("p", "2", {"id": "uid"})
    files = out["files"]
    assert len(files) == 2, files
    assert files[0]["name"] == "accepted/page_1.json", files
    assert files[0]["size_bytes"] == 100, files
    assert files[0]["path"] == "uid/p/step2_qcm/accepted/page_1.json", files
    assert files[0]["created_at"] == "2026-08-05 14:28", files
    print(f"✅ returned {len(files)} files from manifest, no FS walk")


def _test_get_step_output_files_falls_back_to_storage_when_no_sql():
    print("\n--- Test 8: get_step_output_files falls back to Storage when SQL empty ---")
    real_api = _import_real_api()

    class FakePath:
        def __init__(self, s): self._s = s
        def __truediv__(self, other): return FakePath(f"{self._s}/{other}")
        def exists(self): return False
        def rglob(self, *a): return []

    real_api.Path = FakePath
    real_api._latest_step_result_row = MagicMock(return_value=None)

    storage_items = [{"name": "page_1.json", "metadata": {"size": 50}}]
    real_api.list_files_recursive = MagicMock(return_value=storage_items)
    out = real_api.get_step_output_files("p", "2", {"id": "uid"})
    assert len(out["files"]) == 1, out
    assert out["files"][0]["size_bytes"] == 50, out
    print(f"✅ Storage fallback returns {len(out['files'])} file(s)")


# ---------------- step history endpoint ----------------

def _test_get_step_history_shapes_sql_rows_into_blob_contract():
    print("\n--- Test 9: get_step_history reshapes SQL rows to blob contract ---")
    real_api = _import_real_api()
    sql_rows = [
        {"step_number": "2", "run_at": "2026-08-05T10:00:00+00:00", "badge": "success",
         "duration_seconds": 12.5, "metadata": {"run_id": "r1", "folder": "step2_qcm", "qcms": 14, "empty_pages": 1}},
        {"step_number": "2", "run_at": "2026-08-05T09:00:00+00:00", "badge": "warning",
         "duration_seconds": 8.0, "metadata": {"run_id": "r0", "folder": "step2_qcm", "qcms": 12}},
        {"step_number": "1", "run_at": "2026-08-05T08:00:00+00:00", "badge": "success",
         "duration_seconds": 30.0, "metadata": {"pages_ok": 50, "pages_failed": 0}},
    ]
    real_api._all_step_history_rows = MagicMock(return_value=sql_rows)
    out = real_api.get_step_history("p", {"id": "u"})
    assert "2" in out and "1" in out, out
    assert len(out["2"]) == 2, out
    e = out["2"][0]
    assert e["badge"] == "success" and e["duration_seconds"] == 12.5, e
    assert e["qcms"] == 14 and e["empty_pages"] == 1, e
    # internal fields (run_id, folder) stripped from the entry
    assert "run_id" not in e and "folder" not in e, e
    print(f"✅ history shaped: steps={list(out)}, step2 entries={len(out['2'])}")


def _test_get_step_history_falls_back_to_blob_when_sql_empty():
    print("\n--- Test 10: get_step_history blob fallback when SQL empty ---")
    real_api = _import_real_api()
    real_api._all_step_history_rows = MagicMock(return_value=[])
    blob = {"2": [{"run_at": "2025-01-01", "badge": "success", "duration_seconds": 5}]}
    real_api.file_exists = MagicMock(return_value=True)
    real_api.read_file = MagicMock(return_value=json.dumps(blob))
    out = real_api.get_step_history("p", {"id": "u"})
    assert out == blob, out
    print("✅ blob fallback returned when SQL empty")


# ---------------- costs endpoint ----------------

def _test_get_project_costs_aggregates_sql_rows():
    print("\n--- Test 11: get_project_costs aggregates SQL rows to summary shape ---")
    real_api = _import_real_api()
    sql_rows = [
        {"step_number": "2", "cost_usd": 0.10, "tokens": 500, "recorded_at": "2026-08-05T10:00:00"},
        {"step_number": "2", "cost_usd": 0.05, "tokens": 200, "recorded_at": "2026-08-05T09:00:00"},
        {"step_number": "1", "cost_usd": 0.20, "tokens": 1000, "recorded_at": "2026-08-05T08:00:00"},
    ]
    real_api._all_cost_rows = MagicMock(return_value=sql_rows)
    out = real_api.get_project_costs("p", {"id": "u"})
    assert round(out["total_cost"], 2) == 0.35, out
    assert out["total_tokens"] == 1700, out
    assert round(out["per_step"]["2"]["total_cost"], 2) == 0.15, out
    assert out["per_step"]["2"]["call_count"] == 2, out
    assert out["per_step"]["1"]["total_tokens"]["completion"] == 1000, out
    # per_model left empty (SQL doesn't track it)
    assert out["per_model"] == {}, out
    print(f"✅ costs aggregated: total=${round(out['total_cost'],2)}, tokens={out['total_tokens']}")


def _test_get_project_costs_blob_fallback_when_sql_empty():
    print("\n--- Test 12: get_project_costs blob fallback when SQL empty ---")
    real_api = _import_real_api()
    real_api._all_cost_rows = MagicMock(return_value=[])
    blob = {"summary": {"total_cost": 1.23, "total_tokens": 999, "per_model": {"x": {}}, "per_step": {}}}
    real_api.file_exists = MagicMock(return_value=True)
    real_api.read_file = MagicMock(return_value=json.dumps(blob))
    out = real_api.get_project_costs("p", {"id": "u"})
    assert out == blob["summary"], out
    print("✅ blob fallback returned")


# ---------------- list_projects batch last_step query ----------------

def _test_list_projects_uses_batch_sql_for_last_step():
    print("\n--- Test 13: list_projects uses batch step_results query for last_step ---")
    real_api = _import_real_api()
    pm = _import_project_manager()

    pid_a = str(uuid.uuid4())
    pid_b = str(uuid.uuid4())
    db_uid = str(uuid.uuid4())
    email = "u@e.com"

    # Patch get_db_user_id (imported into project_manager at top-level)
    pm.get_db_user_id = lambda user: db_uid

    # Patch supabase_client + storage_client at module level — list_projects
    # uses `from supabase_client import get_supabase` and `from storage_client
    # import list_files, read_file` *inside* the function, so patching
    # pm.get_supabase is bypassed. We must patch the source modules.

    class FakeProjectsTable:
        def select(self, cols): return self
        def eq(self, k, v): return self
        def order(self, *a, **k): return self
        def execute(self):
            return MagicMock(data=[
                {"id": pid_a, "name": "projA", "created_at": "2026-08-05", "last_activity_at": "2026-08-05T10:00:00", "pdf_storage_path": ""},
                {"id": pid_b, "name": "projB", "created_at": "2026-08-04", "last_activity_at": "2026-08-05T11:00:00", "pdf_storage_path": ""},
            ])

    class FakeStepResultsTable:
        def __init__(self): self.last_in = None
        def select(self, cols): return self
        def in_(self, k, v): self.last_in = v; return self
        def eq(self, k, v): return self
        def execute(self):
            data = []
            if pid_a in (self.last_in or []): data.append({"project_id": pid_a, "step_number": "2"})
            if pid_b in (self.last_in or []): data.append({"project_id": pid_b, "step_number": "7"})
            return MagicMock(data=data)

    def fake_table(name):
        return FakeProjectsTable() if name == "projects" else FakeStepResultsTable()
    fake_sb = MagicMock()
    fake_sb.table.side_effect = fake_table

    import supabase_client
    orig_get_sb = supabase_client.get_supabase
    supabase_client.get_supabase = lambda: fake_sb

    # Stub storage_client to never make real HTTP calls
    import storage_client
    orig_list_files = storage_client.list_files
    orig_read_file = storage_client.read_file
    storage_client.list_files = MagicMock(return_value=[])
    storage_client.read_file = MagicMock(side_effect=Exception("no storage in test"))
    # pm.step_output_exists imports list_files_recursive from storage_client
    orig_list_rec = getattr(storage_client, "list_files_recursive", None)
    storage_client.list_files_recursive = MagicMock(return_value=[])
    storage_probe_calls = []
    def step_exists(pname, sid, email):
        storage_probe_calls.append((pname, sid))
        return False
    pm.step_output_exists = MagicMock(side_effect=step_exists)

    try:
        pm.invalidate_projects_cache()  # fresh compute (both tests use this email)
        projects = pm.list_projects(email)
    finally:
        supabase_client.get_supabase = orig_get_sb
        storage_client.list_files = orig_list_files
        storage_client.read_file = orig_read_file
        if orig_list_rec is not None: storage_client.list_files_recursive = orig_list_rec

    names = {p["name"]: p for p in projects}
    assert "projA" in names and "projB" in names, names
    assert names["projA"]["last_step"] == 2, names["projA"]
    assert names["projB"]["last_step"] == 7, names["projB"]
    # The Storage recursive probe should NOT have been called for last_step
    # because the batch SQL query already resolved it.
    assert pm.step_output_exists.call_count == 0, f"Storage probe should be skipped, got {pm.step_output_exists.call_count}"
    print(f"✅ last_step from SQL: projA={names['projA']['last_step']}, projB={names['projB']['last_step']}; Storage probes=0")


def _test_list_projects_falls_back_when_sql_empty():
    print("\n--- Test 14: list_projects SQL miss → last_step=0, NO Storage probing ---")
    real_api = _import_real_api()
    pm = _import_project_manager()
    pid_a = str(uuid.uuid4())
    db_uid = str(uuid.uuid4())
    email = "u@e.com"
    pm.get_db_user_id = lambda user: db_uid

    class FakeProjectsTable:
        def select(self, c): return self
        def eq(self, k, v): return self
        def order(self, *a, **k): return self
        def execute(self): return MagicMock(data=[{"id": pid_a, "name": "projA", "created_at": "2026-08-05", "last_activity_at": "2026-08-05", "pdf_storage_path": ""}])

    class FakeStepResultsTable:
        def select(self, c): return self
        def in_(self, k, v): return self
        def eq(self, k, v): return self
        def execute(self): return MagicMock(data=[])  # no SQL rows

    fake_sb = MagicMock()
    fake_sb.table.side_effect = lambda n: FakeProjectsTable() if n == "projects" else FakeStepResultsTable()

    import supabase_client, storage_client
    orig_get_sb = supabase_client.get_supabase
    orig_list_files = storage_client.list_files
    orig_read_file = storage_client.read_file
    orig_list_rec = getattr(storage_client, "list_files_recursive", None)
    supabase_client.get_supabase = lambda: fake_sb
    storage_client.list_files = MagicMock(return_value=[])  # Storage merge finds nothing
    storage_client.read_file = MagicMock(side_effect=Exception("no storage in test"))
    storage_client.list_files_recursive = MagicMock(return_value=[])

    pm.step_output_exists = MagicMock(return_value=False)

    try:
        pm.invalidate_projects_cache()  # fresh compute (both tests use this email)
        projects = pm.list_projects(email)
    finally:
        supabase_client.get_supabase = orig_get_sb
        storage_client.list_files = orig_list_files
        storage_client.read_file = orig_read_file
        if orig_list_rec is not None: storage_client.list_files_recursive = orig_list_rec

    a = next(p for p in projects if p["name"] == "projA")
    # Performance fix: a project with no step_results row reports last_step=0
    # instead of paying up to 10 recursive Storage probes per list call.
    assert a["last_step"] == 0, a
    assert pm.step_output_exists.call_count == 0, "Storage probing must be skipped (perf fix)"
    print(f"✅ SQL miss → last_step=0, Storage probes=0, Storage reads=0")


def _run_all():
    _test_latest_step_result_row_respects_step_filter()
    _test_latest_step_result_row_no_step_returns_latest_overall()
    _test_latest_step_result_row_returns_none_when_project_missing()
    _test_get_step_status_sql_done_short_circuits_storage()
    _test_get_step_status_sql_error_returns_error()
    _test_get_step_status_sql_miss_falls_back_to_storage()
    _test_get_step_output_files_uses_file_manifest()
    _test_get_step_output_files_falls_back_to_storage_when_no_sql()
    _test_get_step_history_shapes_sql_rows_into_blob_contract()
    _test_get_step_history_falls_back_to_blob_when_sql_empty()
    _test_get_project_costs_aggregates_sql_rows()
    _test_get_project_costs_blob_fallback_when_sql_empty()
    _test_list_projects_uses_batch_sql_for_last_step()
    _test_list_projects_falls_back_when_sql_empty()
    print("\n" + "=" * 60)
    print("ALL PR-2 read-pathway tests PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()