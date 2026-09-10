"""Cas column split — Phase 4: clinical-case text stays in its own column.

Step 2's extraction does not exclude the patient narrative from the question
text, so a QCM's `text` commonly contains the case narrative *plus* the
question — duplicating what Step 3 attaches as `cas` ("LABEL\\r\\nNarrative").
The XLSX must carry the clinical case in its own Cas column only; it must
never be merged/concatenated into the question-text column.

This module deterministically removes the narrative span from the question
`text`/`Text` field, leaving `cas`/`Cas` untouched.

Matching (safe, in order):
  1. Exact substring removal of the narrative from the text.
  2. Whitespace-normalized fallback: collapse all whitespace runs in both
     strings, locate the narrative span, map the span back to original
     indices — formatting outside the span is preserved byte-for-byte.
If the narrative is not found, is too short to match safely, or removal
would leave the text empty, the text is kept untouched (never mangle a
question on an uncertain match).

After narrative removal, a surviving standalone label line (the cas label,
e.g. "CAS CLINIQUE 1") is dropped too — the label already lives in `cas`.

Placement: runs in the Step 2 auto-enrich cascade after hint detection and
before Step 3 — unconditional (keyed on data presence: QCMs without `cas`
are skipped), idempotent, soft-fail. Pure Python: no LLM, no cost.
"""
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Narratives shorter than this are never scrubbed: a tiny string could
# false-positive match inside an unrelated longer question.
MIN_NARRATIVE_LEN = 20


def _split_cas(cas: str) -> Tuple[str, str]:
    if "\r\n" in cas:
        label, narrative = cas.split("\r\n", 1)
        return (label or "CAS CLINIQUE"), narrative
    if "\n" in cas:
        label, narrative = cas.split("\n", 1)
        return (label or "CAS CLINIQUE"), narrative
    return "CAS CLINIQUE", cas


def _collapse_ws(s: str) -> Tuple[str, List[int]]:
    """Collapse every whitespace run to one space. Returns
    (collapsed_string, index_map) where index_map[i] is the original index
    of collapsed[i]. Leading/trailing whitespace is dropped (the map only
    covers kept characters)."""
    collapsed: List[str] = []
    index_map: List[int] = []
    in_ws = True  # skip leading whitespace
    for i, ch in enumerate(s):
        if ch.isspace():
            in_ws = True
            continue
        if in_ws and collapsed:
            collapsed.append(" ")
            index_map.append(i)  # space maps to the current (post-ws) char
        collapsed.append(ch)
        index_map.append(i)
        in_ws = False
    return "".join(collapsed), index_map


def _remove_span(text: str, start: int, end: int) -> str:
    return (text[:start] + text[end:]).strip()


def _norm_line(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower().rstrip(":").strip()


def split_cas_from_text(text: Any, cas: Any) -> Tuple[Any, bool]:
    """Remove the cas narrative from question text. Returns
    (new_text, removed_flag). Non-string inputs pass through untouched."""
    if not isinstance(text, str) or not isinstance(cas, str):
        return text, False
    label, narrative = _split_cas(cas)
    narrative = narrative.strip()
    if len(narrative) < MIN_NARRATIVE_LEN or not text.strip():
        return text, False

    new_text: Optional[str] = None

    # Attempt 1 — exact substring (covers verbatim copies).
    if narrative in text:
        new_text = _remove_span(text, text.index(narrative),
                                text.index(narrative) + len(narrative))
    else:
        # Attempt 2 — whitespace-normalized match mapped back to originals.
        collapsed_text, text_map = _collapse_ws(text)
        collapsed_narr, _ = _collapse_ws(narrative)
        pos = collapsed_text.find(collapsed_narr)
        if pos != -1:
            orig_start = text_map[pos]
            orig_end = text_map[pos + len(collapsed_narr) - 1] + 1
            new_text = _remove_span(text, orig_start, orig_end)

    if new_text is None or not new_text.strip():
        return text, False

    # Drop a surviving standalone label line — the label lives in `cas`.
    # (Blank lines never match a non-blank label, so they are always kept.)
    label_norm = _norm_line(label)
    lines = new_text.split("\n")
    kept = [ln for ln in lines if _norm_line(ln) != label_norm]
    new_text = "\n".join(kept).strip()
    if not new_text:
        return text, False
    return new_text, new_text != text


def _load_step2_qcms(step2_accepted: Path) -> Tuple[List[Tuple[Path, Dict]], Dict[Path, List[Dict]]]:
    """Load every Step 2 accepted QCM file in document order (files sorted
    by name, in-file order preserved). ``merged_*`` files are skipped."""
    entries: List[Tuple[Path, Dict]] = []
    file_data: Dict[Path, List[Dict]] = {}
    for q_file in sorted(step2_accepted.glob("*.json")):
        if q_file.name.startswith("merged_"):
            continue
        try:
            with open(q_file, "r", encoding="utf-8") as f:
                qcms = json.load(f)
        except Exception as e:
            print(f"[CAS-SPLIT] ⚠️ Could not read {q_file.name}: {e}")
            continue
        if not isinstance(qcms, list):
            continue
        file_data[q_file] = qcms
        for i, qcm in enumerate(qcms):
            qcm.setdefault("uid", f"noidx_{q_file.stem}_{i}")
            entries.append((q_file, qcm))
    return entries, file_data


def run_cas_text_split(context) -> Dict:
    """Strip clinical-case narratives out of question text (cas stays intact).

    Must run after Step 2 wrote step2_qcm/accepted/*.json and before Step 3.
    Returns:
        {"status": "ok",      "stats": {...}}
        {"status": "no_qcms"}  # nothing to scan
    """
    print("\n" + "═" * 60)
    print("CAS COLUMN SPLIT  (Phase 4 — case text out of question text)")
    print("═" * 60)

    try:
        step2_accepted = Path(context.get_path("step2_qcm", "accepted"))
    except Exception as e:
        return {"status": "error", "detail": f"project context error: {e}"}

    if not step2_accepted.exists():
        print("[CAS-SPLIT] No step2_qcm/accepted folder — nothing to scan.")
        return {"status": "no_qcms"}

    entries, file_data = _load_step2_qcms(step2_accepted)
    if not entries:
        print("[CAS-SPLIT] No accepted Step 2 QCM JSON found — nothing to scan.")
        return {"status": "no_qcms"}

    stats = {"qcms_scanned": 0, "qcms_with_cas": 0, "qcms_scrubbed": 0}
    touched_files = set()

    for q_file, qcm in entries:
        stats["qcms_scanned"] += 1
        cas = qcm.get("cas")
        if not cas:
            continue
        stats["qcms_with_cas"] += 1

        for key in ("text", "Text"):
            if key in qcm and isinstance(qcm[key], str):
                new_text, removed = split_cas_from_text(qcm[key], cas)
                if removed:
                    qcm[key] = new_text
                    stats["qcms_scrubbed"] += 1
                    touched_files.add(q_file)
                    print(f"[CAS-SPLIT] Q{qcm.get('number', '?')} p.{qcm.get('page', '?')} — "
                          f"narrative removed from '{key}' ({len(qcm[key])} chars kept)")
                break

    for q_file in touched_files:
        with open(q_file, "w", encoding="utf-8") as f:
            json.dump(file_data[q_file], f, indent=2, ensure_ascii=False)
    if touched_files:
        print(f"[CAS-SPLIT] 💾 Split text written → "
              f"{', '.join(sorted(p.name for p in touched_files))}")

    print("\n" + "═" * 60)
    print("📊 CAS SPLIT SUMMARY")
    print("═" * 60)
    print(f"  QCMs scanned:       {stats['qcms_scanned']}")
    print(f"  QCMs carrying cas:  {stats['qcms_with_cas']}")
    print(f"  Texts scrubbed:     {stats['qcms_scrubbed']}")
    print("═" * 60)

    return {"status": "ok", "stats": stats}
