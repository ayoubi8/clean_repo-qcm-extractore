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

Deletions: rows whose identity (uid/Num, bridge-resolved) appears in
`deleted_rows` are REMOVED from every chain file — sheet row counts are the
source of truth (see propagate_sheet_edits).
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
      - dict-to-dict merges per key (an empty sheet cell never wipes an
        existing structured value inside the dict)
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
        if isinstance(new_val, dict) and isinstance(target.get(field), dict):
            changed += _merge_dict_kv(target[field], new_val)
            continue
        if str(target.get(field)) != str(new_val):
            target[field] = new_val
            changed += 1
    return changed


def _merge_dict_kv(target_kv: Dict, source_kv: Dict) -> int:
    """Key-level merge for dict-valued fields (propositions): empty/None in
    source never overwrite an existing value; returns changed-key count."""
    changed = 0
    for key, val in source_kv.items():
        if val is None:
            continue
        if isinstance(val, str) and not val.strip():
            continue
        if str(target_kv.get(key)) != str(val):
            target_kv[key] = val
            changed += 1
    return changed


def _merge_rows_into_file(path: Path, edited_rows: List[Dict],
                          uid_by_num: Dict[str, str] = None,
                          translate: bool = False) -> bool:
    """Merge edited rows into one JSON list file, keyed by qcm_key().

    Each file row matches an edited row when their qcm_key() values are
    equal, OR when the file row's uid equals uid_by_num[row_key] (bridge
    for legacy Num-keyed rows). `translate=True` converts sheet field
    names to the raw-record names (Text→text, A..E→propositions) used by
    uid-keyed files (step3 accepted, all_qcms.json).

    Returns True when the file was modified (and should be re-uploaded).
    """
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(current, list):
        return False

    uid_by_num = uid_by_num or {}
    changed = 0
    for row in edited_rows:
        row2 = translate_row_for_raw(row) if translate else row
        key = qcm_key(row2)
        if not key:
            continue
        cands = {key}
        bridged = uid_by_num.get(key)
        if bridged:
            cands.add(bridged)
        matched = False
        for q in current:
            if not isinstance(q, dict):
                continue
            qk = qcm_key(q)
            if qk and qk in cands:
                changed += merge_qcm_fields(q, row2)
                matched = True
                break
        if not matched:
            changed += 0  # row not present in this file — nothing to merge

    if changed <= 0:
        return False
    try:
        path.write_text(json.dumps(current, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    except Exception:
        return False
    return True


# Raw-record field names live in uid-keyed files (all_qcms.json,
# step3_metadata/accepted/*.json); sheet workbooks use Template names.
_RAW_FIELD_MAP = {"Text": "text", "Cas": "cas"}


def translate_row_for_raw(row: Dict) -> Dict:
    """Convert a sheet row (Template-schema, A-E columns) into raw-record
    field names (text/cas/propositions) so edits can merge into uid-keyed
    JSON files. Non-mapped fields pass through unchanged."""
    if not isinstance(row, dict):
        return row
    out: Dict = {}
    props: Dict = {}
    for k, v in row.items():
        if k in _RAW_FIELD_MAP:
            out[_RAW_FIELD_MAP[k]] = v
        elif len(k) == 1 and k in "ABCDE":
            props[k.lower()] = v
        else:
            out[k] = v
    if props:
        out["propositions"] = props
    return out


def build_uid_bridge(output_root: Path) -> Dict[str, str]:
    """Num → uid map from step5_json/merged_qcms.json.

    Step 5 assigns Num sequentially from the same Step-3 files Step 2 reads,
    so the index mapping is exact for the current generation. Lets legacy
    Num-only sheet rows (no uid column) resolve to stable identities.
    """
    root = Path(output_root)
    path = root / "step5_json" / "merged_qcms.json"
    bridge: Dict[str, str] = {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return bridge
    if not isinstance(data, list):
        return bridge
    for q in data:
        if not isinstance(q, dict):
            continue
        num = q.get("Num") or q.get("number")
        uid = q.get("uid")
        if num is not None and uid and str(num) not in bridge:
            bridge[str(num)] = str(uid)
    return bridge


def attach_bridge_uids(rows: List[Dict], uid_by_num: Dict[str, str]) -> None:
    """Stamp a stable uid onto Num-keyed rows when the bridge resolves it.
    Mutates rows in place; used so synced rows carry identity downstream."""
    if not uid_by_num:
        return
    for row in rows:
        if not isinstance(row, dict) or row.get("uid"):
            continue
        k = qcm_key(row)
        if k and k in uid_by_num:
            row["uid"] = uid_by_num[k]


def expand_keys_with_bridge(keys: set, uid_by_num: Dict[str, str]) -> set:
    """Add bridged uids for numeric keys so uid-keyed files can be pruned."""
    out = set(keys)
    for k in list(keys):
        bridged = uid_by_num.get(str(k))
        if bridged:
            out.add(str(bridged))
    return out


def propagate_sheet_edits(output_root: Path, edited_rows: List[Dict],
                          deleted_rows: List[Dict] = None,
                          uid_by_num: Dict[str, str] = None) -> Dict:
    """Propagate sheet edits through the Step 2 → 3 → 5 build chain on disk.

    Call this after the canonical JSON for the edited step has been updated,
    so every file downstream steps consume stays in sync:

      - step5_json/merged_qcms.json            (Step 6 direct input)
      - step2_qcm/accepted/merged_qcms.json    (display mirror in Step 2 UI)
      - step3_metadata/accepted/*.json         (build source — keeps edits
                                                alive across Step 2 re-runs,
                                                which rebuild step5 from it)

    Edits are merged field-level (translate_row_for_raw is applied for the
    uid-keyed step3 files). Rows whose identity appears in `deleted_rows`
    are REMOVED from every chain file (deleted_keys, bridged to uids).

    Only changed files are reported so the caller can upload exactly those
    to Storage.

    Args:
        output_root: project output dir (…/output/{user_id}/{project}/)
        edited_rows: list of QCM dicts parsed from the edited sheet
        deleted_rows: rows REMOVED from the sheet (entries of the old
            canonical) — deleted from all chain files
        uid_by_num: Num→uid bridge (legacy sheets without a uid column)

    Returns:
        {"changed": [relative posix paths rewritten],
         "pruned": [relative posix paths with rows removed],
         "files_scanned": int}
    """
    root = Path(output_root)
    changed: List[str] = []
    pruned_files: List[str] = []
    uid_by_num = uid_by_num or {}
    deleted_rows = deleted_rows or []

    candidates: List[Path] = [
        root / "step5_json" / "merged_qcms.json",
        root / "step2_qcm" / "accepted" / "merged_qcms.json",
    ]
    step3_dir = root / "step3_metadata" / "accepted"
    step3_files: List[Path] = []
    if step3_dir.is_dir():
        step3_files = [
            p for p in sorted(step3_dir.glob("*.json"))
            if not p.name.startswith("merged_")
        ]
        candidates.extend(step3_files)

    # Deletion key-set (bridged to uids so uid-keyed files match too).
    deleted_keys: set = set()
    if deleted_rows:
        deleted_keys = {qcm_key(d) for d in deleted_rows if qcm_key(d)}
        deleted_keys = expand_keys_with_bridge(deleted_keys, uid_by_num)

    for path in candidates:
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        translate = ("step3_metadata/" in rel)
        merged = _merge_rows_into_file(
            path, edited_rows, uid_by_num=uid_by_num, translate=translate)
        if merged:
            changed.append(rel)
        if deleted_keys:
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                current = None
            if isinstance(current, list):
                kept = [q for q in current
                        if not (isinstance(q, dict) and qcm_key(q) in deleted_keys)]
                if len(kept) != len(current):
                    try:
                        path.write_text(
                            json.dumps(kept, indent=2, ensure_ascii=False),
                            encoding="utf-8")
                        pruned_files.append(rel)
                        if rel not in changed:
                            changed.append(rel)
                    except Exception:
                        pass

    return {"changed": changed, "pruned": list(pruned_files),
            "files_scanned": len(candidates)}
