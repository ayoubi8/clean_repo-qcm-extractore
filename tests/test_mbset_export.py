"""Phase 5 — MBset import workbook, §8 validation, Sheets round-trip, Step 8 union.
Plan: docs/plans/exam-papers-sections-numbering-plan.md (§6 XLSX exports, §8, §11)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from openpyxl import load_workbook  # noqa: E402

from modules.utils import exam_papers as ep  # noqa: E402
from modules.utils.mbset_export import (  # noqa: E402
    MBSET_COLUMNS, build_workbook_rows, export_mbset_import, mbset_file_names)
from modules.utils.qcm_merge import merge_qcm_fields  # noqa: E402

TEMPLATE = ROOT / "mbset-smart-import-skill" / "mbset-smart-import" / "mbset-question-import-template.xlsx"


def _row(num, number, year, tag, cas=None, **kw):
    d = {"Num": num, "Number": number, "Text": f"Question {num}", "A": "a", "B": "b",
         "C": "c", "D": "d", "E": "e", "Correct": "AC", "Year": year, "Tag": tag,
         "Cas": cas, "uid": f"1_{num}_{num}", "categoryName": "Gynécologie",
         "Exams": "Residanat Blida · Rattrapage 2023 · N°22",
         "papers": [{"number": number}], "review_flags": []}
    d.update(kw)
    return d


def test_columns_match_the_official_template():
    if TEMPLATE.exists():
        header = [c.value for c in load_workbook(TEMPLATE)["Questions"][1]]
        assert header == MBSET_COLUMNS
    assert "Period" not in MBSET_COLUMNS


def test_import_file_user_decisions(tmp_path):
    case = "CAS CLINIQUE\r\nMme X, 32 ans"
    tag = ["Residanat Blida", "2023", "Rattrapage"]
    qcms = [_row(41, 22, "2023", tag, case), _row(42, 23, "2023", tag, case),
            _row(43, 24, "2023", tag, case), _row(44, 25, "2023", tag, case),
            _row(45, 42, "2024", ["Residanat Blida", "2024", "Sec 02"]),
            _row(46, 2, "2017", ["Residanat Blida", "2017", "Sec 01 Pratique"]),
            _row(47, 2, "2017", ["Residanat Blida", "2017", "Sec 01"])]
    out = export_mbset_import(qcms, tmp_path, "gyneco QCM classé 2025")
    assert out["exported"] == 7 and out["rejected"] == 0
    imp, rep = mbset_file_names("gyneco QCM classé 2025")
    assert Path(out["import_file"]).name == imp == "mbset_import_gyneco_QCM_class_2025.xlsx"
    wb = load_workbook(tmp_path / imp)
    assert wb.sheetnames == ["Questions"]                   # nothing else for the wizard
    ws = wb["Questions"]
    header = [c.value for c in ws[1]]
    assert header == MBSET_COLUMNS
    rows = [dict(zip(header, [c.value for c in r])) for r in ws.iter_rows(min_row=2)]
    assert [r["Number"] for r in rows] == [22, 23, 24, 25, 42, 2, 2]
    assert [r["Year"] for r in rows] == [2023] * 4 + [2024, 2017, 2017]
    assert rows[0]["Tag"] == "Residanat Blida, 2023, Rattrapage"
    assert rows[5]["Tag"] == "Residanat Blida, 2017, Sec 01 Pratique"
    assert all(r["Exams"] in (None, "") for r in rows)       # decision O2
    assert {r["Cas"] for r in rows[:4]} == {case} and rows[4]["Cas"] in (None, "")
    assert rows[0]["Correct"] == "AC" and rows[0]["categoryName"] == "Gynécologie"
    assert (tmp_path / rep).exists()


def test_rejected_and_review_rows():
    qcms = [
        _row(1, None, "2023", ["X"], papers=[]),                       # no Number
        _row(2, 5, None, ["X"]),                                       # no Year
        _row(3, 6, "2022", ["Externat Oran", "N° 12", "Corrigé type", "2022"]),
        _row(4, 7, "2022", ["X"], review_flags=["exam_number_suspect"]),
        _row(4, 7, "2022", ["X"]),                                     # same uid twice
        _row(5, 8, "2022", ["X"], Text=""),                            # empty text
    ]
    res = build_workbook_rows(qcms)
    assert len(res["exported"]) == 2
    reasons = " | ".join(r["reason"] for r in res["rejected"])
    for part in ("Number", "year", "duplicate row", "empty question text"):
        assert part in reasons
    tagged = res["exported"][0]
    assert tagged["Tag"] == "Externat Oran, 2022"                     # number/corrigé tags removed
    notes = " | ".join(r["notes"] for r in res["review"])
    assert "removed number/corrigé tag" in notes and "exam_number_suspect" in notes


def test_review_flags_case_rows_not_consecutive():
    case = "CAS\r\nM. Y"
    qcms = [_row(1, 1, "2021", ["S"], case), _row(2, 9, "2021", ["S"]), _row(3, 2, "2021", ["S"], case)]
    res = build_workbook_rows(qcms)
    assert any("non-consecutive" in r["notes"] for r in res["review"])


def test_normal_exam_row():
    q = {"Num": 12, "Number": 12, "Text": "T", "propositions": {"a": "x", "b": "y"},
         "Correct": "B", "Year": "2024", "Tag": "['Externat Alger', '2024', 'EMD1']", "uid": "u"}
    res = build_workbook_rows([q])
    r = res["exported"][0]
    assert (r["Number"], r["Year"], r["Tag"], r["A"], r["B"]) == (12, 2024, "Externat Alger, 2024, EMD1", "x", "y")


# ── Sheets round-trip ─────────────────────────────────────────────────────

def test_parse_exams_inverse_of_format_exams():
    papers = [{"source": "Residanat Blida", "period": "Sec 01", "year": 2017, "number": 2,
               "section": "Pratique"},
              {"source": None, "period": "Rattrapage", "year": 2021, "number": None, "section": None}]
    cell = ep.format_exams(papers)
    assert cell == "Residanat Blida · Sec 01 Pratique 2017 · N°2 | Rattrapage 2021"
    back = ep.parse_exams(cell)
    assert [(p["source"], p["period"], p["section"], p["year"], p["number"]) for p in back] == \
        [("Residanat Blida", "Sec 01", "Pratique", 2017, 2), (None, "Rattrapage", None, 2021, None)]
    assert ep.parse_exams("Externat Setif · 2024 · N°28")[0]["number"] == 28
    assert ep.parse_exams("no year here · N°3") == []


def test_sheet_edit_of_exams_rebuilds_papers():
    target = {"Num": 4, "Number": 7, "Exams": "Residanat Blida · Sec 01 2021 · N°7",
              "papers": [{"source": "Residanat Blida", "period": "Sec 01", "year": 2021, "number": 7}]}
    merge_qcm_fields(target, {"Num": "4", "Exams": "Residanat Blida · Sec 02 Pratique 2021 · N°8"})
    assert target["Number"] == 8 and target["session"] == "Sec 02 Pratique"
    assert target["papers"][0]["period"] == "Sec 02" and target["papers"][0]["section"] == "Pratique"


def test_sheet_edit_of_number_only():
    target = {"Num": 4, "Number": 7, "Exams": "Residanat Blida · Sec 01 2021 · N°7",
              "papers": [{"source": "Residanat Blida", "period": "Sec 01", "year": 2021,
                          "number": 7, "section": None}]}
    merge_qcm_fields(target, {"Num": "4", "Number": "9", "Exams": "Residanat Blida · Sec 01 2021 · N°7"})
    assert target["Number"] == 9 and target["papers"][0]["number"] == 9
    assert target["Exams"] == "Residanat Blida · Sec 01 2021 · N°9"
    # untouched cells change nothing
    before = dict(target)
    merge_qcm_fields(target, {"Num": "4", "Number": "9"})
    assert target == before


# ── Step 8 paper union ────────────────────────────────────────────────────

def test_union_papers_keeps_every_paper():
    ref = ep.parse_exams("Residanat Blida · Rattrapage Pratique 2021 · N°2")
    src = [{"source": None, "period": "Sec 01", "section": "Pratique", "year": 2021, "number": 7},
           {"source": None, "period": "Rattrapage", "section": "Pratique", "year": 2021, "number": 3}]
    merged, conflicts = ep.union_papers(ref, src)
    assert ep.format_exams(merged) == ("Residanat Blida · Rattrapage Pratique 2021 · N°2 | "
                                       "Sec 01 Pratique 2021 · N°7")
    assert conflicts and "N°3" in conflicts[0]
