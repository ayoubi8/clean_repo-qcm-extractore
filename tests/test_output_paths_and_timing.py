"""Lag plan phases 0-1 (backend): S1 path safety, B1 sync auth, B2 Server-Timing.
Plan: docs/plans/frontend-routes-and-switch-lag-plan.md."""
import asyncio
import inspect
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

import output_paths as op  # noqa: E402


@pytest.fixture
def out_root(tmp_path, monkeypatch):
    monkeypatch.setenv("QCM_OUTPUT_ROOT", str(tmp_path))
    return tmp_path


BAD_NAMES = [
    "../../other-user/proj/step6_corrections/corrected_qcms.json",
    "../step2_qcm/all_qcms.json",
    "accepted/../../../x.json",
    "/etc/passwd",
    "..\\..\\x.json",
    "C:/Windows/win.ini",
    "",
    "./",
]


@pytest.mark.parametrize("name", BAD_NAMES)
def test_traversal_rejected(out_root, name):
    with pytest.raises(HTTPException) as e:
        op.safe_output_path("u1", "proj", "6", name)
    assert e.value.status_code == 400


@pytest.mark.parametrize("project", ["..", ".", "a/b", "a\\b", ""])
def test_bad_project_name_rejected(out_root, project):
    with pytest.raises(HTTPException):
        op.safe_output_path("u1", project, "6", "x.json")


def test_good_paths(out_root):
    local, key = op.safe_output_path("u1", "gyneco 2025", "2", "accepted/all_qcms.json")
    assert local == out_root / "u1" / "gyneco 2025" / "step2_qcm" / "accepted" / "all_qcms.json"
    assert key == "u1/gyneco 2025/step2_qcm/accepted/all_qcms.json"
    local, key = op.safe_history_path("u1", "p", "6", "run_20261121", "corrected_qcms.json")
    assert key == "u1/p/_history/step6/run_20261121/corrected_qcms.json"
    assert op.safe_history_path("u1", "p", "6", "current", "a.json")[1] == "u1/p/step6_corrections/a.json"
    with pytest.raises(HTTPException):
        op.safe_history_path("u1", "p", "6", "..", "a.json")


def test_symlink_escape_rejected(out_root):
    outside = out_root / "secret"
    outside.mkdir()
    (outside / "s.json").write_text("{}")
    step = out_root / "u1" / "p" / "step6_corrections"
    step.mkdir(parents=True)
    try:
        (step / "link").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted here")
    with pytest.raises(HTTPException):
        op.safe_output_path("u1", "p", "6", "link/s.json")


def _real_api():
    import importlib
    import real_api
    return importlib.reload(real_api)


def test_endpoints_reject_traversal(out_root):
    api = _real_api()
    user = {"id": "u1"}
    bad = "../../u2/p/step6_corrections/corrected_qcms.json"
    calls = [
        lambda: api.get_step_file_content("p", "6", bad, user),
        lambda: api.view_step_file("p", "6", bad, user),
        lambda: api.download_step_file("p", "6", bad, user),
        lambda: api.get_history_file("p", "6", "current", bad, user),
        lambda: api.get_history_file("p", "6", "../../u2", "x.json", user),
        lambda: api.open_in_google_sheets("p", "6", {"filename": bad}, user),
        lambda: api.delete_step_output_file("p", "6", bad, user),
    ]
    for call in calls:
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 400


def test_auth_dependency_is_sync():
    import auth
    # B1: a sync dependency runs in FastAPI's thread pool, so its blocking
    # Supabase lookup can no longer freeze the event loop.
    assert not inspect.iscoroutinefunction(auth.get_current_user)


def test_server_timing_header():
    from server_timing import ServerTimingMiddleware

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    sent = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "http.request"}

    asyncio.run(ServerTimingMiddleware(app)({"type": "http", "method": "GET", "path": "/x"}, receive, send))
    headers = dict(sent[0]["headers"])
    assert headers[b"server-timing"].startswith(b"app;dur=")
    assert headers[b"timing-allow-origin"] == b"*"
    assert sent[1]["body"] == b"ok"
