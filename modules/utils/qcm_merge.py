"""Sheet-edit propagation helpers.

When the user edits a step's result xlsx in Google Sheets and syncs it back
(`sync-from-sheets`), the canonical JSON for that step is overwritten. But
downstream artifacts were built from an earlier version of that JSON:

    step2 all_qcms.json ──► step3 accepted/*.json ──► step5 merged_qcms.json ──► Step 6
                                    (enrich)             (template build)

Step 6 reads `step5_json/merged_qcms.json`, NOT `all_qcms.json`. Without
propagation, manual sheet edits never reach the file Step 6 consumes and the
user would have to redo them.

This module provides:
  - qcm_key():           stable identity for a QCM dict (uid / Num / number)
  - merge_qcm_fields():  field-level, sheet-safe merge of one QCM into another
  - propagate_sheet_edits(): merge edited rows into the whole build chain
    (step5 merged + step2 accepted mirror + step3 accepted files) on disk.

All merges are non-destructive: only non-empty values are applied, structured
values (list/dict) in the target are protected against string flattening from
the sheet round-trip (a list exported as "['a', 'b']" is parsed back via
ast.literal_eval; anything unparseable is skipped, never written).
"""
import ast
import json
from pathlib import Path
from typing import Any, Dict, List


def qcm_key(q: Dict) -> str:
    """Stable identity for a QCM across pipeline stages.

    Step 2 raw qcms carry `uid`; template-built stages (step 5/6/7) carry
    `Num`; step 3 metadata carries `number`. Sheets round-trip all of them
    as strings, so the key is always str().
    """
    if not isinstance(q, dict):
        return ""
    return str(q.get("uid") or q.get("Num") or q.get("number") or "")


def _coerce_sheet_value(existing: Any, incoming: Any) -> Any:
    """Make an incoming sheet value compatible with the existing field type.

    The xlsx round-trip flattens lists (Tag -> "['Externat', '2024']") and
    would otherwise replace structured JSON values with plain strings.
    """
    if isinstance(existing, (list, dict)) and isinstance(incoming, str):
        text = incoming.strip()
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            return None  # unparseable — caller skips, structured value survives
        if isinstance(parsed, type(existing)):
            return parsed
        return None
    return incoming


def merge_qcm_fields(target: Dict, source: Dict) -> int:
    """Field-level merge of `source` (edited sheet row / prior output) into
    `target` (current pipeline QCM dict). Mutates target in place.

    Rules:
      - empty strings / None in source never overwrite
      - values are type-coerced against the existing target value
        (list/dict targets are protected, see _coerce_sheet_value)
      - a field counts as changed only when its canonical str() differs

    Returns the number of fields actually changed on target.
    """
    if not isinstance(target, dict) or not isinstance(source, dict):
        return 0
    changed = 0
    for field, val in source.items():
        if val is None:
            continue
        if isinstance(val, str) and not val.strip():
            continue
        new_val = _coerce_sheet_value(target.get(field), val)
        if new_val is None and isinstance(target.get(field), (list, dict)):
            continue  # could not parse back — keep the structured value
        if str(target.get(field)) != str(new_val):
            target[field] = new_val
            changed += 1
    return changed


def _merge_rows_into_file(path: Path, edited_rows: List[Dict]) -> bool:
    """Merge edited rows into one JSON list file, keyed by qcm_key().

    Returns True when the file was modified (and should be re-uploaded).
    """
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(current, list):
        return False

    current_map: Dict[str, Dict] = {}
    for q in current:
        key = qcm_key(q)
        if key:
            current_map[key] = q

    changed = 0
    for row in edited_rows:
        key = qcm_key(row)
        target = current_map.get(key)
        if target is not None:
            changed += merge_qcm_fields(target, row)

    if changed <= 0:
        return False
    try:
        path.write_text(json.dumps(current, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    except Exception:
        return False
    return True


def propagate_sheet_edits(output_root: Path, edited_rows: List[Dict]) -> Dict:
    """Propagate sheet edits through the Step 2 → 3 → 5 build chain on disk.

    Call this after the canonical JSON for the edited step has been updated,
    so every file downstream steps consume stays in sync:

      - step5_json/merged_qcms.json            (Step 6 direct input)
      - step2_qcm/accepted/merged_qcms.json    (display mirror in Step 2 UI)
      - step3_metadata/accepted/*.json         (build source — keeps edits
                                                alive across Step 2 re-runs,
                                                which rebuild step5 from it)

    Only files that actually change are reported so the caller can upload
    exactly those to Storage.

    Args:
        output_root: project output dir (…/output/{user_id}/{project}/)
        edited_rows: list of QCM dicts parsed from the edited sheet

    Returns:
        {"changed": [relative posix paths that were rewritten],
         "files_scanned": int}
    """
    root = Path(output_root)
    changed: List[str] = []

    candidates: List[Path] = [
        root / "step5_json" / "merged_qcms.json",
        root / "step2_qcm" / "accepted" / "merged_qcms.json",
    ]
    step3_dir = root / "step3_metadata" / "accepted"
    if step3_dir.is_dir():
        candidates.extend(
            p for p in sorted(step3_dir.glob("*.json"))
            if not p.name.startswith("merged_")
        )

    for path in candidates:
        if not path.is_file():
            continue
        if _merge_rows_into_file(path, edited_rows):
            changed.append(path.relative_to(root).as_posix())

    return {"changed": changed, "files_scanned": len(candidates)}
