"""Hint detection — Phase 3: always-on backend-only deterministic parser.

A hint block is a run of trailing lines at the very end of a QCM, right after
the last proposition (proposition E), shaped like::

    A(1+2+3)
    B(1+3+4)
    C(2+3+4)
    D(3+4+5)
    E(2+4+5)

Parsing rule (the whole algorithm — nothing fancier): inside each line, map
the numbers to proposition letters with 1=A, 2=B, 3=C, 4=D, 5=E, then join
the mapped letters into one combo string per line, in line order. Combos are
normalized (sorted + deduped), so ``B(2+1)`` -> ``"AB"``. For the example
above the output is exactly ``["ABC", "ACD", "BCD", "CDE", "BDE"]``.

A line only counts when it is EXACTLY ``LETTER(digits+digits...)`` (whitespace
tolerated) with digits 1-5 only — anything else (``A(1+6)``, prose containing
``A(1+2)`` mid-sentence, a mid-field lookalike) is not a hint line. Only
TRAILING hint lines of a field are collected; hint-like lines in the middle
of a field are left alone.

Hard constraint: the raw hint block text (e.g. ``A(1+3+4)``) is stripped out
of the proposition (A-E) text fields it was found in. It must only ever land
in the Hint column — never in, nor overwriting, proposition text.

Output: every QCM gets ``hint`` — an array of combo strings, or ``[]`` when
the QCM has no hint block.

Placement: runs at the START of the Step 2 auto-enrich cascade
(run_post_step2_metadata), unconditionally (no toggle, no strategy gate),
BEFORE Step 3, the Phase-1 checker, and the Step 4/5 build — so every
downstream consumer sees scrubbed propositions + ``hint`` arrays. Pure
Python: no LLM, no model config, no cost. Idempotent by construction (a
re-run finds no raw hint lines left and leaves existing ``hint`` values
untouched).
"""
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Full-line match only: LETTER(digits+digits...) with digits 1-5.
# Surrounding whitespace tolerated. Anything else is not a hint line.
HINT_LINE_RE = re.compile(r"^([A-E])\s*\(\s*([1-5](?:\s*\+\s*[1-5])*)\s*\)\s*$")

_NUM_TO_LETTER = {"1": "A", "2": "B", "3": "C", "4": "D", "5": "E"}

PROP_LETTERS = ["a", "b", "c", "d", "e"]


def _combo_from_numbers(nums: List[str]) -> str:
    """Map numbers to letters (1=A..5=E), then normalize: sort + dedupe."""
    letters = sorted({_NUM_TO_LETTER[n] for n in nums})
    return "".join(letters)


def _parse_hint_line(line: str) -> Optional[str]:
    """Return the combo string for one hint-pattern line, else None."""
    m = HINT_LINE_RE.match(line.strip())
    if not m:
        return None
    nums = re.findall(r"[1-5]", m.group(2))
    if not nums:
        return None
    return _combo_from_numbers(nums)


def _split_trailing_hints(value: Any) -> Tuple[Any, List[str]]:
    """Split trailing hint-pattern lines off a text field.

    Returns (cleaned_value, combos_in_document_order). Non-string values
    pass through untouched with no combos. Only a TRAILING run of hint
    lines is collected — hint-like lines in the middle stay put.
    """
    if not isinstance(value, str) or not value.strip():
        return value, []
    lines = value.split("\n")
    combos: List[str] = []
    cut = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if not lines[i].strip():
            cut = i  # skip blank padding lines, keep scanning upward
            continue
        combo = _parse_hint_line(lines[i])
        if combo is None:
            break
        combos.append(combo)
        cut = i
    if not combos:
        return value, []
    combos.reverse()
    cleaned = "\n".join(lines[:cut]).rstrip()
    return cleaned, combos


def parse_qcm_hints(qcm: Dict) -> Tuple[List[str], Dict[str, str]]:
    """Parse + scrub one QCM. Returns (combos, {field_key: cleaned_value}).

    Fields are scanned in document order: question text, nested propositions
    a-e, then top-level A-E fallbacks. Identical combos collected from more
    than one field are deduped (first occurrence wins).
    """
    combos: List[str] = []
    cleaned: Dict[str, str] = {}

    text = qcm.get("text") or qcm.get("Text")
    if isinstance(text, str):
        new_text, found = _split_trailing_hints(text)
        if found:
            key = "text" if "text" in qcm else "Text"
            cleaned[key] = new_text
            combos.extend(found)

    props = qcm.get("propositions") or {}
    if isinstance(props, dict):
        for letter in PROP_LETTERS:
            for key in (letter, letter.upper()):
                if key in props and isinstance(props[key], str):
                    new_val, found = _split_trailing_hints(props[key])
                    if found:
                        cleaned[("propositions", key)] = new_val
                        combos.extend(found)
                    break

    for letter in ["A", "B", "C", "D", "E"]:
        if letter in qcm and isinstance(qcm[letter], str):
            new_val, found = _split_trailing_hints(qcm[letter])
            if found:
                cleaned[letter] = new_val
                combos.extend(found)

    # Dedupe identical combos, preserving first-occurrence order.
    seen = set()
    unique: List[str] = []
    for c in combos:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique, cleaned


def _apply_cleaned(qcm: Dict, cleaned: Dict[str, str]) -> None:
    """Write scrubbed field values back into the QCM dict in place."""
    for key, val in cleaned.items():
        if isinstance(key, tuple) and key[0] == "propositions":
            qcm["propositions"][key[1]] = val
        else:
            qcm[key] = val


def _load_step2_qcms(step2_accepted: Path) -> Tuple[List[Tuple[Path, Dict]], Dict[Path, List[Dict]]]:
    """Load every Step 2 accepted QCM file in document order.

    Files visited sorted by name; in-file list order preserved. ``merged_*``
    files (mirrored back by the auto-build on re-runs) are skipped — they
    carry the template schema, not extraction fields.
    """
    entries: List[Tuple[Path, Dict]] = []
    file_data: Dict[Path, List[Dict]] = {}
    for q_file in sorted(step2_accepted.glob("*.json")):
        if q_file.name.startswith("merged_"):
            continue
        try:
            with open(q_file, "r", encoding="utf-8") as f:
                qcms = json.load(f)
        except Exception as e:
            print(f"[HINT] ⚠️ Could not read {q_file.name}: {e}")
            continue
        if not isinstance(qcms, list):
            continue
        file_data[q_file] = qcms
        for i, qcm in enumerate(qcms):
            qcm.setdefault("uid", f"noidx_{q_file.stem}_{i}")
            entries.append((q_file, qcm))
    return entries, file_data


def run_hint_detection(context) -> Dict:
    """Parse + scrub hint blocks on Step 2 QCMs; stamp every QCM with ``hint``.

    Must run after Step 2 wrote step2_qcm/accepted/*.json and before Step 3.
    Returns:
        {"status": "ok",      "stats": {...}}
        {"status": "no_qcms"}  # nothing to scan
    """
    print("\n" + "═" * 60)
    print("HINT DETECTION  (Phase 3 — always-on, deterministic)")
    print("═" * 60)

    try:
        step2_accepted = Path(context.get_path("step2_qcm", "accepted"))
    except Exception as e:
        return {"status": "error", "detail": f"project context error: {e}"}

    if not step2_accepted.exists():
        print("[HINT] No step2_qcm/accepted folder — nothing to scan.")
        return {"status": "no_qcms"}

    entries, file_data = _load_step2_qcms(step2_accepted)
    if not entries:
        print("[HINT] No accepted Step 2 QCM JSON found — nothing to scan.")
        return {"status": "no_qcms"}

    stats = {"qcms_scanned": 0, "qcms_with_hints": 0,
             "combos_total": 0, "fields_scrubbed": 0}
    touched_files = set()

    for _q_file, qcm in entries:
        stats["qcms_scanned"] += 1
        combos, cleaned = parse_qcm_hints(qcm)

        if cleaned:
            _apply_cleaned(qcm, cleaned)
            stats["fields_scrubbed"] += len(cleaned)
            touched_files.add(_q_file)

        if combos:
            qcm["hint"] = combos
            stats["qcms_with_hints"] += 1
            stats["combos_total"] += len(combos)
            print(f"[HINT] Q{qcm.get('number', '?')} p.{qcm.get('page', '?')} → "
                  f"{len(combos)} combo(s): {', '.join(combos)}")
        elif "hint" not in qcm:
            qcm["hint"] = []
            touched_files.add(_q_file)
        # else: re-run over an already-parsed QCM — leave its hint untouched.

    for q_file in touched_files:
        with open(q_file, "w", encoding="utf-8") as f:
            json.dump(file_data[q_file], f, indent=2, ensure_ascii=False)
    if touched_files:
        print(f"[HINT] 💾 Hint fields written → "
              f"{', '.join(sorted(p.name for p in touched_files))}")

    print("\n" + "═" * 60)
    print("📊 HINT DETECTION SUMMARY")
    print("═" * 60)
    print(f"  QCMs scanned:       {stats['qcms_scanned']}")
    print(f"  QCMs with hints:    {stats['qcms_with_hints']}")
    print(f"  Combos extracted:   {stats['combos_total']}")
    print(f"  Fields scrubbed:    {stats['fields_scrubbed']}")
    print("═" * 60)

    return {"status": "ok", "stats": stats}
