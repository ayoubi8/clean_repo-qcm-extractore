"""Tests for PR-3 byte-serving from Storage (PERSISTENCE_FIX_PLAN).

Covers:
- _stream_file_from_storage: downloads, caches, returns bytes; None on miss
- get_step_file_content: FS miss → Storage text + binary, local cache written
- view_step_file / download_step_file: FS miss → cache warm + signed URL
  redirect, last-resort local FileResponse if signed URL unavailable
- get_history_file: current + archived run paths, signed-URL fallback
- step8_merge_outputs: FS miss → read summary from Storage / step_results.payload
"""
import asyncio
import json
import os
import sys
import uuid
import types
import tempfile
import shutil
from pathlib import Path
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


# ---------------- _stream_file_from_storage ----------------

def _test_stream_file_downloads_and_caches():
    print("\n--- Test 1: _stream_file_from_storage downloads bytes + writes cache ---")
    real_api = _import_real_api()
    tmp = Path(tempfile.mkdtemp())
    local_dest = tmp / "output" / "uid" / "proj" / "step2_qcm" / "page_1.json"
    storage_path = "uid/proj/step2_qcm/page_1.json"
    real_api.read_bytes_file = MagicMock(return_value=b'{"qcm":1}')
    data = real_api._stream_file_from_storage(storage_path, local_dest)
    assert data == b'{"qcm":1}', data
    assert local_dest.exists(), "cache file not written"
    assert local_dest.read_bytes() == b'{"qcm":1}'
    real_api.read_bytes_file.assert_called_once_with(storage_path)
    print(f"✅ downloaded + cached at {local_dest}")
    shutil.rmtree(tmp, ignore_errors=True)


def _test_stream_file_returns_none_on_storage_miss():
    print("\n--- Test 2: _stream_file_from_storage returns None when Storage miss ---")
    real_api = _import_real_api()
    tmp = Path(tempfile.mkdtemp())
    def boom(p): raise RuntimeError("404 not found")
    real_api.read_bytes_file = MagicMock(side_effect=boom)
    out = real_api._stream_file_from_storage("uid/p/x", tmp / "x.json")
    assert out is None, out
    print("✅ returns None on Storage failure")


def _test_stream_file_returns_bytes_when_cache_write_fails():
    print("\n--- Test 3: cache write failure still returns bytes ---")
    real_api = _import_real_api()
    real_api.read_bytes_file = MagicMock(return_value=b"data")
    bad_dest = MagicMock()
    bad_dest.parent.mkdir = MagicMock(side_effect=OSError("disk full"))
    bad_dest.write_bytes = MagicMock(side_effect=OSError("disk full"))
    data = real_api._stream_file_from_storage("uid/p/x", bad_dest)
    assert data == b"data", data
    print("✅ bytes returned even when local cache write fails")


# ---------------- get_step_file_content (text + binary) ----------------

def _test_get_step_file_content_text_from_storage():
    print("\n--- Test 4: get_step_file_content returns text from Storage + caches ---")
    real_api = _import_real_api()
    # On Windows /app/output doesn't exist so file_path.exists() is naturally
    # False — we don't monkeypatch Path. _stream_file_from_storage is mocked
    # so no real network/cache write happens.
    captured = {}
    def fake_stream(sp, ld):
        captured["storage_path"] = sp
        captured["local_dest"] = str(ld)
        return b'{"qcm":1}'
    real_api._stream_file_from_storage = MagicMock(side_effect=fake_stream)

    out = real_api.get_step_file_content("proj", "2", "page_1.json", {"id": "uid"})
    assert out == {"content": '{"qcm":1}'}, out
    # On the dev box the local dest resolves to the literal /app/output/... path
    # which doesn't exist — that's fine, the cache write is best-effort.
    assert captured["storage_path"] == "uid/proj/step2_qcm/page_1.json", captured
    print(f"✅ text served from Storage via _stream_file_from_storage (storage_path={captured['storage_path']})")


def _test_get_step_file_content_binary_from_storage():
    print("\n--- Test 5: get_step_file_content returns binary for .xlsx from Storage ---")
    real_api = _import_real_api()
    fake_xlsx = b"PK\x03\x04binaryxlsxcontent"
    real_api._stream_file_from_storage = MagicMock(return_value=fake_xlsx)

    out = real_api.get_step_file_content("proj", "8", "step8_matches.xlsx", {"id": "uid"})
    assert out == {"binary": True, "size": len(fake_xlsx)}, out
    print(f"✅ xlsx served as binary, size={out['size']}")


def _test_get_step_file_content_storage_miss_404():
    print("\n--- Test 6: get_step_file_content Storage miss → 404 ---")
    real_api = _import_real_api()
    real_api._stream_file_from_storage = MagicMock(return_value=None)
    real_api.HTTPException = type("HE", (Exception,), {"__init__": lambda self, **k: Exception.__init__(self, str(k))})

    try:
        real_api.get_step_file_content("proj", "2", "missing.json", {"id": "uid"})
        raise AssertionError("expected HTTPException")
    except Exception as e:
        assert "404" in str(e) or "not found" in str(e).lower(), str(e)
    print("✅ Storage miss raises 404")


# ---------------- view_step_file / download_step_file ----------------

def _test_view_step_file_warm_then_redirect():
    print("\n--- Test 7: view_step_file warms cache then redirects to signed URL ---")
    real_api = _import_real_api()
    real_api._stream_file_from_storage = MagicMock(return_value=b"x")
    real_api.get_signed_url = MagicMock(return_value="https://signed.example.com/x.xlsx")
    real_api.RedirectResponse = MagicMock(return_value="REDIRECT")
    real_api.FileResponse = MagicMock(return_value="FILERES")

    out = real_api.view_step_file("proj", "8", "step8_matches.xlsx", {"id": "uid"})
    assert out == "REDIRECT", out
    real_api._stream_file_from_storage.assert_called_once()  # cache warmed
    real_api.get_signed_url.assert_called_once_with("uid/proj/step8_matches/step8_matches.xlsx")
    print("✅ cache warmed, redirected to signed URL")


def _test_view_step_file_local_hit_no_storage():
    print("\n--- Test 8: view_step_file local FS hit → FileResponse, no Storage call ---")
    real_api = _import_real_api()
    # Patch the global Path so exists()/is_file() return True for any path.
    orig_path = real_api.Path

    class HitPath(orig_path):
        def exists(self): return True
        def is_file(self): return True
        def stat(self): return MagicMock(st_size=100)
    real_api.Path = HitPath
    real_api.mimetypes = MagicMock()
    real_api.mimetypes.guess_type = MagicMock(return_value=("application/vnd.openxmlformats", None))
    real_api.FileResponse = MagicMock(return_value="LOCAL_FILE")
    real_api._stream_file_from_storage = MagicMock()
    real_api.get_signed_url = MagicMock()

    try:
        out = real_api.view_step_file("proj", "8", "step8_matches.xlsx", {"id": "uid"})
    finally:
        real_api.Path = orig_path
    assert out == "LOCAL_FILE", out
    real_api._stream_file_from_storage.assert_not_called()
    real_api.get_signed_url.assert_not_called()
    print("✅ local hit served via FileResponse; Storage never touched")


def _test_download_step_file_storage_signed_url_unavailable_serves_local():
    print("\n--- Test 9: download signed URL fails → serves cached FS file ---")
    real_api = _import_real_api()
    orig_path = real_api.Path

    class HitPath(orig_path):
        def exists(self):
            # First call (initial check) misses → trigger Storage; second call
            # (post-cache-warm) returns True so the FileResponse fallback fires.
            return self._hits > 0
        def __init__(self, *a, **k): super().__init__(*a, **k); self._hits = 0
        def is_file(self): return self.exists()
        def stat(self): return MagicMock(st_size=50)
        @property
        def name(self): return "step8_matches.xlsx"
    class HitPath2(orig_path):
        # Stable version: every call to exists() flips True after first.
        _miss_count = 0
        def exists(self):
            HitPath2._miss_count += 1
            return HitPath2._miss_count > 1
        def is_file(self): return self.exists()
        def stat(self): return MagicMock(st_size=50)
        @property
        def name(self): return "step8_matches.xlsx"
    real_api.Path = HitPath2
    real_api._stream_file_from_storage = MagicMock(return_value=b"PK")
    real_api.get_signed_url = MagicMock(side_effect=RuntimeError("no signed url"))
    real_api.mimetypes = MagicMock()
    real_api.mimetypes.guess_type = MagicMock(return_value=("application/octet-stream", None))
    real_api.FileResponse = MagicMock(return_value="LOCAL_FALLBACK")
    real_api.RedirectResponse = MagicMock()
    real_api.HTTPException = type("HE", (Exception,), {"__init__": lambda self, **k: Exception.__init__(self, str(k))})

    try:
        out = real_api.download_step_file("proj", "8", "step8_matches.xlsx", {"id": "uid"})
    finally:
        real_api.Path = orig_path
    assert out == "LOCAL_FALLBACK", out
    real_api.FileResponse.assert_called_once()
    real_api.RedirectResponse.assert_not_called()
    print("✅ signed-URL fail → served cached local file")


# ---------------- get_history_file ----------------

def _test_get_history_file_warm_then_redirect():
    print("\n--- Test 10: get_history_file warms cache and redirects for a historical run ---")
    real_api = _import_real_api()
    real_api._stream_file_from_storage = MagicMock(return_value=b"x")
    real_api.get_signed_url = MagicMock(return_value="https://signed.example.com/h.json")
    real_api.RedirectResponse = MagicMock(return_value="REDIRECT")
    real_api.FileResponse = MagicMock()

    out = real_api.get_history_file("proj", "2", "2026-01-01", "page_1.json", {"id": "uid"})
    assert out == "REDIRECT", out
    expected_storage = "uid/proj/_history/step2/2026-01-01/page_1.json"
    real_api._stream_file_from_storage.assert_called_once()
    called_sp = real_api._stream_file_from_storage.call_args[0][0]
    assert called_sp == expected_storage, called_sp
    real_api.get_signed_url.assert_called_once_with(expected_storage)
    print(f"✅ history download warmed + redirected, storage={called_sp}")


def _test_get_history_file_current_run_uses_step_folder_path():
    print("\n--- Test 11: get_history_file run_id=='current' uses step folder storage path ---")
    real_api = _import_real_api()
    real_api._stream_file_from_storage = MagicMock(return_value=b"x")
    real_api.get_signed_url = MagicMock(return_value="https://signed.example.com/c.json")
    real_api.RedirectResponse = MagicMock(return_value="REDIRECT")
    real_api.get_history_file("proj", "8", "current", "step8_matches.xlsx", {"id": "uid"})
    expected = "uid/proj/step8_matches/step8_matches.xlsx"
    real_api.get_signed_url.assert_called_once_with(expected)
    print("✅ current run uses step folder storage path")


# ---------------- step8_merge_outputs ----------------

def _test_step8_merge_outputs_reads_summary_from_storage_when_fs_empty():
    print("\n--- Test 12: step8_merge_outputs reads summary from Storage when FS empty ---")
    real_api = _import_real_api()
    tmp = Path(tempfile.mkdtemp())
    base_path = tmp / "uid" / "proj"
    base_path.mkdir(parents=True)
    storage_summary = json.dumps({
        "merge": {
            "ref_updated_filename": "ref_UPDATED.xlsx",
            "merge_report_filename": "merge_report.json",
            "unmerged_filename": "unmerged_qcms.xlsx",
        },
        "totals": {"qcms": 10, "merged": 5},
    })

    ctx = MagicMock()
    ctx.base_path = base_path
    real_api.get_or_create = MagicMock(return_value={"context": ctx})
    real_api._apply_user_env = MagicMock()
    real_api.file_exists = MagicMock(return_value=True)
    real_api.read_file = MagicMock(return_value=storage_summary)
    real_api._latest_step_result_row = MagicMock(return_value={
        "file_manifest": [
            {"path": "step8_summary.json", "size_bytes": 100},
            {"path": "ref_UPDATED.xlsx", "size_bytes": 5000},
            {"path": "merge_report.json", "size_bytes": 200},
            {"path": "unmerged_qcms.xlsx", "size_bytes": 3000},
        ],
        "payload": {},
    })

    manifest = asyncio.run(real_api.step8_merge_outputs("proj", {"id": "uid"}))
    assert "summary" in manifest["files"], manifest["files"]
    assert manifest["files"]["summary"]["filename"] == "step8_summary.json"
    assert "ref_updated" in manifest["files"]
    assert manifest["files"]["ref_updated"]["filename"] == "ref_UPDATED.xlsx"
    assert "merge_report" in manifest["files"]
    assert "unmerged" in manifest["files"]
    # summary content was pulled from Storage (since FS misses)
    real_api.read_file.assert_called_with("uid/proj/step8_matches/step8_summary.json")
    assert manifest["summary"]["totals"]["qcms"] == 10, manifest["summary"]
    print(f"✅ manifest built from Storage: files={list(manifest['files'])}, qcms={manifest['summary']['totals']['qcms']}")
    shutil.rmtree(tmp, ignore_errors=True)


def _test_step8_merge_outputs_uses_sql_payload_when_storage_missing():
    print("\n--- Test 13: step8_merge_outputs falls back to step_results.payload ---")
    real_api = _import_real_api()
    tmp = Path(tempfile.mkdtemp())
    base_path = tmp / "x"
    base_path.mkdir()
    ctx = MagicMock(); ctx.base_path = base_path
    real_api.get_or_create = MagicMock(return_value={"context": ctx})
    real_api._apply_user_env = MagicMock()
    real_api.file_exists = MagicMock(return_value=False)
    real_api.read_file = MagicMock(side_effect=RuntimeError("no storage"))
    payload = {"merge": {"ref_updated_filename": "ref_UPDATED.xlsx"}, "totals": {"qcms": 7}}
    real_api._latest_step_result_row = MagicMock(return_value={
        # The summary file IS listed in the manifest so _info() returns
        # a non-None entry, which opens the summary-from-payload branch.
        "file_manifest": [
            {"path": "step8_summary.json", "size_bytes": 100},
            {"path": "ref_UPDATED.xlsx", "size_bytes": 999},
        ],
        "payload": payload,
    })

    manifest = asyncio.run(real_api.step8_merge_outputs("proj", {"id": "uid"}))
    # summary_info found in manifest → manifest["files"]["summary"] populated.
    # summary content pulled from SQL payload (since Storage / FS both miss).
    assert "summary" in manifest["files"], manifest["files"]
    assert manifest["files"]["summary"]["size_bytes"] == 100, manifest["files"]
    # And because summary is now non-None, the merge-block artifacts are listed.
    assert "ref_updated" in manifest["files"], manifest["files"]
    assert manifest["files"]["ref_updated"]["size_bytes"] == 999, manifest["files"]
    assert manifest.get("summary") == payload, manifest.get("summary")
    print(f"✅ manifest built from SQL payload: files={list(manifest['files'])}, summary.qcms={manifest['summary']['totals']['qcms']}")
    shutil.rmtree(tmp, ignore_errors=True)


def _test_step8_merge_outputs_empty_manifest_when_nothing_available():
    print("\n--- Test 14: step8_merge_outputs empty manifest when no SQL/FS/Storage ---")
    real_api = _import_real_api()
    tmp = Path(tempfile.mkdtemp())
    base_path = tmp / "x"; base_path.mkdir()
    ctx = MagicMock(); ctx.base_path = base_path
    real_api.get_or_create = MagicMock(return_value={"context": ctx})
    real_api._apply_user_env = MagicMock()
    real_api.file_exists = MagicMock(return_value=False)
    real_api.read_file = MagicMock(side_effect=Exception("no"))
    real_api._latest_step_result_row = MagicMock(return_value=None)

    manifest = asyncio.run(real_api.step8_merge_outputs("proj", {"id": "uid"}))
    assert manifest == {"files": {}}, manifest
    print("✅ empty manifest returned (frontend treats as 'not yet run')")
    shutil.rmtree(tmp, ignore_errors=True)


def _run_all():
    _test_stream_file_downloads_and_caches()
    _test_stream_file_returns_none_on_storage_miss()
    _test_stream_file_returns_bytes_when_cache_write_fails()
    _test_get_step_file_content_text_from_storage()
    _test_get_step_file_content_binary_from_storage()
    _test_get_step_file_content_storage_miss_404()
    _test_view_step_file_warm_then_redirect()
    _test_view_step_file_local_hit_no_storage()
    _test_download_step_file_storage_signed_url_unavailable_serves_local()
    _test_get_history_file_warm_then_redirect()
    _test_get_history_file_current_run_uses_step_folder_path()
    _test_step8_merge_outputs_reads_summary_from_storage_when_fs_empty()
    _test_step8_merge_outputs_uses_sql_payload_when_storage_missing()
    _test_step8_merge_outputs_empty_manifest_when_nothing_available()
    print("\n" + "=" * 60)
    print("ALL PR-3 byte-serving tests PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()