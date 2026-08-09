# Plan — Enrich Step 3 Metadata Detector with Algerian Medical Exam Taxonomy

> Goal: give the Step 3 metadata LLM a **structured context** (valid faculties, modules-by-level, derivation rules) so it stops returning `categoryName=null` / wrong year / "Externat" with no faculty. Currently both detector prompts are generic free-text and the model often returns null when the module header isn't on page 1.

---

## 1. Where this hooks in (the two detector paths)

| File:line | Function | When it fires | Current prompt |
|---|---|---|---|
| `modules/step3_metadata.py:854` | `_extract_metadata_with_ai(text, fields, context_desc)` | Global + Per-QCM strategies for **Year/Source/Category/Subcategory** (the default cascade) | Generic — "Extract specific metadata: {field_list} ... Return ONLY JSON." No taxonomy. |
| `modules/utils/ai_metadata_detector.py:14` | `detect_all_fields(text, fields)` | The `"A"` (ai_detect) strategy | Generic INSTRUCTIONS block (lines 40-44) — examples like "Pédiatrie", "Cardiologie" but no closed list. |

Both need the same enrichment. We'll factor the taxonomy into a **single shared module** so the two paths stay in sync.

---

## 2. The taxonomy source file (JSON, committed to repo)

**New file:** `modules/utils/metadata_taxonomy.json`

```json
{
  "system_instruction": "Extract 'module', 'level', and 'source' metadata from Algerian medical exam PDFs.",
  "valid_faculties": [
    "Alger", "Oran", "Constantine", "Annaba", "Sétif", "Tlemcen",
    "Sidi Bel Abbès", "Blida", "Tizi Ouzou", "Béjaïa", "Batna",
    "Mostaganem", "Laghouat", "Ouargla", "Béchar"
  ],
  "valid_modules": {
    "1ère année (Lvl 1)": ["Anatomie", "Biochimie", "Biostatistique", "Chimie", "Biophysiques", "Cytologie", "Embryologie", "Histologie", "Physiologie générale", "SSH"],
    "2ème année (Lvl 2)": ["Génétique", "Immunologie", "Appareil Digestif", "Endocrinologie", "Système Nerveux et Organes des Sens", "Appareil Urinaire", "Appareil Cardio-Respiratoire"],
    "3ème année (Lvl 3)": ["Immunologie 3ème", "Anatomie Pathologique", "Microbiologie", "Parasitologie-Mycologie", "Pharmacologie", "Appareil Digestif et Hématologie", "Appareil Endocrinien de Reproduction et Urinaire", "Appareil Cardiovasculaire et Respiratoire", "Appareil Neurologique Locomoteur et Cutané"],
    "4ème année (Lvl 4)": ["Cardiologie", "Hématologie et Oncologie", "Gastro-entérologie", "Infectiologie", "Neurologie", "Pneumologie"],
    "5ème année (Lvl 5)": ["Endocrinologie", "Gynécologie-Obstétrique", "Urologie Néphrologie", "OTR et MPR", "Psychiatrie", "Pédiatrie"],
    "6ème année (Lvl 6)": ["Dermatologie", "Épidémiologie", "Gériatrie", "Maladies de Système", "Médecine du Travail", "Médecine Légale", "Ophtalmologie", "ORL", "UMC"]
  },
  "rules": [
    "Year: '2025/2026' → '2025', '2024/2025' → '2024'. Always use the START year of the pair.",
    "Faculty: must match one of valid_faculties exactly (case-insensitive, accent-tolerant).",
    "If a module matches valid_modules → source = 'Externat {Faculty}'.",
    "If no module matches, OR the document indicates a residency exam (Résidanat), → module = null and source = 'Residanat {Faculty}'.",
    "Level: infer from the matched module's level label (e.g. Cardiologie → '4ème année (Lvl 4)'). null if unknown."
  ]
}
```

**Notes / decisions to lock:**
- Q1: The taxonomy is a JSON file in repo (not a Supabase table) so it ships with the build. To update, edit the file + push. Fine — it changes rarely.
- Q2: The file is **cached** on first load (module-level dict); reloading requires container restart. Acceptable for a taxonomy that changes once a year.
- Q3: Filename keys for `valid_modules` are the level labels themselves (so the LLM can echo the level directly and we can reverse-lookup module→level in Python).
- Q4: We add two NEW output fields beyond the current four: `module` (the matched module name, normalized) and `level` (the level label). The existing `category` field in the current schema maps to `module` — see §4 for the migration.

---

## 3. New shared helper module

**New file:** `modules/utils/metadata_context.py`

```python
"""Shared taxonomy loader + prompt-builder for Step 3 metadata detection.
Used by both step3_metadata._extract_metadata_with_ai and
ai_metadata_detector.detect_all_fields so the two paths stay in sync."""
import json
from functools import lru_cache
from pathlib import Path

TAXONOMY_FILE = Path(__file__).parent / "metadata_taxonomy.json"


@lru_cache(maxsize=1)
def load_taxonomy() -> dict:
    """Load + cache the Algerian medical exam taxonomy."""
    with open(TAXONOMY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def build_context_block() -> str:
    """Render the taxonomy as a deterministic text block for the LLM prompt."""
    tax = load_taxonomy()
    faculties = ", ".join(tax["valid_faculties"])
    lines = [
        f"SYSTEM: {tax['system_instruction']}",
        f"VALID FACULTIES: {faculties}",
        "VALID MODULES BY LEVEL:",
    ]
    for level, modules in tax["valid_modules"].items():
        lines.append(f"  {level}: {', '.join(modules)}")
    lines.append("RULES:")
    for r in tax["rules"]:
        lines.append(f"  - {r}")
    return "\n".join(lines)


def normalize_module(value: str) -> str | None:
    """Case-insensitive, accent-tolerant match against valid_modules.
    Returns the canonical module name or None."""
    if not value:
        return None
    tax = load_taxonomy()
    target = _strip_accents(value).lower()
    for level, modules in tax["valid_modules"].items():
        for m in modules:
            if _strip_accents(m).lower() == target:
                return m
    return None


def module_to_level(module: str) -> str | None:
    """Reverse-lookup: canonical module name → level label (or None)."""
    if not module:
        return None
    tax = load_taxonomy()
    target = _strip_accents(module).lower()
    for level, modules in tax["valid_modules"].items():
        if any(_strip_accents(m).lower() == target for m in modules):
            return level
    return None


def normalize_year(value: str) -> str | None:
    """Apply the year rule: '2025/2026' → '2025', '2024' stays '2024'."""
    if not value:
        return None
    v = str(value).strip()
    if "/" in v:
        return v.split("/")[0].strip()
    return v


def normalize_faculty(value: str) -> str | None:
    """Case/accent-tolerant match against valid_faculties. Returns canonical or None."""
    if not value:
        return None
    tax = load_taxonomy()
    target = _strip_accents(value).lower()
    for f in tax["valid_faculties"]:
        if _strip_accents(f).lower() == target:
            return f
    return None


def _strip_accents(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def derive_source(module: str | None, faculty: str | None, is_residanat: bool = False) -> str | None:
    """Apply the source-derivation rule.
    - Externat: module matched → 'Externat {Faculty}'
    - Residanat: no module OR is_residanat flag → 'Residanat {Faculty}'"""
    if not faculty:
        return None
    if module and not is_residanat:
        return f"Externat {faculty}"
    return f"Residanat {faculty}"
```

This gives us:
1. One cached taxonomy loader.
2. A `build_context_block()` for the prompt (injected into both detectors).
3. Python post-processing (`normalize_*`) so the LLM's free-text answer gets **validated** against the closed list — model returns `"cardiologie"` → we canonicalize to `"Cardiologie"` and reject `"Foo"` to `null`. This is the "validate after the LLM" pattern that prevents hallucinated module names.

---

## 4. Field mapping — `category` stays as `module` only

The taxonomy structure groups modules by level (the level labels are the **keys** of `valid_modules`), but we do **NOT** add a `level` output field. The level structure stays in the taxonomy purely as context to help the LLM find the canonical module name, then Python validates it.

- The existing `category` field (internally `module_detected`, mapped to `categoryName` in Step 5) **stays as the only module-related output**.
- The LLM is asked for `Category` only (no `level`).
- Post-processing: `qcm["module_detected"] = normalize_module(raw_category)` — canonical module name or `null` (per D4 — reject hallucinations to null).
- No changes to `DEFAULT_TEMPLATE_XLSX`, no `level` column in the xlsx, no frontend changes.

---

## 5. Patch 1 — `step3_metadata._extract_metadata_with_ai`

**File:** `modules/step3_metadata.py:854`

Before:
```python
def _extract_metadata_with_ai(self, text: str, fields: List[str], context_desc: str) -> Dict:
    field_list = ", ".join(fields)
    prompt = f"""TASK: Extract specific metadata: {field_list}
CONTEXT: {context_desc}
INPUT TEXT:
{text}
...
"""
```

After:
```python
def _extract_metadata_with_ai(self, text: str, fields: List[str], context_desc: str) -> Dict:
    from modules.utils.metadata_context import build_context_block, normalize_module, normalize_year, normalize_faculty, derive_source, module_to_level

    field_list = ", ".join(fields)
    taxonomy_block = build_context_block()
    prompt = f"""TASK: Extract specific metadata: {field_list}
CONTEXT: {context_desc}

{taxonomy_block}

INPUT TEXT:
{text}

INSTRUCTIONS:
- Return ONLY JSON. Keys: {field_list}
- "module": a canonical module name from VALID MODULES BY LEVEL (exactly as written). null if unknown.
- "level": the level label containing the matched module (e.g. "4ème année (Lvl 4)"). null if module unknown.
- "year": the START year of any "YYYY/YYYY" pair (e.g. "2025/2026" → "2025"). Plain 4-digit year stays as-is.
- "source": derived — see RULES. "Externat {{Faculty}}" if module matched, else "Residanat {{Faculty}}". null if faculty unknown.
- "subcategory": specific topic if present, else null.

If a field is not found or ambiguous, use null.
"""
```

And after parsing the response, add a **post-processing pass** that runs the LLM's values through the Python normalizers (the LLM is the *recommender*, Python is the *validator*):

```python
data = json.loads(json_str)
# Validate + canonicalize against the taxonomy
if "module" in data or "Category" in data:
    raw_mod = data.get("module") or data.get("Category")
    data["Category"] = normalize_module(raw_mod) or None
    data["level"] = module_to_level(data["Category"]) or data.get("level")
if "year" in data or "Year" in data:
    data["Year"] = normalize_year(data.get("year") or data.get("Year"))
if "source" in data or "Source" in data:
    faculty = normalize_faculty(<extract faculty from text or from data["source"]>)
    data["Source"] = derive_source(data.get("Category"), faculty)
# ... existing cost logging ...
return data
```

The faculty extraction needs care — sometimes it's embedded in `source` ("Résidanat Oran") sometimes in the text ("Université de Tlemcen"). Add a small helper `_extract_faculty(text, llm_source)` that regex-searches the page text for any `valid_faculties` mention and prefers that over the LLM's guess.

---

## 6. Patch 2 — `ai_metadata_detector.detect_all_fields`

**File:** `modules/utils/ai_metadata_detector.py:14`

Same enrichment — inject `build_context_block()` into the prompt (lines 32-55) and post-process `data` (line 83) with the same normalizers. The detector's return shape already includes `value` + `confidence`; we keep those, just canonicalize `value` through the normalizers and **set confidence to 0.0** when the normalizer returns `None` (so `filter_by_confidence` drops hallucinated modules).

This path only fires on the `"A"` (ai_detect) strategy. The default cascade uses `"G"` (global) which goes through Patch 1. But enriching both keeps behavior consistent if the user enables ai_detect.

---

## 7. Patch 3 — `DEFAULT_STEP3_CONFIG` (NOT IMPLEMENTED — removed per user)

The earlier draft proposed changing `global_pages "1"→"1,2"` and `source "skip"→"global"` in `DEFAULT_STEP3_CONFIG`. **Removed from scope.** The taxonomy enrichment (Patches 1 + 2) is the only change.

---

## 8. Testing plan

**New file:** `tests/test_metadata_context.py`

| Test | What it verifies |
|---|---|
| `test_load_taxonomy` | `load_taxonomy()` returns dict with required keys; cached on second call |
| `test_normalize_module` | `"cardiologie"`→`"Cardiologie"`, `"Cardiologie"`→`"Cardiologie"`, `"foo"`→`None` (case + accent tolerant) |
| `test_normalize_year` | `"2025/2026"`→`"2025"`, `"2024"`→`"2024"`, `None`→`None` |
| `test_normalize_faculty` | `"oran"`→`"Oran"`, `"TLEMCEN"`→`"Tlemcen"`, `"foo"`→`None` |
| `test_derive_source` | `(module="Cardiologie", faculty="Oran")`→`"Externat Oran"`; `(None, "Oran")`→`"Residanat Oran"`; `(module="X", faculty="Oran", is_residanat=True)`→`"Residanat Oran"` |
| `test_find_faculty_in_text` | `"Université de Tlemcen"`→`"Tlemcen"`, `"no mention"`→`None` |
| `test_build_context_block` | Output contains all 15 faculties, all 6 levels, the year rule text; deterministic |

**Update:** `tests/test_post_step2_metadata.py` — verify the enriched detector still gets called and the cascade still completes (the patch only changes the prompt, not the call shape).

**Manual E2E:** on the affected HF project (after fix #1 from the previous session ships):
- Re-run Step 2 → Step 3 should populate `module_detected`, `source`, `year` for the 45 real QCMs.
- Verify `merged_qcms.xlsx`: `categoryName` should be "Neurology" → canonicalized to "Neurologie" for all rows, `Year` = "2025/2026" → "2025", `Source` = "Externat {Faculty}" (or `Residanat` if applicable).
- Verify hallucinated "DB" QCMs (if any slip past fix #2) get `module=null` because "SGBD" is not in `valid_modules` — they'll be visually obvious in the xlsx as rows with a null module column.

---

## 9. Rollout order

1. **Commit `metadata_taxonomy.json` + `metadata_context.py` + Patch 1 + Patch 2 + tests** in one commit (atomic — the helpers + the two call sites update together).
2. Push to `space`. Re-run on the affected HF project → verify the 45 real QCMs now have `module_detected=Neurologie`, `source=Externat/Residanat {Faculty}`, `year=2025`.
3. Update `SESSION_RESUME.md` with the new files + the taxonomy-edit workflow.

Total diff size: ~130 lines (taxonomy JSON ~60, helper module ~60, two prompt changes ~10 each, tests ~40).

---

## 10. Open decisions (resolved)

| # | Decision | Resolution |
|---|---|---|
| D1 | Where the taxonomy lives | `modules/utils/metadata_taxonomy.json` in repo (ships with build) |
| D2 | Add `level` field | **NO** — category stays as module only (per user) |
| D3 | Folder-name fallback for module | Not in this scope — LLM-only (can revisit later) |
| D4 | Post-detect validation strictness | Reject hallucinated module to null (keeps the closed list meaningful) |
| D5 | `DEFAULT_STEP3_CONFIG` edit | **REMOVED from scope** (per user) — no changes to the default config |