"""Lag plan Phase 3 (project overview) + Phase R (results service).
Plan: docs/plans/frontend-routes-and-switch-lag-plan.md §3.2, §11."""
import io
import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

import results as R  # noqa: E402

QCMS = [
    {"Num": 1, "Number": "7", "Text": "Les signes cliniques", "A": "a", "B": "b", "Correct": "AC",
     "session": "Sec 01 2021", "review_flags": []},
    {"Num": 2, "Text": "Une hypertonie utérine", "A": "x", "Correct": "",
     "session": "Sec 01 Pratique", "review_flags": ["exam_number_suspect", "origin_mismatch"],
     "papers": [{"number": 7}], "Cas": "Patiente de 30 ans"},
    {"Num": 3, "Text": "Troisième", "A": "y", "Correct": "B", "session": "Sec 01 Pratique",
     "review_flags": "correction_ambiguous", "clinical_case": {"text": "Cas 2"}},
]


# ── pure module ─────────────────────────────────────────────────────────────

def test_classify():
    assert R.classify("_sheets_meta.json") == "internal"
    assert R.classify("mbset_import_x.xlsx") == "mbset_import"
    assert R.classify("mbset_report_x.xlsx") == "mbset_report"
    assert R.classify("120_qcms_x.xlsx") == "workbook"
    assert R.classify("accepted/merged_qcms.json") == "result_json"
    assert R.classify("accepted/page_12.json") == "intermediate"
    assert R.classify("pages/page_3.txt") == "intermediate"


def test_split_keeps_newest_count_workbook():
    files = [
        {"name": "118_qcms_x.xlsx", "size_bytes": 10, "created_at": "2026-11-20 10:00"},
        {"name": "120_qcms_x.xlsx", "size_bytes": 11, "created_at": "2026-11-21 10:00"},
        {"name": "119_qcms_x.xlsx", "size_bytes": 12, "created_at": "2026-11-19 10:00"},
        {"name": "mbset_import_x.xlsx", "size_bytes": 5},
        {"name": "accepted/page_1.json", "size_bytes": 3},
        {"name": "accepted/page_2.json", "size_bytes": 4},
        {"name": "_sheets_meta.json", "size_bytes": 1},
    ]
    s = R.split_step_files(files)
    names = [r["name"] for r in s["results"]]
    assert names == ["mbset_import_x.xlsx", "120_qcms_x.xlsx"]
    assert [r["name"] for r in s["older"]] == ["118_qcms_x.xlsx", "119_qcms_x.xlsx"]
    assert s["intermediate_count"] == 2 and s["intermediate_bytes"] == 7
    assert s["results"][1]["label"] == "QCM workbook · 120 QCMs"


def test_split_without_times_uses_count():
    s = R.split_step_files([{"name": "5_corrections_x.xlsx"}, {"name": "9_corrections_x.xlsx"}])
    assert [r["name"] for r in s["results"]] == ["9_corrections_x.xlsx"]


def test_find_qcm_json_prefers_merged():
    files = [{"name": "accepted/all_qcms.json"}, {"name": "accepted/merged_qcms.json"}]
    assert R.find_qcm_json("2", files) == "accepted/merged_qcms.json"
    assert R.find_qcm_json("6", files) is None


def test_counters():
    c = R.counters(QCMS)
    assert (c["qcms"], c["with_answer"], c["no_answer"], c["flagged"], c["with_case"]) == (3, 2, 1, 2, 2)
    assert {f["flag"] for f in c["flags"]} == {"exam_number_suspect", "origin_mismatch", "correction_ambiguous"}
    assert c["sessions"] == [{"session": "Sec 01 2021", "count": 1}, {"session": "Sec 01 Pratique", "count": 2}]


def test_query_rows_filters_and_pages():
    assert R.query_rows(QCMS, filter="needs_review")["total"] == 2
    assert R.query_rows(QCMS, filter="no_answer")["rows"][0]["Num"] == 2
    assert R.query_rows(QCMS, filter="has_case")["total"] == 2
    assert R.query_rows(QCMS, flag="origin_mismatch")["total"] == 1
    assert R.query_rows(QCMS, session="Sec 01 Pratique")["total"] == 2
    assert R.query_rows(QCMS, q="hypertonie")["rows"][0]["Num"] == 2
    p = R.query_rows(QCMS, page=2, size=2)
    assert p["total"] == 3 and [r["Num"] for r in p["rows"]] == [3]
    row = R.query_rows(QCMS, q="hypertonie")["rows"][0]
    assert row["Number"] == "7"                      # from papers[0]
    assert row["flag_labels"][0] == "Exam number looks misread"
    assert row["Cas"] == "Patiente de 30 ans"
    assert R.query_rows(QCMS, q="Troisième")["rows"][0]["Cas"] == "Cas 2"


def test_text_chunk_never_splits_utf8():
    raw = ("é" * 10).encode("utf-8")       # 20 bytes, 2 per char
    c = R.text_chunk(raw, 0, 5)
    assert c["content"] == "éé" and c["next_offset"] == 4
    c2 = R.text_chunk(raw, c["next_offset"], 100)
    assert c2["next_offset"] is None and c2["total_bytes"] == 20
    assert c["content"] + c2["content"] == "é" * 10


def _xlsx(sheets):
    from openpyxl import Workbook
    wb = Workbook()
    first = True
    for title, rows in sheets.items():
        ws = wb.active if first else wb.create_sheet(title)
        ws.title = title
        first = False
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_xlsx_table_pages():
    raw = _xlsx({"Questions": [["Text", "A"]] + [[f"q{i}", i] for i in range(7)], "Other": [["h"], ["v"]]})
    t = R.xlsx_table(raw, page=2, size=3)
    assert t["sheets"] == ["Questions", "Other"] and t["header"] == ["Text", "A"]
    assert t["total_rows"] == 7 and t["rows"] == [["q3", 3], ["q4", 4], ["q5", 5]]
    assert R.xlsx_table(raw, sheet="Other")["rows"] == [["v"]]
    assert R.xlsx_row_count(raw, "Questions") == 7
    assert R.xlsx_row_count(raw, "missing") is None


# ── endpoints ───────────────────────────────────────────────────────────────

@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("QCM_OUTPUT_ROOT", str(tmp_path))
    import importlib
    import real_api
    mod = importlib.reload(real_api)
    R.qcm_cache.clear()

    s6 = tmp_path / "u1" / "p" / "step6_corrections"
    s6.mkdir(parents=True)
    (s6 / "corrected_qcms.json").write_text(json.dumps(QCMS), encoding="utf-8")
    (s6 / "mbset_import_x.xlsx").write_bytes(_xlsx({"Questions": [["Text"], ["a"], ["b"]]}))
    (s6 / "mbset_report_x.xlsx").write_bytes(
        _xlsx({"rejected": [["reason"], ["no answer"]], "review": [["notes"], ["n1"], ["n2"], ["n3"]]}))
    listing = {
        "6": [{"name": n, "size_bytes": 1, "created_at": "2026-11-21 10:00"}
              for n in ("corrected_qcms.json", "mbset_import_x.xlsx", "mbset_report_x.xlsx",
                        "3_corrections_x.xlsx", "correction_map.json")],
    }
    monkeypatch.setattr(mod, "get_step_output_files", lambda name, sid, user: {"files": listing.get(sid, [])})
    monkeypatch.setattr(mod, "get_step_status",
                        lambda name, sid, user: {"status": "done" if sid == "6" else "idle",
                                                 "output_exists": sid == "6"})
    return mod


def _req(headers=None):
    from starlette.requests import Request
    return Request({"type": "http", "method": "GET", "path": "/",
                    "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]})


def test_results_summary_and_etag(api):
    user = {"id": "u1"}
    res = api.get_project_results("p", _req(), user)
    body = json.loads(res.body)
    assert body["summary"]["step"] == "6" and body["summary"]["qcms"] == 3
    assert body["summary"]["flagged"] == 2
    assert body["mbset"] == {"step": "6", "import_file": "mbset_import_x.xlsx",
                             "report_file": "mbset_report_x.xlsx", "rows": 2, "rejected": 1, "to_review": 3}
    s6 = body["steps"]["6"]
    assert s6["status"] == "done" and s6["intermediate_count"] == 1
    assert {r["kind"] for r in s6["results"]} == {"mbset_import", "mbset_report", "workbook", "result_json"}
    etag = res.headers["etag"]
    again = api.get_project_results("p", _req({"If-None-Match": etag}), user)
    assert again.status_code == 304


def test_result_qcms_endpoint(api):
    out = api.get_result_qcms("p", filter="needs_review", user={"id": "u1"})
    assert out["step"] == "6" and out["total"] == 2
    empty = api.get_result_qcms("p", step="2", user={"id": "u1"})
    assert empty["total"] == 0 and empty["file"] is None


def test_preview_table_and_traversal(api):
    user = {"id": "u1"}
    prev = api.get_result_preview("p", "6", "corrected_qcms.json", 0, 10, user)
    assert prev["total_bytes"] > 10 and prev["next_offset"] == 10
    tab = api.get_result_table("p", "6", "mbset_import_x.xlsx", "", 1, 100, user)
    assert tab["rows"] == [["a"], ["b"]]
    for call in (lambda: api.get_result_preview("p", "6", "../../u2/p/x.json", 0, 10, user),
                 lambda: api.get_result_table("p", "6", "../../u2/p/x.xlsx", "", 1, 10, user)):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        api.get_result_preview("p", "6", "mbset_import_x.xlsx", 0, 10, user)
    assert e.value.status_code == 415
    with pytest.raises(HTTPException) as e:
        api.get_result_files("p", "99", user=user)
    assert e.value.status_code == 404


def test_result_files_paged(api):
    out = api.get_result_files("p", "6", user={"id": "u1"})
    # working file + the older count workbook? (only one count workbook → it is the result)
    assert out["total"] == 1 and out["files"][0]["name"] == "correction_map.json"


def test_overview_one_call(api, monkeypatch):
    monkeypatch.setattr(api, "list_projects", lambda uid: [{"name": "p", "pdf_path": "x.pdf"}])

    def status(name, sid, user):
        if sid == "7":
            raise RuntimeError("storage down")
        return {"status": "done" if sid == "6" else "idle", "output_exists": sid == "6"}
    monkeypatch.setattr(api, "get_step_status", status)
    o = api.get_project_overview("p", {"id": "u1"})
    assert o["project"]["pdf_path"] == "x.pdf"
    assert set(o["steps"]) == {"1", "2", "6", "7", "8"}
    assert o["steps"]["6"]["status"] == "done"
    assert o["steps"]["7"]["status"] == "idle"        # one failing probe doesn't break the call

