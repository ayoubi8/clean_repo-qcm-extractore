"""MBset import workbook (plan §6 "XLSX exports" item 2, §8, decisions D1-D7).

Two files next to each result workbook:

- `mbset_import_<pdf>.xlsx` — ONE sheet `Questions`, exactly the columns of
  MBset's `mbset-question-import-template.xlsx`, in that order. Built for the
  import wizard (new questions, no `id`):
    Number = ORIGINAL paper number, Year = start year,
    Tag    = source, year, session label ("Sec 01 Pratique"),
    Cas    = case text, identical on every question of the case,
    Exams  = EMPTY (a filled Exams would override Number/Year — decision O2),
    one row per paper occurrence, no duplicate merging (MBset dedupes).
- `mbset_report_<pdf>.xlsx` — what the import file does NOT contain or should
  be checked: sheet `rejected` (row + reason, not exported) and sheet
  `review` (exported rows carrying review flags). Kept out of the import file
  so the wizard never sees extra sheets or columns.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from modules.utils.exam_papers import extract_int, parse_year

# Column order of mbset-question-import-template.xlsx (sheet "Questions").
MBSET_COLUMNS: List[str] = [
    "Text", "A", "B", "Correct", "C", "D", "E", "F", "Year", "Number", "Exams",
    "Official", "Proposed", "EXP", "Note", "A_EXP", "B_EXP", "C_EXP", "D_EXP",
    "categoryId", "subcategoryId", "categoryName", "subcategoryName", "tagSuggere",
    "Tag", "Hint", "Type", "Cas", "ModelAnswer", "Image", "ImagePage",
    "explanationImage", "ImageMasks", "ExplanationImageMasks", "SourceFile",
]

# Tags MBset deletes or that would mislabel a paper (SKILL.md §6.4).
_BAD_TAG = re.compile(r"(?i)(\bn\s*[°º]|\bno\.\s*\d|\bn\d{1,3}\b|corrig)")


def mbset_file_names(pdf_stem: str) -> Tuple[str, str]:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", pdf_stem or "source").strip("._") or "source"
    return f"mbset_import_{stem}.xlsx", f"mbset_report_{stem}.xlsx"


def _text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        out: List[str] = []
        for x in v:
            s = str(x).strip()
            if s and s not in out:
                out.append(s)
        return ", ".join(out)
    return str(v).strip()


def _tag_list(v: Any) -> List[str]:
    if v is None or v == "":
        return []
    if isinstance(v, list):
        items = v
    else:
        s = str(v).strip()
        if s.startswith("[") and s.endswith("]"):
            try:
                import ast
                parsed = ast.literal_eval(s)
                items = parsed if isinstance(parsed, list) else [s]
            except (ValueError, SyntaxError):
                items = s.strip("[]").split(",")
        else:
            items = s.split(",")
    out: List[str] = []
    for x in items:
        t = str(x).strip().strip("'\"").strip()
        if t and t not in out:
            out.append(t)
    return out


def _option(q: Dict, letter: str) -> str:
    if q.get(letter) not in (None, ""):
        return _text(q.get(letter))
    props = q.get("propositions") or {}
    if isinstance(props, dict):
        for k in (letter, letter.lower()):
            if props.get(k) not in (None, ""):
                return _text(props[k])
    return ""


def _correct(v: Any) -> str:
    letters = "".join(re.findall(r"[A-H]", str(v or "").upper()))
    return "".join(dict.fromkeys(letters))


def build_row(q: Dict) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """One MBset row for one QCM.

    Returns (row, reasons_to_reject, review_notes)."""
    reasons: List[str] = []
    notes: List[str] = []

    text = _text(q.get("Text") if q.get("Text") not in (None, "") else q.get("text"))
    if not text:
        reasons.append("empty question text")

    year = parse_year(q.get("Year") if q.get("Year") not in (None, "") else q.get("year"))
    if year is None:
        reasons.append("no valid 4-digit year (a question with no year is invisible "
                       "to the exam filters)")

    number = extract_int(q.get("Number"))
    if number is None:
        papers = q.get("papers") or []
        if papers and isinstance(papers[0], dict):
            number = extract_int(papers[0].get("number"))
    if number is None:
        reasons.append("no original question number (Number)")
    elif number <= 0:
        reasons.append(f"invalid question number {number}")
        number = None

    tags = _tag_list(q.get("Tag") if q.get("Tag") not in (None, "", []) else q.get("tag"))
    bad = [t for t in tags if _BAD_TAG.search(t)]
    if bad:
        tags = [t for t in tags if t not in bad]
        notes.append(f"removed number/corrigé tag(s) {bad} (MBset deletes them)")

    flags = q.get("review_flags") or []
    if isinstance(flags, str):
        flags = [f.strip() for f in flags.split(",") if f.strip()]
    notes.extend(str(f) for f in flags)

    row: Dict[str, Any] = {c: "" for c in MBSET_COLUMNS}
    row.update({
        "Text": text,
        "A": _option(q, "A"), "B": _option(q, "B"), "C": _option(q, "C"),
        "D": _option(q, "D"), "E": _option(q, "E"), "F": _option(q, "F"),
        "Correct": _correct(q.get("Correct")),
        "Year": year if year is not None else "",
        "Number": number if number is not None else "",
        "Exams": "",                                     # decision O2
        "EXP": _text(q.get("EXP") if q.get("EXP") not in (None, "") else q.get("Exp")),
        "Note": _text(q.get("Note")),
        "categoryName": _text(q.get("categoryName")),
        "subcategoryName": _text(q.get("subcategoryName")),
        "tagSuggere": _text(q.get("tagSuggere")),
        "Tag": ", ".join(tags),
        "Hint": _text(q.get("Hint") if q.get("Hint") not in (None, "", []) else q.get("hint")),
        "Type": _text(q.get("Type")),
        "Cas": q.get("Cas") if q.get("Cas") not in (None, "") else (q.get("cas") or ""),
    })
    for letter in "ABCD":
        row[f"{letter}_EXP"] = _text(q.get(f"{letter}_EXP"))
    for col in ("Official", "Proposed", "ModelAnswer", "Image", "explanationImage", "SourceFile"):
        if q.get(col) not in (None, ""):
            row[col] = _text(q.get(col))
    if not any(row[x] for x in "ABCDEF") and row["Type"] != "QROC":
        notes.append("no options")
    return row, reasons, notes


def build_workbook_rows(qcms: List[Dict]) -> Dict[str, List]:
    """Apply §8 checks to every QCM. Pure function (no file I/O)."""
    exported: List[Dict] = []
    rejected: List[Dict] = []
    review: List[Dict] = []
    seen_uid: set = set()
    seen_paper: Dict[Tuple, int] = {}
    cas_rows: Dict[str, List[int]] = {}

    for i, q in enumerate(qcms or []):
        if not isinstance(q, dict):
            continue
        row, reasons, notes = build_row(q)
        uid = str(q.get("uid") or "")
        if uid and uid in seen_uid:
            reasons.append(f"duplicate row for the same question (uid {uid})")
        if uid:
            seen_uid.add(uid)
        ref = {"source_row": i + 1, "Num": q.get("Num") if q.get("Num") is not None else q.get("number"),
               "Number": row["Number"], "Year": row["Year"], "Tag": row["Tag"],
               "Text": (row["Text"] or "")[:120], "origin_line": q.get("origin_line") or ""}
        if reasons:
            rejected.append(dict(ref, reason="; ".join(reasons)))
            continue
        exported.append(row)
        pos = len(exported)                      # 1-based data row in the import sheet
        key = (row["Tag"], row["Year"], row["Number"])
        if key in seen_paper:
            notes.append(f"same Tag/Year/Number as import row {seen_paper[key]} "
                         "(two different questions, or one question printed twice)")
        else:
            seen_paper[key] = pos
        if row["Cas"]:
            cas_rows.setdefault(row["Cas"], []).append(pos)
        if notes:
            review.append(dict(ref, import_row=pos, notes="; ".join(dict.fromkeys(notes))))

    # §11.2 — one case's rows must be one unbroken run in the import file.
    for cas, positions in cas_rows.items():
        if positions != list(range(positions[0], positions[0] + len(positions))):
            review.append({"import_row": positions[0], "Text": cas[:120],
                           "notes": f"case text used on non-consecutive import rows {positions}"})
    return {"exported": exported, "rejected": rejected, "review": review}


def _write_sheet(ws, columns: List[str], rows: List[Dict]) -> None:
    from openpyxl.styles import Font
    ws.append(columns)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append([r.get(c, "") for c in columns])
    ws.freeze_panes = "A2"


def export_mbset_import(qcms: List[Dict], output_dir: Path, pdf_stem: str) -> Optional[Dict]:
    """Write the import workbook + the report workbook. Never raises."""
    try:
        from openpyxl import Workbook
    except ImportError:
        print("⚠️  openpyxl not installed — MBset import file skipped.")
        return None
    try:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        import_name, report_name = mbset_file_names(pdf_stem)
        res = build_workbook_rows(qcms)

        wb = Workbook()
        ws = wb.active
        ws.title = "Questions"
        _write_sheet(ws, MBSET_COLUMNS, res["exported"])
        import_path = output_dir / import_name
        wb.save(import_path)

        rep = Workbook()
        ws_r = rep.active
        ws_r.title = "rejected"
        _write_sheet(ws_r, ["source_row", "Num", "Number", "Year", "Tag", "Text",
                            "origin_line", "reason"], res["rejected"])
        ws_v = rep.create_sheet("review")
        _write_sheet(ws_v, ["import_row", "source_row", "Num", "Number", "Year", "Tag",
                            "Text", "origin_line", "notes"], res["review"])
        report_path = output_dir / report_name
        rep.save(report_path)

        print(f"[MBSET] {len(res['exported'])} row(s) → {import_name} · "
              f"{len(res['rejected'])} rejected, {len(res['review'])} to review → {report_name}")
        return {"import_file": str(import_path), "report_file": str(report_path),
                "exported": len(res["exported"]), "rejected": len(res["rejected"]),
                "review": len(res["review"])}
    except Exception as e:
        print(f"[WARN] MBset import file not written: {e}")
        return None
