"""Tests for PR-4 eager startup + Storage backfill (PERSISTENCE_FIX_PLAN).

Covers:
- project_manager.rebuild_project_registry_from_db + PROJECT_REGISTRY + lookup_project_id
- real_api._eager_rebuild_registry wrapper
- real_api._backfill_step_results_from_storage:
  * probes step_results table (skips if missing)
  * skips when PROJECT_REGISTRY is empty
  * walks the per-(proj,step) Storage prefixes; skips folders with no real files
  * upserts one synthetic row per missing step (run_id="backfill")
  * skips (proj, step) already present in SQL
  * idempotent (existing rows are loaded first)
- real_api startup hook wiring
"""
import asyncio
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


# ---------------- rebuild_project_registry_from_db ----------------

def _test_rebuild_registry_caches_all_projects():
    print("\n--- Test 1: rebuild_project_registry_from_db caches all rows ---")
    import project_manager
    import supabase_client
    p1, p2 = str(uuid.uuid4()), str(uuid.uuid4())
    uid1, uid2 = str(uuid.uuid4()), str(uuid.uuid4())
    rows = [
        {"id": p1, "user_id": uid1, "name": "projA"},
        {"id": p2, "user_id": uid2, "name": "projB"},
    ]
    class FakeChain:
        def select(self, c): return self
        def execute(self): return MagicMock(data=rows)
    fake_sb = MagicMock(); fake_sb.table.return_value = FakeChain()
    orig_get_sb = supabase_client.get_supabase
    supabase_client.get_supabase = lambda: fake_sb
    project_manager.PROJECT_REGISTRY.clear()
    try:
        n = project_manager.rebuild_project_registry_from_db()
    finally:
        supabase_client.get_supabase = orig_get_sb
    assert n == 2, n
    assert project_manager.PROJECT_REGISTRY[f"{uid1}/projA"]["project_id"] == p1
    assert project_manager.PROJECT_REGISTRY[f"{uid2}/projB"]["project_id"] == p2
    print(f"✅ cached {n} rows: {list(project_manager.PROJECT_REGISTRY.keys())}")


def _test_rebuild_registry_clears_previous_cache():
    print("\n--- Test 2: rebuild clears existing cache before populating ---")
    import project_manager
    import supabase_client
    project_manager.PROJECT_REGISTRY.clear()
    project_manager.PROJECT_REGISTRY["stale/old"] = {"project_id": "x", "user_id": "stale", "name": "old"}
    class FakeChain:
        def select(self, c): return self
        def execute(self): return MagicMock(data=[{"id":"new","user_id":"new_uid","name":"new"}])
    fake_sb = MagicMock(); fake_sb.table.return_value = FakeChain()
    orig_get_sb = supabase_client.get_supabase
    supabase_client.get_supabase = lambda: fake_sb
    try:
        project_manager.rebuild_project_registry_from_db()
    finally:
        supabase_client.get_supabase = orig_get_sb
    assert "stale/old" not in project_manager.PROJECT_REGISTRY, project_manager.PROJECT_REGISTRY
    assert "new_uid/new" in project_manager.PROJECT_REGISTRY
    print("✅ stale row evicted, fresh row cached")


def _test_lookup_project_id_cache_hit():
    print("\n--- Test 3: lookup_project_id returns cached value without SQL ---")
    import project_manager
    import supabase_client
    project_manager.PROJECT_REGISTRY.clear()
    pid = str(uuid.uuid4())
    uid = str(uuid.uuid4())
    project_manager.PROJECT_REGISTRY[f"{uid}/p"] = {"project_id": pid, "user_id": uid, "name": "p"}
    fake_sb = MagicMock()
    orig_get_sb = supabase_client.get_supabase
    supabase_client.get_supabase = lambda: fake_sb
    try:
        out = project_manager.lookup_project_id(uid, "p")
    finally:
        supabase_client.get_supabase = orig_get_sb
    assert out == pid, out
    fake_sb.table.assert_not_called()  # no SQL round-trip
    print(f"✅ cache hit, no SQL call")


def _test_lookup_project_id_cache_miss_queries_sql():
    print("\n--- Test 4: lookup_project_id SQL fill on cache miss ---")
    import project_manager
    import supabase_client
    project_manager.PROJECT_REGISTRY.clear()
    pid = str(uuid.uuid4())
    uid = str(uuid.uuid4())
    class FakeChain:
        def select(self, c): return self
        def eq(self, k, v): return self
        def limit(self, n): return self
        def execute(self): return MagicMock(data=[{"id": pid, "user_id": uid, "name": "p"}])
    fake_sb = MagicMock(); fake_sb.table.return_value = FakeChain()
    orig_get_sb = supabase_client.get_supabase
    supabase_client.get_supabase = lambda: fake_sb
    try:
        out = project_manager.lookup_project_id(uid, "p")
        assert out == pid, out
        # Second call should NOT hit SQL again.
        fake_sb.table.reset_mock()
        out2 = project_manager.lookup_project_id(uid, "p")
        assert out2 == pid, out2
        fake_sb.table.assert_not_called()
    finally:
        supabase_client.get_supabase = orig_get_sb
    print("✅ cache miss → SQL fill → subsequent call cached")


def _test_lookup_project_id_returns_none_when_not_in_db():
    print("\n--- Test 5: lookup_project_id returns None when row missing ---")
    import project_manager
    import supabase_client
    project_manager.PROJECT_REGISTRY.clear()
    class FakeChain:
        def select(self, c): return self
        def eq(self, k, v): return self
        def limit(self, n): return self
        def execute(self): return MagicMock(data=[])
    fake_sb = MagicMock(); fake_sb.table.return_value = FakeChain()
    orig_get_sb = supabase_client.get_supabase
    supabase_client.get_supabase = lambda: fake_sb
    try:
        out = project_manager.lookup_project_id("u", "missing")
    finally:
        supabase_client.get_supabase = orig_get_sb
    assert out is None, out
    print("✅ returns None when row missing")


# ---------------- _eager_rebuild_registry wrapper ----------------

def _test_eager_rebuild_registry_calls_pm_helper():
    print("\n--- Test 6: _eager_rebuild_registry calls project_manager.rebuild_* ---")
    real_api = _import_real_api()
    import project_manager
    called = []
    orig = project_manager.rebuild_project_registry_from_db
    project_manager.rebuild_project_registry_from_db = lambda: called.append(1) or 5
    try:
        real_api._eager_rebuild_registry()
    finally:
        project_manager.rebuild_project_registry_from_db = orig
    assert called == [1], called
    print("✅ wrapper invoked the PM helper")


def _test_eager_rebuild_registry_swallows_errors():
    print("\n--- Test 7: _eager_rebuild_registry swallows errors ---")
    import io
    from contextlib import redirect_stdout
    real_api = _import_real_api()
    import project_manager
    project_manager.rebuild_project_registry_from_db = MagicMock(side_effect=RuntimeError("boom"))
    buf = io.StringIO()
    with redirect_stdout(buf):
        real_api._eager_rebuild_registry()
    assert "eager registry rebuild failed" in buf.getvalue(), buf.getvalue()
    print("✅ error logged, no exception raised")


# ---------------- _backfill_step_results_from_storage ----------------

def _test_backfill_skips_when_table_missing():
    print("\n--- Test 8: backfill skips silently when step_results table missing ---")
    import io
    from contextlib import redirect_stdout
    real_api = _import_real_api()
    fake_sb = MagicMock()
    chain = MagicMock()
    chain.select.return_value = chain
    chain.limit.return_value = chain
    chain.execute.side_effect = RuntimeError("relation step_results does not exist")
    fake_sb.table.return_value = chain
    real_api.get_supabase = lambda: fake_sb
    import project_manager
    project_manager.PROJECT_REGISTRY = {"u/p": {"project_id":"x","user_id":"u","name":"p"}}
    buf = io.StringIO()
    with redirect_stdout(buf):
        n = real_api._backfill_step_results_from_storage()
    assert n == 0, n
    assert "table missing" in buf.getvalue() or "does not exist" in buf.getvalue(), buf.getvalue()
    print("✅ backfill aborted with 0 rows on missing table")


def _test_backfill_skips_when_registry_empty():
    print("\n--- Test 9: backfill skips when PROJECT_REGISTRY empty ---")
    import io
    from contextlib import redirect_stdout
    real_api = _import_real_api()
    fake_sb = MagicMock()
    probe_chain = MagicMock()
    probe_chain.select.return_value = probe_chain
    probe_chain.limit.return_value = probe_chain
    probe_chain.execute.return_value = MagicMock(data=[{"id":"row"}])
    fake_sb.table.return_value = probe_chain
    real_api.get_supabase = lambda: fake_sb
    import project_manager
    project_manager.PROJECT_REGISTRY = {}  # empty
    real_api.list_files = MagicMock()  # should never be called
    buf = io.StringIO()
    with redirect_stdout(buf):
        n = real_api._backfill_step_results_from_storage()
    assert n == 0, n
    real_api.list_files.assert_not_called()
    print("✅ backfill no-op with empty registry; Storage never probed")


def _test_backfill_inserts_synthetic_rows_for_missing_steps():
    print("\n--- Test 10: backfill inserts synthetic rows for missing steps ---")
    real_api = _import_real_api()
    pid = str(uuid.uuid4()); uid = str(uuid.uuid4()); pname = "exam"
    import project_manager
    project_manager.PROJECT_REGISTRY = {
        f"{uid}/{pname}": {"project_id": pid, "user_id": uid, "name": pname},
    }

    # Step_results probe OK; existing-rows SELECT returns empty (so every
    # folder we discover will trigger an upsert).
    upserts = []
    class FakeExistingChain:
        def select(self, c): return self
        def execute(self): return MagicMock(data=[])
    class FakeUpsertChain:
        def __init__(self, name): self.name = name
        def select(self, c): return self
        def limit(self, n): return self
        def execute(self):
            if self.name == "step_results":
                return MagicMock(data=[{"id": "probe"}])  # probe succeeds
            return MagicMock(data=[])
        def upsert(self, row, on_conflict=None):
            upserts.append((row, on_conflict)); return self
    fake_sb = MagicMock()
    fake_sb.table.side_effect = lambda n: FakeUpsertChain(n)
    real_api.get_supabase = lambda: fake_sb

    # Storage list_files: only step2_qcm and step8_matches have files.
    def fake_list_files(prefix):
        if prefix == f"{uid}/{pname}/step2_qcm":
            return [{"id":"f1","name":"all_qcms.json","metadata":{"size":1024}}]
        if prefix == f"{uid}/{pname}/step8_matches":
            return [{"id":"f2","name":"step8_matches.xlsx","metadata":{"size":50000}},
                    {"id":"f3","name":"step8_summary.json","metadata":{"size":400}}]
        return []  # other step folders → empty → skip
    real_api.list_files = MagicMock(side_effect=fake_list_files)

    n = real_api._backfill_step_results_from_storage()
    assert n == 2, n
    assert len(upserts) == 2, upserts
    sids = sorted(u[0]["step_number"] for u in upserts)
    assert sids == ["2", "8"], sids
    # both synthetic rows use run_id="backfill"
    assert all(u[0]["run_id"] == "backfill" for u in upserts), upserts
    # manifests are populated from Storage file metadata (no downloads)
    step2_row = next(u[0] for u in upserts if u[0]["step_number"] == "2")
    assert step2_row["file_manifest"][0]["path"] == "all_qcms.json", step2_row
    assert step2_row["file_manifest"][0]["size_bytes"] == 1024, step2_row
    assert step2_row["payload"]["backfill"] is True
    assert step2_row["storage_prefix"] == f"{uid}/{pname}/step2_qcm"
    # conflict key passed
    assert upserts[0][1] == "project_id,step_number,run_id"
    print(f"✅ inserted {n} synthetic rows: steps={sids}")


def _test_backfill_skips_existing_real_run_rows():
    print("\n--- Test 11: backfill skips (proj, step) already in SQL ---")
    real_api = _import_real_api()
    pid = str(uuid.uuid4()); uid = str(uuid.uuid4()); pname = "exam"
    import project_manager
    project_manager.PROJECT_REGISTRY = {
        f"{uid}/{pname}": {"project_id": pid, "user_id": uid, "name": pname},
    }
    # Simulate step 2 already recorded (e.g. by a real run after PR-1).
    existing_rows = [{"project_id": pid, "step_number": "2"}]
    upserts = []
    class FakeChain:
        def __init__(self, name): self.name = name
        def select(self, c): return self
        def limit(self, n): return self
        def execute(self):
            if self.name == "step_results":
                # probe succeeds (data non-empty)
                return MagicMock(data=[{"id":"probe"}])
            raise AssertionError("only step_results accessed for existing fetch")
        def upsert(self, row, on_conflict=None):
            upserts.append(row); return self
    # First call returns probe; second SELECT (existing rows) returns the
    # existing rows; we use side_effect to differentiate.
    class FakeTable:
        def __init__(self, name): self.name = name
        def select(self, c):
            return self
        def limit(self, n): return self
        def execute(self):
            if self.name == "step_results":
                # Probe call returns [], then existing-rows call returns existing rows.
                # We can't differentiate, so we just return existing_rows on every call.
                return MagicMock(data=existing_rows if existing_rows else [{"id":"x"}])
            return MagicMock(data=[])
        def upsert(self, row, on_conflict=None):
            upserts.append(row); return self
    fake_sb = MagicMock()
    fake_sb.table.side_effect = lambda n: FakeTable(n)
    real_api.get_supabase = lambda: fake_sb

    def fake_list_files(prefix):
        # step2 has files, but it's already in existing_rows → must be skipped.
        if prefix.endswith("/step2_qcm"):
            return [{"id":"f","name":"all_qcms.json"}]
        if prefix.endswith("/step7_categories"):
            return [{"id":"f","name":"final_qcms.json"}]
        return []
    real_api.list_files = MagicMock(side_effect=fake_list_files)

    n = real_api._backfill_step_results_from_storage()
    # step 2 already in existing → skip; step 7 new → 1 insert
    assert n == 1, n
    assert upserts[0]["step_number"] == "7", upserts
    print("✅ existing rows skipped, only missing step inserted")


def _test_backfill_handles_upsert_failure_gracefully():
    print("\n--- Test 12: backfill logs but continues when upsert fails ---")
    import io
    from contextlib import redirect_stdout
    real_api = _import_real_api()
    pid = str(uuid.uuid4()); uid = str(uuid.uuid4()); pname = "exam"
    import project_manager
    project_manager.PROJECT_REGISTRY = {
        f"{uid}/{pname}": {"project_id": pid, "user_id": uid, "name": pname},
    }
    upserts = []
    class FakeChain:
        def __init__(self, name): self.name = name; self._count = 0
        def select(self, c): return self
        def limit(self, n): return self
        def execute(self):
            self._count += 1
            # probe call returns data so the table is "present"
            return MagicMock(data=[{"id":"x"}])
        def upsert(self, row, on_conflict=None):
            upserts.append(row)
            raise RuntimeError("upsert blew up")
    fake_sb = MagicMock(); fake_sb.table.side_effect = lambda n: FakeChain(n)
    real_api.get_supabase = lambda: fake_sb
    def fake_list_files(prefix):
        if prefix.endswith("/step2_qcm"):
            return [{"id":"f","name":"x.json"}]
        if prefix.endswith("/step8_matches"):
            return [{"id":"f","name":"y.xlsx"}]
        return []
    real_api.list_files = MagicMock(side_effect=fake_list_files)
    buf = io.StringIO()
    with redirect_stdout(buf):
        n = real_api._backfill_step_results_from_storage()
    # Even though every upsert threw, we keep going (counter stays 0)
    assert n == 0, n
    assert len(upserts) == 2, upserts  # tried both
    log = buf.getvalue()
    assert "upsert failed" in log, log
    print(f"✅ {len(upserts)} upsert failures logged; final counter={n}")


# ---------------- startup hook wiring ----------------

def _test_startup_event_invokes_eager_rebuild_and_backfill():
    print("\n--- Test 13: startup_event invokes _eager_rebuild_registry + backfill ---")
    real_api = _import_real_api()
    called = []
    real_api._migrate_legacy_projects = lambda: called.append("migrate")
    real_api._backfill_projects_to_db = lambda: called.append("backfill_proj")
    real_api._eager_rebuild_registry = lambda: called.append("eager")
    real_api._backfill_step_results_from_storage = lambda: called.append("backfill_sr") or 0
    asyncio.run(real_api.startup_event())
    assert called == ["migrate", "backfill_proj", "eager", "backfill_sr"], called
    print(f"✅ startup_event order: {called}")


def _test_startup_event_continues_when_backfill_raises():
    print("\n--- Test 14: startup_event survives a backfill exception ---")
    import io
    from contextlib import redirect_stdout
    real_api = _import_real_api()
    real_api._migrate_legacy_projects = MagicMock()
    real_api._backfill_projects_to_db = MagicMock()
    real_api._eager_rebuild_registry = MagicMock()
    real_api._backfill_step_results_from_storage = MagicMock(side_effect=RuntimeError("ok"))
    buf = io.StringIO()
    with redirect_stdout(buf):
        asyncio.run(real_api.startup_event())  # must NOT raise
    assert "step_results backfill failed" in buf.getvalue(), buf.getvalue()
    print("✅ startup_event swallowed the backfill exception")


def _run_all():
    _test_rebuild_registry_caches_all_projects()
    _test_rebuild_registry_clears_previous_cache()
    _test_lookup_project_id_cache_hit()
    _test_lookup_project_id_cache_miss_queries_sql()
    _test_lookup_project_id_returns_none_when_not_in_db()
    _test_eager_rebuild_registry_calls_pm_helper()
    _test_eager_rebuild_registry_swallows_errors()
    _test_backfill_skips_when_table_missing()
    _test_backfill_skips_when_registry_empty()
    _test_backfill_inserts_synthetic_rows_for_missing_steps()
    _test_backfill_skips_existing_real_run_rows()
    _test_backfill_handles_upsert_failure_gracefully()
    _test_startup_event_invokes_eager_rebuild_and_backfill()
    _test_startup_event_continues_when_backfill_raises()
    print("\n" + "=" * 60)
    print("ALL PR-4 startup + backfill tests PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()