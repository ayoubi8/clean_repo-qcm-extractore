"""Tests for persistence layer (PERSISTENCE_FIX_PLAN PR-1).

Covers:
- modules/utils/result_manifest.build_file_manifest + summarize_step (pure)
- api/real_api._record_step_result + _record_step_costs (mocked supabase)
- _resolve_project_id + _is_uuid helpers
"""
import json
import os
import sys
import shutil
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "api"))


# ---------------- pure helpers ----------------

def _test_build_file_manifest_basic():
    print("\n--- Test 1: build_file_manifest lists files with size+kind+sha ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "accepted").mkdir()
        (tmp / "accepted" / "page_1.json").write_text('[{"number":1}]', encoding="utf-8")
        (tmp / "accepted" / "page_2.json").write_text('[{"number":2}]', encoding="utf-8")
        (tmp / "all_qcms.json").write_text('[]', encoding="utf-8")
        from modules.utils.result_manifest import build_file_manifest
        m = build_file_manifest(tmp, "uid/proj/step2_qcm")
        paths = sorted(e["path"] for e in m)
        assert paths == ["accepted/page_1.json", "accepted/page_2.json", "all_qcms.json"], paths
        kinds = {e["path"]: e["kind"] for e in m}
        assert kinds["accepted/page_1.json"] == "json", kinds
        sizes = {e["path"]: e["size_bytes"] for e in m}
        assert sizes["accepted/page_1.json"] == len('[{"number":1}]'), sizes
        sha = next(e["sha256"] for e in m if e["path"] == "accepted/page_1.json")
        assert len(sha) == 64, sha
        print(f"✅ manifest has {len(m)} entries with kind/size/sha256")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_build_file_manifest_empty():
    print("\n--- Test 2: build_file_manifest on missing dir → [] ---")
    from modules.utils.result_manifest import build_file_manifest
    m = build_file_manifest(Path("/nonexistent/x/y/z"), "uid/proj/x")
    assert m == [], m
    print("✅ missing dir returns []")


def _test_summarize_step_combines_stats_and_counts():
    print("\n--- Test 3: summarize_step merges badge stats + file counts ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "page_1.json").write_text('[]', encoding="utf-8")
        (tmp / "page_2.json").write_text('[]', encoding="utf-8")
        (tmp / "sub").mkdir()
        (tmp / "sub" / "deep.json").write_text('[]', encoding="utf-8")
        from modules.utils.result_manifest import summarize_step
        payload = summarize_step("2", tmp, {"qcms": 14, "empty_pages": 1})
        assert payload["qcms"] == 14, payload
        assert payload["empty_pages"] == 1, payload
        assert payload["file_count"] == 3, payload
        assert payload["total_bytes"] == len('[]') * 3, payload
        print(f"✅ payload={payload}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_summarize_step_missing_dir():
    print("\n--- Test 4: summarize_step with missing dir returns just stats ---")
    from modules.utils.result_manifest import summarize_step
    payload = summarize_step("8", Path("/no/such"), {"merged": 5})
    assert payload == {"merged": 5}, payload
    print(f"✅ payload={payload}")


# ---------------- _record_step_result (mocked supabase) ----------------

def _import_real_api():
    """Import real_api with stubbed supabase/storage so importing doesn't
    require real credentials. We only need the helper functions, not the
    FastAPI app wiring."""
    # Stub heavy deps that real_api imports unconditionally
    import types
    # google deps can be missing in test env
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


def _test_is_uuid():
    print("\n--- Test 5: _is_uuid helper ---")
    real_api = _import_real_api()
    assert real_api._is_uuid(str(uuid.uuid4())) is True
    assert real_api._is_uuid("not-a-uuid") is False
    assert real_api._is_uuid("user@example.com") is False
    print("✅ _is_uuid distinguishes uuids vs other ids")


def _test_resolve_project_id_hits_supabase():
    print("\n--- Test 6: _resolve_project_id queries projects table ---")
    real_api = _import_real_api()
    uid = str(uuid.uuid4())
    fake_sb = MagicMock()
    # Build the chain so execute().data is a real list with one row
    fake_chain = MagicMock()
    fake_chain.limit.return_value.execute.return_value = MagicMock(data=[{"id": "proj-uuid-1"}])
    fake_chain.eq.return_value = fake_chain  # second .eq returns same chain
    fake_sb.table.return_value.select.return_value = fake_chain
    real_api.get_supabase = lambda: fake_sb
    real_api.get_db_user_id = MagicMock()
    pid = real_api._resolve_project_id(uid, "myproj")
    assert pid == "proj-uuid-1", pid
    print(f"✅ resolved project_id={pid}")


def _test_record_step_result_inserts_rows():
    print("\n--- Test 7: _record_step_result upserts step_results + step_history ---")
    real_api = _import_real_api()
    uid = str(uuid.uuid4())
    project = "exam1"
    project_id = str(uuid.uuid4())

    # Patch the manifest helpers (imported at call-time inside the function
    # via `from modules.utils.result_manifest import ...`) so we control the
    # payload without needing a real /app/output tree.
    import modules.utils.result_manifest as rm
    canned_manifest = [
        {"path": "accepted/page_1.json", "size_bytes": 12, "sha256": "abc", "kind": "json"},
        {"path": "all_qcms.json", "size_bytes": 2, "sha256": "def", "kind": "json"},
    ]
    rm.build_file_manifest = lambda d, p: canned_manifest
    rm.summarize_step = lambda sid, sd, st: {"qcms": 5, "file_count": 2, **(st or {})}

    try:
        inserted_step_results = []
        inserted_step_history = []

        class FakeTable:
            def __init__(self, name):
                self.name = name
            def upsert(self, row, on_conflict=None):
                if self.name == "step_results":
                    inserted_step_results.append(row)
                return MagicMock()
            def insert(self, row):
                if self.name == "step_history":
                    inserted_step_history.append(row)
                return MagicMock()

        fake_sb = MagicMock()
        fake_sb.table.side_effect = FakeTable
        real_api.get_supabase = lambda: fake_sb
        real_api.get_db_user_id = MagicMock(return_value=uid)
        real_api._resolve_project_id = lambda u, p: project_id

        import time as _t
        start = _t.time() - 3.0
        real_api._record_step_result(
            project, uid, "2", "2026-01-01T00-00-00", start,
            "success", {"qcms": 5, "empty_pages": 0},
            "step2_qcm", auto_build_folders=["step3_metadata", "step5_json"],
        )
        # One step_results upsert per folder (step2_qcm + 2 auto-build)
        assert len(inserted_step_results) == 3, f"got {len(inserted_step_results)}: {inserted_step_results}"
        assert len(inserted_step_history) == 3, f"history: {len(inserted_step_history)}"
        primary_row = next(r for r in inserted_step_results if r["step_number"] == "2")
        assert primary_row["project_id"] == project_id
        assert primary_row["badge"] == "success"
        assert primary_row["storage_prefix"].endswith("step2_qcm"), primary_row["storage_prefix"]
        assert primary_row["file_manifest"] == canned_manifest
        step_numbers = sorted(r["step_number"] for r in inserted_step_results)
        # auto-build folders map to step numbers: step3_metadata → "3", step5_json → "5"
        assert "3" in step_numbers and "5" in step_numbers, step_numbers
        # history rows carry the run_id in metadata
        hist_meta = [r["metadata"].get("run_id") for r in inserted_step_history]
        assert all(r == "2026-01-01T00-00-00" for r in hist_meta), hist_meta
        print(f"✅ inserted {len(inserted_step_results)} step_results rows + {len(inserted_step_history)} history rows")
    finally:
        import importlib
        importlib.reload(rm)


def _test_record_step_result_no_project_row_is_safe():
    print("\n--- Test 8: _record_step_result noops when projects row missing ---")
    real_api = _import_real_api()
    real_api._resolve_project_id = lambda u, p: None
    real_api.get_supabase = MagicMock()
    real_api._record_step_result("p", "u", "2", "r", 0.0, "success", {}, "step2_qcm")
    # Should not have called supabase at all
    real_api.get_supabase.assert_not_called()
    print("✅ noop when project not in SQL")


def _test_record_step_costs_inserts_one_row():
    print("\n--- Test 9: _record_step_costs inserts a costs row from tracker ---")
    real_api = _import_real_api()
    project_id = str(uuid.uuid4())
    real_api._resolve_project_id = lambda u, p: project_id
    inserted = []

    class FakeTable:
        def __init__(self, name): self.name = name
        def insert(self, row):
            inserted.append(row); return MagicMock()

    fake_sb = MagicMock()
    fake_sb.table.side_effect = FakeTable
    real_api.get_supabase = lambda: fake_sb

    tracker = MagicMock()
    tracker.get_step_summary.return_value = {"total_cost": 0.12, "total_tokens": {"prompt": 100, "completion": 400}}
    real_api._record_step_costs(str(uuid.uuid4()), "proj", "2", tracker)
    assert len(inserted) == 1, inserted
    assert inserted[0]["cost_usd"] == 0.12, inserted[0]
    assert inserted[0]["tokens"] == 500, inserted[0]
    assert inserted[0]["step_number"] == "2", inserted[0]
    print(f"✅ costs row inserted: {inserted[0]}")


def _test_record_step_costs_handles_missing_tracker():
    print("\n--- Test 10: _record_step_costs handles missing tracker/summary ---")
    real_api = _import_real_api()
    real_api._resolve_project_id = lambda u, p: str(uuid.uuid4())
    fake_sb = MagicMock()
    real_api.get_supabase = lambda: fake_sb
    tracker = MagicMock()
    tracker.get_step_summary.return_value = None
    real_api._record_step_costs("u", "p", "2", tracker)
    fake_sb.table.assert_not_called()
    # Also None tracker path:
    real_api._record_step_costs("u", "p", "2", None)
    fake_sb.table.assert_not_called()
    print("✅ safely noops when no summary/tracker")


def _run_all():
    _test_build_file_manifest_basic()
    _test_build_file_manifest_empty()
    _test_summarize_step_combines_stats_and_counts()
    _test_summarize_step_missing_dir()
    _test_is_uuid()
    _test_resolve_project_id_hits_supabase()
    _test_record_step_result_inserts_rows()
    _test_record_step_result_no_project_row_is_safe()
    _test_record_step_costs_inserts_one_row()
    _test_record_step_costs_handles_missing_tracker()
    print("\n" + "=" * 60)
    print("ALL persistence PR-1 tests PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()