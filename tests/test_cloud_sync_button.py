"""The cloud_sync button end to end, with Google and Storage faked."""
import json
import sys
from pathlib import Path as RealPath
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

ROOT = RealPath(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

import real_api as ra  # noqa: E402

HEADER = ["Num", "Text", "A", "B", "Correct", "Tag", "uid"]


def row(num, text="Question", correct="A"):
    return [str(num), f"{text} {num}", "a", "b", correct, "['Alger']", f"u{num}"]


def stored(num, text="Question", correct="A"):
    return {"Num": num, "Text": f"{text} {num}", "A": "a", "B": "b", "Correct": correct,
            "Tag": ["Alger"], "uid": f"u{num}", "papers": [{"keep": True}]}


class FakeSheets:
    def __init__(self, grid):
        self.grid = grid

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, **kw):
        return SimpleNamespace(execute=lambda: {"values": self.grid})


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(ra, "Path", lambda p: RealPath(str(p).replace("/app/output", str(tmp_path))))
    storage = {}
    monkeypatch.setattr(ra, "write_file", lambda p, c: storage.__setitem__(p, c))
    monkeypatch.setattr(ra, "write_bytes_file", lambda p, c: storage.__setitem__(p, c))

    def read(path):
        if path not in storage:
            raise FileNotFoundError(path)
        value = storage[path]
        return value.decode("utf-8") if isinstance(value, bytes) else value
    monkeypatch.setattr(ra, "read_file", read)
    monkeypatch.setattr(ra, "read_bytes_file",
                        lambda p: storage[p] if isinstance(storage[p], bytes) else storage[p].encode("utf-8"))
    monkeypatch.setattr(ra, "list_files_recursive", lambda p: [])
    monkeypatch.setattr(ra, "_archive_superseded_xlsx", lambda *a, **k: [])
    monkeypatch.setattr(ra, "_get_google_creds", lambda uid: "creds" if uid == "db-id" else None)
    monkeypatch.setattr(ra, "get_db_user_id", lambda user: "db-id")

    base = tmp_path / "admin" / "p"
    (base / "step6_corrections").mkdir(parents=True)
    (base / "step6_corrections" / "_sheets_meta.json").write_text(
        json.dumps({"sheet_id": "S1", "filename": "2_corrections_x.xlsx"}), encoding="utf-8")
    (base / "step6_corrections" / "corrected_qcms.json").write_text(
        json.dumps([stored(1), stored(2), stored(3), stored(4)]), encoding="utf-8")

    def use_grid(grid):
        monkeypatch.setattr(ra, "build", lambda *a, **k: FakeSheets(grid))

    return SimpleNamespace(base=base, storage=storage, use_grid=use_grid)


def saved(project):
    return json.loads((project.base / "step6_corrections" / "corrected_qcms.json").read_text(encoding="utf-8"))


def test_admin_finds_token_saved_under_db_id_and_edit_keeps_hidden_fields(project):
    project.use_grid([HEADER, row(1, "Edited"), row(2), row(3), row(4)])
    result = ra._sync_step_from_sheets_svc("p", "6", "admin")
    rows = saved(project)
    assert result["total"] == 4 and rows[0]["Text"] == "Edited 1"
    assert rows[0]["papers"] == [{"keep": True}] and rows[0]["Tag"] == ["Alger"]


def test_deleting_a_row_removes_only_that_row(project):
    project.use_grid([HEADER, row(1), row(3), row(4)])
    result = ra._sync_step_from_sheets_svc("p", "6", "admin")
    assert result["deleted_count"] == 1
    assert [q["uid"] for q in saved(project)] == ["u1", "u3", "u4"]
    assert saved(project)[0]["papers"] == [{"keep": True}]


def test_stale_cell_does_not_undo_a_newer_value(project):
    grid = [HEADER, row(1), row(2), row(3), row(4)]
    project.use_grid(grid)
    ra._sync_step_from_sheets_svc("p", "6", "admin")
    path = project.base / "step6_corrections" / "corrected_qcms.json"
    rows = saved(project)
    rows[1]["Correct"] = "BD"                 # newer pipeline run
    path.write_text(json.dumps(rows), encoding="utf-8")
    grid[1] = row(1, "User edit")             # user edits another row
    ra._sync_step_from_sheets_svc("p", "6", "admin")
    after = saved(project)
    assert after[1]["Correct"] == "BD" and after[0]["Text"] == "User edit 1"


def test_row_added_by_a_newer_run_is_not_treated_as_deleted(project):
    grid = [HEADER, row(1), row(2), row(3), row(4)]
    project.use_grid(grid)
    ra._sync_step_from_sheets_svc("p", "6", "admin")
    path = project.base / "step6_corrections" / "corrected_qcms.json"
    path.write_text(json.dumps(saved(project) + [stored(5)]), encoding="utf-8")
    result = ra._sync_step_from_sheets_svc("p", "6", "admin")
    assert result["deleted_count"] == 0 and len(saved(project)) == 5


def test_no_google_token_asks_to_connect(project, monkeypatch):
    monkeypatch.setattr(ra, "_get_google_creds", lambda uid: None)
    project.use_grid([HEADER, row(1)])
    with pytest.raises(HTTPException) as err:
        ra._sync_step_from_sheets_svc("p", "6", "admin")
    assert err.value.status_code == 401 and err.value.detail == "NOT_AUTHORIZED"


def test_output_newer_than_sheet(monkeypatch):
    monkeypatch.setattr(ra, "_latest_step_result_row",
                        lambda *a: {"created_at": "2026-11-23T10:00:00.12345+00:00"})
    assert ra._output_newer_than_sheet("u", "p", "6", {"pushed_at": "2026-11-23T09:00:00+00:00"})
    assert not ra._output_newer_than_sheet("u", "p", "6", {"opened_at": "2026-11-23T11:00:00"})
    assert not ra._output_newer_than_sheet("u", "p", "6", {})
