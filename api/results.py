"""Results service (plan frontend-routes-and-switch-lag §11, Phase R).

Pure functions — no FastAPI, no Storage — so they are tested on their own.
The thin HTTP endpoints in real_api.py feed them the step file listings and
file bytes, and return what they build:

- classify / split_step_files: which files are results (what the user wants),
  MBset files, older copies of a workbook, or working files.
- QCM rows: parsed once per file version (LRU keyed by the file's identity),
  counted, normalised, filtered and paged on the server, so the browser never
  downloads a multi-MB JSON to show 20 rows.
- text_chunk / xlsx_table: previews in pages (text in 64 KB chunks, xlsx as
  a table read with openpyxl read-only) — an xlsx is viewable without Google.
"""
from __future__ import annotations

import io
import json
import re
import threading
from collections import OrderedDict
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

# ── Plain-language labels for review flags (§11.3) ──────────────────────────
FLAG_LABELS: Dict[str, str] = {
    "exam_number_suspect": "Exam number looks misread",
    "exam_number_missing": "No exam number found",
    "exam_number_duplicate": "Same exam number used twice in this session",
    "origin_mismatch": "Origin line and detected session disagree",
    "correction_ambiguous": "Answer not applied: two parts share this number",
    "missing_year": "No year found",
}


def flag_label(flag: str) -> str:
    return FLAG_LABELS.get(flag, flag.replace("_", " ").capitalize())


# ── File classification ─────────────────────────────────────────────────────
RESULT_JSON_NAMES = ("merged_qcms.json", "all_qcms.json", "corrected_qcms.json", "final_qcms.json")
# Which result JSON holds a step's QCMs, best first.
STEP_QCM_JSON: Dict[str, Tuple[str, ...]] = {
    "2": ("merged_qcms.json", "all_qcms.json"),
    "6": ("corrected_qcms.json",),
    "7": ("final_qcms.json",),
}
# Newest pipeline stage first: the project's QCMs are read from here.
QCM_STEP_PRIORITY = ("7", "6", "2")

_COUNT_WORKBOOK = re.compile(r"^(\d+)_(qcms|corrections)_(.+)\.xlsx$", re.I)


def basename(path: str) -> str:
    return str(path or "").replace("\\", "/").rsplit("/", 1)[-1]


def classify(name: str) -> str:
    """'internal' | 'mbset_import' | 'mbset_report' | 'workbook' | 'result_json' | 'intermediate'."""
    base = basename(name)
    low = base.lower()
    if not base or base.startswith("_"):
        return "internal"
    if low.startswith("mbset_import_") and low.endswith(".xlsx"):
        return "mbset_import"
    if low.startswith("mbset_report_") and low.endswith(".xlsx"):
        return "mbset_report"
    if low.endswith(".xlsx"):
        return "workbook"
    if low in RESULT_JSON_NAMES:
        return "result_json"
    return "intermediate"


_LABELS = {
    "mbset_import": "MBset import file",
    "mbset_report": "MBset report (rejected / to check)",
    "result_json": "Result data (JSON)",
}


def file_label(name: str, kind: str) -> str:
    if kind in _LABELS:
        return _LABELS[kind]
    m = _COUNT_WORKBOOK.match(basename(name))
    if m:
        return f"{'QCM' if m.group(2).lower() == 'qcms' else 'Corrections'} workbook · {m.group(1)} QCMs"
    if kind == "workbook":
        return "Workbook"
    return basename(name)


def _ts(f: Dict) -> str:
    return str(f.get("created_at") or "")


def split_step_files(files: Iterable[Dict]) -> Dict[str, Any]:
    """Split one step's file listing for the Results page.

    Count-named workbooks (`120_qcms_x.xlsx`, `118_qcms_x.xlsx`…) pile up
    because the name changes with the count (U8): only the newest of each
    (kind, pdf) is a result, the others are listed as `older`.
    """
    results: List[Dict] = []
    older: List[Dict] = []
    intermediate: List[Dict] = []
    newest: Dict[Tuple[str, str], Dict] = {}
    for f in files or []:
        name = str(f.get("name") or "")
        kind = classify(name)
        if kind == "internal":
            continue
        row = {
            "name": name,
            "kind": kind,
            "label": file_label(name, kind),
            "size_bytes": int(f.get("size_bytes") or 0),
            "updated_at": _ts(f),
        }
        if kind == "intermediate":
            intermediate.append(row)
            continue
        m = _COUNT_WORKBOOK.match(basename(name))
        if m:
            key = (m.group(2).lower(), m.group(3).lower())
            cur = newest.get(key)
            # Newest by time, then by the count in the name (Storage listings
            # may have no time).
            if cur is None or (row["updated_at"], int(m.group(1))) > (
                    cur["updated_at"], int(_COUNT_WORKBOOK.match(basename(cur["name"])).group(1))):
                if cur is not None:
                    older.append(cur)
                newest[key] = row
            else:
                older.append(row)
            continue
        results.append(row)
    order = {"mbset_import": 0, "workbook": 1, "mbset_report": 2, "result_json": 3}
    results.extend(newest.values())
    results.sort(key=lambda r: (order.get(r["kind"], 9), r["name"].lower()))
    older.sort(key=lambda r: r["updated_at"], reverse=True)
    return {
        "results": results,
        "older": older,
        "intermediate_count": len(intermediate),
        "intermediate_bytes": sum(r["size_bytes"] for r in intermediate),
        "_intermediate": intermediate,
    }


def find_qcm_json(step_id: str, files: Iterable[Dict]) -> Optional[str]:
    """Name (relative path) of the step's result JSON in its listing, or None."""
    by_base: Dict[str, str] = {}
    for f in files or []:
        name = str(f.get("name") or "")
        by_base.setdefault(basename(name).lower(), name)
    for wanted in STEP_QCM_JSON.get(str(step_id), ()):
        if wanted in by_base:
            return by_base[wanted]
    return None


def page_files(rows: List[Dict], folder: str = "", q: str = "",
               page: int = 1, size: int = 100) -> Dict[str, Any]:
    """Working files, grouped by folder and paged (Step 1's hundreds of pages
    collapse into one group)."""
    groups: Dict[str, int] = {}
    for r in rows:
        top = r["name"].split("/", 1)[0] if "/" in r["name"] else ""
        groups[top] = groups.get(top, 0) + 1
    sel = rows
    if folder:
        sel = [r for r in sel if r["name"].startswith(folder.rstrip("/") + "/")]
    if q:
        ql = q.lower()
        sel = [r for r in sel if ql in r["name"].lower()]
    sel = sorted(sel, key=_natural_key)
    size = max(1, min(int(size or 100), 500))
    page = max(1, int(page or 1))
    start = (page - 1) * size
    return {
        "groups": [{"folder": k, "count": v} for k, v in sorted(groups.items())],
        "total": len(sel),
        "page": page,
        "size": size,
        "files": sel[start:start + size],
    }


def _natural_key(r: Dict) -> List[Any]:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", r["name"])]


# ── QCM rows ────────────────────────────────────────────────────────────────
class _LRU:
    """Parsed result JSON per file version (key includes size/mtime)."""

    def __init__(self, cap: int = 8):
        self.cap = cap
        self.data: "OrderedDict[str, Any]" = OrderedDict()
        self.lock = threading.Lock()

    def get_or_load(self, key: str, loader: Callable[[], Any]) -> Any:
        with self.lock:
            if key in self.data:
                self.data.move_to_end(key)
                return self.data[key]
        value = loader()
        with self.lock:
            self.data[key] = value
            self.data.move_to_end(key)
            while len(self.data) > self.cap:
                self.data.popitem(last=False)
        return value

    def clear(self) -> None:
        with self.lock:
            self.data.clear()


qcm_cache = _LRU()


def parse_qcms(raw: bytes) -> List[Dict]:
    """Result JSON bytes -> list of QCM dicts (accepts {"qcms": [...]})."""
    data = json.loads(raw.decode("utf-8-sig") if isinstance(raw, (bytes, bytearray)) else raw)
    if isinstance(data, dict):
        data = data.get("qcms") or data.get("items") or []
    return [q for q in data if isinstance(q, dict)] if isinstance(data, list) else []


def _s(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        return ", ".join(str(x).strip() for x in v if str(x).strip())
    return str(v).strip()


def _case_text(q: Dict) -> str:
    for k in ("Cas", "cas", "clinical_case", "case_text", "Case"):
        v = q.get(k)
        if isinstance(v, dict):
            v = v.get("text") or v.get("content")
        if _s(v):
            return _s(v)
    return ""


def _flags(q: Dict) -> List[str]:
    f = q.get("review_flags")
    if not f:
        return []
    if isinstance(f, list):
        return [str(x) for x in f if str(x).strip()]
    return [str(f)]


def _number(q: Dict) -> str:
    n = q.get("Number")
    if n in (None, "") and isinstance(q.get("papers"), list) and q["papers"]:
        p0 = q["papers"][0]
        if isinstance(p0, dict):
            n = p0.get("number")
    return _s(n)


def normalise(q: Dict, idx: int) -> Dict[str, Any]:
    """One QCM -> the row shape the Results table shows."""
    options = {k: _s(q.get(k)) for k in ("A", "B", "C", "D", "E", "F") if _s(q.get(k))}
    flags = _flags(q)
    return {
        "row": idx + 1,
        "Num": q.get("Num", q.get("number")),
        "Number": _number(q),
        "page": q.get("page"),
        "Text": _s(q.get("Text") or q.get("text")),
        "options": options,
        "Correct": _s(q.get("Correct") or q.get("correct")),
        "Year": _s(q.get("Year") or q.get("year")),
        "Tag": _s(q.get("Tag") or q.get("tag")),
        "session": _s(q.get("session")),
        "Cas": _case_text(q),
        "category": _s(q.get("categoryName") or q.get("category")),
        "review_flags": flags,
        "flag_labels": [flag_label(f) for f in flags],
        "origin_line": _s(q.get("origin_line")),
    }


def counters(qcms: List[Dict]) -> Dict[str, Any]:
    flags: Dict[str, int] = {}
    sessions: Dict[str, int] = {}
    with_answer = flagged = with_case = 0
    for q in qcms:
        if _s(q.get("Correct") or q.get("correct")):
            with_answer += 1
        fl = _flags(q)
        if fl:
            flagged += 1
            for f in fl:
                flags[f] = flags.get(f, 0) + 1
        if _case_text(q):
            with_case += 1
        s = _s(q.get("session"))
        if s:
            sessions[s] = sessions.get(s, 0) + 1
    return {
        "qcms": len(qcms),
        "with_answer": with_answer,
        "no_answer": len(qcms) - with_answer,
        "flagged": flagged,
        "with_case": with_case,
        "flags": [{"flag": k, "label": flag_label(k), "count": v}
                  for k, v in sorted(flags.items(), key=lambda kv: -kv[1])],
        "sessions": [{"session": k, "count": v} for k, v in sorted(sessions.items())],
    }


def query_rows(qcms: List[Dict], filter: str = "", flag: str = "", session: str = "",
               q: str = "", page: int = 1, size: int = 50) -> Dict[str, Any]:
    """Server-side filter + paging. filter: '' | needs_review | no_answer | has_case."""
    rows = [normalise(x, i) for i, x in enumerate(qcms)]
    if filter == "needs_review":
        rows = [r for r in rows if r["review_flags"]]
    elif filter == "no_answer":
        rows = [r for r in rows if not r["Correct"]]
    elif filter == "has_case":
        rows = [r for r in rows if r["Cas"]]
    if flag:
        rows = [r for r in rows if flag in r["review_flags"]]
    if session:
        rows = [r for r in rows if r["session"] == session]
    if q:
        ql = q.lower().strip()
        rows = [r for r in rows if ql in r["Text"].lower()
                or any(ql in v.lower() for v in r["options"].values())
                or ql == str(r["Num"]).lower() or ql == r["Number"].lower()]
    size = max(1, min(int(size or 50), 200))
    page = max(1, int(page or 1))
    start = (page - 1) * size
    return {"total": len(rows), "page": page, "size": size, "rows": rows[start:start + size]}


# ── Previews ────────────────────────────────────────────────────────────────
TEXT_CHUNK = 64 * 1024


def text_chunk(raw: bytes, offset: int = 0, limit: int = TEXT_CHUNK) -> Dict[str, Any]:
    total = len(raw)
    offset = max(0, min(int(offset or 0), total))
    limit = max(1, min(int(limit or TEXT_CHUNK), 1024 * 1024))
    end = min(total, offset + limit)
    # Never cut a UTF-8 character in half: end the chunk where a character
    # starts (the byte at `end` must not be a continuation byte 10xxxxxx).
    while offset < end < total and (raw[end] & 0xC0) == 0x80:
        end -= 1
    piece = raw[offset:end]
    return {
        "content": piece.decode("utf-8", errors="replace"),
        "offset": offset,
        "next_offset": end if end < total else None,
        "total_bytes": total,
    }


def _cell(v: Any) -> Any:
    if v is None:
        return ""
    if isinstance(v, (int, float, bool)):
        return v
    return str(v)


def xlsx_table(raw: bytes, sheet: str = "", page: int = 1, size: int = 100) -> Dict[str, Any]:
    """First row = header; rows paged. Read-only openpyxl: fast on big files."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    try:
        names = wb.sheetnames
        ws = wb[sheet] if sheet in names else wb[names[0]]
        size = max(1, min(int(size or 100), 500))
        page = max(1, int(page or 1))
        start = (page - 1) * size
        header: List[Any] = []
        rows: List[List[Any]] = []
        total = 0
        for i, r in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                header = [_cell(v) for v in r]
                continue
            if all(v in (None, "") for v in r):
                continue
            if start <= total < start + size:
                rows.append([_cell(v) for v in r])
            total += 1
        # Trim trailing empty header columns.
        while header and header[-1] == "":
            header.pop()
        width = len(header)
        rows = [row[:width] if width else row for row in rows]
        return {"sheets": names, "sheet": ws.title, "header": header,
                "rows": rows, "total_rows": total, "page": page, "size": size}
    finally:
        wb.close()


def xlsx_row_count(raw: bytes, sheet: str) -> Optional[int]:
    """Data rows of one sheet (None if the sheet is missing / unreadable)."""
    try:
        t = xlsx_table(raw, sheet=sheet, page=1, size=1)
        return t["total_rows"] if t["sheet"] == sheet else None
    except Exception:
        return None
