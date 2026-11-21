# Plan — Exam papers, sections and question numbers (MBset `Exams` column)

Status: PLAN ONLY (no code yet) · 2026-11-19 · decisions updated 2026-11-21

> **Read §11 first.** The user's decisions of 2026-11-21 change the OUTPUT format:
> the MBset import file uses the template's `Number` + `Year` + `Tag` (session label)
> + `Cas` columns, **one row per paper occurrence**, and leaves `Exams` empty. Wherever an
> earlier section says "write `Exams`" for the import file, §11 wins. The internal `papers`
> model (§3) is unchanged — it is just serialised to `Number/Year/Tag` instead of `Exams`.
Scope: make the pipeline produce a correct MBset import file for BOTH document types:

- **A. Normal exam PDF** — one exam paper (e.g. *Externat Blida · EMD1 2025*), questions
  numbered 1..N, sometimes split into parts (*Partie théorique / Partie pratique*,
  *Session normale / Rattrapage*) where numbering restarts.
- **B. Classified compilation** ("QCM classé", e.g. `gyneco QCM classé 2025.pdf`) — questions
  sorted by topic, each preceded by its own **origin line**:

  ```
  • Question N° 32, Sec 01 de l'année 2021-2022
  29- Quelles sont les étiologies de l'HRP (cochez la réponse juste).
  a. ...
  • Question N° 07, Partie pratique, Sec 01 de l'année 2021-2022
  7- Une hypertonie utérine : ...
  ```

  Here every question has **two numbers**: `29-` = its position in the compiled document
  (restarts per chapter) and `N° 32` = its number in the ORIGINAL paper
  (*Sec 01, 2021-2022*). MBset needs the second one, per paper, in `Exams`.

---

## 1. What MBset expects (from `mbset-smart-import` SKILL.md §3.1, §6.4, §7)

| Column | Rule |
|---|---|
| `Exams` | One part per paper: `Source · Period Year · N°n`; papers separated by ` \| `. Example: `Externat Setif · EMD1 2025 · N°12 \| Externat Setif · EMD1 2026 · N°7`. **The only place a number may go.** Year is required in every part; a part with no year or two sources refuses the whole row. |
| `Year` | Derived by the server from `Exams` (newest paper). Legacy / wizard fallback only. |
| `Tag` | FREE tags only. **Never** a number (`N° 12`), never `Corrigé type/proposé`. Server rebuilds exam tags from `Exams`. |
| `Number`, `Period`, `Year` | Wizard "one paper for the whole file" mode. `Exams` on a row replaces them. |
| `Cas` | Rows with the same case text become one case (wizard). |
| `Official` / `Official 2…5` | `B or E` → `Official=B`, `Official 2=E`; `B,E` means AND. |
| Unknown columns | Ignored and listed in the preview (harmless, but noisy). |

Consequence: the pipeline must output, for every QCM, a list of **papers**
`{source, period, year, number}` and serialise it into `Exams`. Everything else in this plan
exists to fill that list correctly and to stop numbers from colliding inside the pipeline.

---

## 2. What the system does today (verified in code)

| # | Problem | Where | Effect |
|---|---|---|---|
| P1 | No concept of **paper / period / section**. Only `source`, `year`; `Tag = [source, year]`. | `step3_metadata.py:~818-828` | No `Exams` column; *Sec 01 / Rattrapage / Partie pratique* are lost. |
| P2 | **One `number` per QCM.** Step 2 prompt asks for "the number"; in a compilation the model picks `29` or `32` unpredictably. | `step2_qcm_extract_batch.py` prompt | Wrong / inconsistent numbers. |
| P3 | Labels like `QuestionN010` → `_safe_int()` fails → **number = 0**. | `_sanitize_qcms` | Silent loss of the number. |
| P4 | Origin line sits right after the previous question's option `e.` → can be glued into proposition E or dropped. | Step 2 prompt has no rule for it | Polluted option text, lost paper info. |
| P5 | **Numbers assumed sequential**: previous-page numbering context (sequential) and `_fill_missing_numbers` (parallel). | Step 2 | Wrong in compilations (non-sequential) and across part restarts. |
| P6 | **Step 6 corrections keyed by bare number** `str(Num)`. | `step6_corrections.py:973` and ~10 other sites | Theory Q1 and Practice Q1 (or Normale Q1 and Rattrapage Q1) get the SAME answer; one key overwrites the other. |
| P7 | Step 3 clinical-case anchoring is by QCM number (`anchor_num`). | `step3_metadata.py` CC v4 | Duplicate numbers on one page can mis-anchor; an origin line between narrative and question can break the link. |
| P8 | `normalize_year` handles `2025/2026` only; `2020-2021`, `20.17-2018` (OCR) pass through unchanged. | `metadata_context.py:67` | Invalid year → MBset refuses the row. |
| P9 | **Template placeholders leak**: `_map_to_template` starts from `template.copy()` whose defaults are `Year 2024`, `Tag ["Externat","2024"]`, `Correct "ABC"`, `categoryName "Cardiologie"`… A missing value keeps the fake one. | `post_step3_build.py:19-36`, `step5_builder._map_to_template` | Fake year/tag/answer in the export. |
| P10 | Step 8 merges duplicate questions' `Tag` lists, not their papers. | `step8_matcher.py:~987` | A question that appeared in EMD1 2024 AND 2025 loses one paper. |
| P11 | OCR prompt has no rule to keep origin lines / numbering prefixes verbatim. | `step1_extraction._build_vision_prompt` | Lines may be summarised away on scanned pages (pages 1–200 of the gyneco PDF have no text layer). |

---

## 3. Target data model (internal, per QCM)

Keep every existing field. Add:

```jsonc
{
  "number": 29,                 // UNCHANGED meaning: number printed IN THIS DOCUMENT ("29-")
  "scope": "ch:Hématome rétro-placentaire",   // numbering scope (see §4.2) — section/chapter/part
  "origin_raw": "Question N° 32, Sec 01 de l'année 2021-2022",  // verbatim, never edited
  "papers": [                   // → Exams column
    {"source": "Externat Blida", "period": "Sec 01", "year": 2021,
     "number": 32, "section": null,
     "from": "origin_line",     // origin_line | section_header | doc_header | project_config
     "confidence": "ok"}        // ok | suspect (§5.3) | missing_year
  ],
  "review_flags": ["exam_number_suspect"]      // empty when clean
}
```

- **`number` keeps its current meaning** (printed in this document) so Step 3/6/8, Sheets
  sync, and the `Num` column keep working. The paper number lives ONLY in `papers[].number`.
- For a **normal exam** the two numbers are the same: `papers = [{…, number: number}]`.
- **Identity** stays `uid` (page-based, already unique). Every matching that used the bare
  number moves to the **scoped key** `(scope, number)`.

---

## 4. Detection logic

### 4.1 Document mode (auto, overridable)

Step 2 already reads every page. Add a deterministic pre-scan of Step 1 text:

- `compilation` if ≥ 30 % of QCM-bearing pages contain origin lines (regex §5.1).
- else `single_paper`.
- User override in the Step 2 panel and the batch wizard: **Auto / Single paper / Compilation**.

Mode decides: number filling (§4.3), where papers come from (§4.4), Step 6 keys (§6).

### 4.2 Numbering scope (sections that restart numbers)

A **scope** is a stretch of the document where printed numbers are unique. A new scope starts at:

1. A recognised **section header** line: `Partie théorique`, `Partie pratique`,
   `Session normale`, `Rattrapage`, `Cas cliniques`, `Questions à réponse…`, chapter titles
   in compilations (`Les anomalies de la contraction utérine`). Vocabulary is configurable (§7.3).
2. A **number restart**: the printed number drops to 1 (or below the previous number by
   more than a configurable gap) with no header → new anonymous scope `part-2`, flagged
   `scope_inferred` for review.

`scope` = normalised header text or `part-N`. Within a scope `(scope, number)` must be
unique; a duplicate is flagged `duplicate_in_scope` (never silently merged).

### 4.3 Missing numbers

- `single_paper`: fill `number` by sequence **within the scope only** (current logic,
  scope-aware). Same for the paper number (equal to it).
- `compilation`: fill `number` (document position) by sequence within the chapter; **never
  infer a paper number** — missing → `papers[].number = null`, flag `exam_number_missing`.
  (`Exams` allows a part without `N°`.)

### 4.4 Where each paper field comes from (precedence, first non-empty wins)

| Field | 1. Origin line | 2. Section header | 3. Document header (Step 3 global) | 4. Project / batch config | 5. Otherwise |
|---|---|---|---|---|---|
| source | (rarely present) | — | faculty → `Externat {Fac}` / `Residanat {Fac}` (existing rule) | region/faculty tag of the project | empty → flag `source_missing` |
| period | `Sec 01`, `Rattrapage`, `EMD1`… | `Rattrapage`, `Session normale` | header (`EMD 1`, `Synthèse`…) | config Period | empty (MBset allows `· 2024 ·`) |
| year | `2021-2022` → rule §5.2 | — | header year | config Year | **flag `missing_year`, never a default** |
| number | `N° 32` | — | — | — | single_paper: printed number |
| section | `Partie pratique` | header `Partie pratique` | — | — | null |

No template default may ever fill these (fixes P9).

---

## 5. Deterministic parsers (Python, not LLM)

LLMs propose; Python parses and validates (same pattern as `metadata_context.py`).

### 5.1 Origin-line parser `parse_origin_line(text) -> Paper | None`

Tolerant regex over accent-stripped, OCR-normalised text. Observed real variants
(gyneco PDF pages 201-231) — each becomes a unit test:

| Raw OCR | Parsed |
|---|---|
| `Question N° 32, Sec 01 de l'année 2021-2022` | n=32, period=Sec 01, year=2021-2022 |
| `QuestionN° 38, Rattrapage de l'ann6e 2018-2019` | n=38, Rattrapage, 2018-2019 |
| `Question N° 32, Sec 01 de t•ann~ 2021-2022` | n=32, Sec 01, 2021-2022 |
| `Question N> 02, Participratique, Sec 01 de l'année 20.17-2018` | n=2, section=Partie pratique, Sec 01, 2017-2018 |
| `Question N° 07, Partie pratique, Sec 01 de l'ann" 2021-2022` | n=7, Partie pratique, Sec 01, 2021-2022 |
| `Question N° 401 Rattrapage de l'année 2023-2024` | n=40 **suspect** (missing comma read as `1`) |
| `QuestionN010` (no period) | n=10, period/year from higher levels |

Shape: `Question\s*N\s*[°o>º.]?\s*(\d{1,3})` → optional `,` → optional section
`(Partie\s*\w+|Parti\w*pratique|…)` → period `(Sec\s*0?\d|Rattrapage|Session\s*\w+|EMD\s*\d|…)`
→ `de\s*l\W?ann\S*` → year pair `(\d{2}[.\s]?\d{2})\s*[-/–]\s*(\d{4})`.
Leading zeros are kept for display (`010` → `N°10` in Exams; MBset stores numbers).

### 5.2 Year rule

`normalize_year` accepts `YYYY`, `YYYY/YYYY`, `YYYY-YYYY`, `YYYY–YYYY`, OCR `20.17-2018`,
`2017 - 2018`. Pair → **one** year by the rule chosen in Decision D1 (taxonomy today = START
year). Reject anything outside 1990..current+1 → `missing_year`.

### 5.3 Suspect-number checks (flag, never auto-fix)

- 3-digit number where the line has no comma after it and the 2-digit prefix fits the
  usual range (`401` → maybe `40,`) → `exam_number_suspect`.
- Paper number > configurable max (default 150).
- Same `(source, period, year, number)` on two different questions in this document →
  `exam_number_duplicate` (in a compilation this usually means an OCR misread).

### 5.4 Alignment (cross-check the LLM)

Step 2 returns `origin_raw` per QCM. Independently, the parser lists origin lines per page in
reading order. If the counts match, align by order and compare; on disagreement trust the
deterministic parse of the page line and flag `origin_mismatch`. If counts differ, keep the
LLM's attachment and flag.

---

## 6. Changes per step

### Step 1 — OCR prompt (P11)
Add rules: "Transcribe exam origin lines such as `• Question N° 32, Sec 01 de l'année
2021-2022` verbatim on their own line, BEFORE the question they introduce. Keep numbering
prefixes (`29-`, `30-`) and section/chapter titles (`Partie pratique`, `Rattrapage`) exactly."
Pages already cached keep their text (OCR cache) — re-run with `force_overwrite` for old projects.

### Step 2 — QCM extraction (P2, P3, P4, P5)
- Prompt: new output fields `origin_raw` (verbatim origin line that **precedes** the question,
  null if none) and `section_header` (latest section/chapter heading above it, null if none).
  `number` = the number printed **in front of the question text** (`29-`), never the `N°` of
  the origin line. Rule: "An origin line belongs to the question that FOLLOWS it. Never put it
  inside a proposition."
- Remove the previous-page numbering rule in `compilation` mode (numbers not sequential).
- `_sanitize_qcms`: extract digits from labels (`QuestionN010` → 10, `N° 7` → 7) before
  giving up; keep 0 only when no digit exists, and flag.
- Post-pass (Python): mode detection §4.1, scopes §4.2, scope-aware fill §4.3, origin
  parse + alignment §5. Writes `scope`, `papers`, `review_flags` into `all_qcms.json`.
- Strip any trailing origin-line text that still leaked into proposition `e`.

### Step 3 — metadata (P1, P7, P8)
- Global/document metadata prompt also returns `period` (EMD1, Rattrapage, Synthèse,
  Session normale…) and the raw year text; Python normalises (§5.2).
- Fill `papers` by precedence §4.4; keep `year`/`source` fields as derived values for
  backward compatibility.
- `Tag` = free tags only (existing source/year tags kept as today if Decision D4 says so),
  **never** a number or period-number.
- CC detector prompt: add origin lines to the "NOT a narrative" list and tell it an origin
  line between a narrative and its question does not break the link. Anchoring uses
  `(page, position)` instead of the bare number when the page has duplicate numbers.

### Step 4/5 — template + build (P9)
- Template values become **types/columns only**: missing → empty cell. Remove the
  placeholders `Year 2024`, `Tag ["Externat","2024"]`, `Correct "ABC"`, `categoryName
  "Cardiologie"`, `tagSuggere "Semiologie"`, `Type "QCS"`, `Exp ""` from `DEFAULT_TEMPLATE_XLSX`
  and from `_map_to_template`'s starting row.
- `_map_to_template` carries `papers`, `scope`, `origin_raw`, `review_flags`.
- Build `Exams` with `format_exams(papers)`: ` · ` between parts, ` | ` between papers,
  `N°n` only when the number is known, period omitted when empty (`Externat Setif · 2024 · N°28`).
  A paper without a year is NOT written (MBset would refuse the row) → flag instead.

### Step 6 — corrections (P6)
- All ~12 lookups `str(Num)` → scoped key `(scope, number)` via one helper
  (`qcm_key(qcm)`), single source of truth.
- Correction prompts return the scope label of each answer table when the page shows one
  (`Corrigé partie pratique`, `Rattrapage`, chapter title) — `{"scope": "...", "answers": {"1": "AB"}}`.
- Apply rule: table with scope → apply within that scope. Table without scope:
  - number unique across scopes → apply;
  - number exists in several scopes → apply to the scope of the nearest preceding question
    pages (compilations put the key at the end of each chapter); if still ambiguous → do
    NOT apply, flag `correction_ambiguous`.
- Alternative answers ("B ou E") → `Official` + `Official 2` (already the MBset rule) —
  keep as-is, just scoped.

### Step 8 — reference DB merge (P10)
- When a question matches a reference question, **union** the papers (dedupe on
  `source+period+year`; keep each paper's own number; a conflicting number for the same paper
  → flag, keep reference value) and rebuild `Exams`. `Tag` merge unchanged.

### XLSX exports
Two files per run (same data):

1. **Review workbook** (today's file, extended): existing columns + `Exams`, `Section`,
   `origin_raw`, `review_flags` at the right, rows with flags highlighted. Used in Google
   Sheets; sync-from-sheets parses `Exams` back into `papers` (same parser as MBset's format).
2. **MBset import workbook** (`*_mbset_import.xlsx`): exactly the columns of
   `mbset-question-import-template.xlsx` (§11.1 O1), in that order. Per row:
   `Number` = original paper number, `Year` = start year, `Tag` = source, year, session
   label (`Sec 01 Pratique`…), `Cas` = case text (§11.2), `Exams` = empty. One row per paper
   occurrence; no duplicate merging. Validated before writing (§8 checks). No `Num`, no
   audit columns → clean preview, no "ignored columns" noise.

### UI
- Step 2 panel + batch wizard: **Document type** (Auto / Single paper / Compilation) and
  **Exam paper** fields `Source`, `Period`, `Year` (same as MBset's Details step), used as
  level-4 fallback.
- Output viewer: a "Needs review" filter on `review_flags`.

---

## 7. Configuration (new, all optional)

1. `exam_mode`: `auto | single_paper | compilation` (default auto).
2. `paper_defaults`: `{source, period, year}` per project / batch.
3. `period_vocabulary` (`metadata_taxonomy.json`): raw → canonical, e.g.
   `sec 01 → Sec 01`, `sec1 → Sec 01`, `rattrapage → Rattrapage`, `emd 1 → EMD1`,
   `session normale → Normale` (final spellings = Decision D3).
4. `section_vocabulary`: `partie pratique / participratique → Pratique`,
   `partie théorique → Théorique`, plus "chapter titles start a scope" (compilation only).
5. `exam_number_max` (150), `year_rule` (`start | end`, Decision D1).

---

## 8. Validation before export (hard checks, run on the MBset import file)

- Import file: `Exams` empty on every row (§11.1 O2). Review file: every `Exams` part has a
  4-digit year; no part has two sources.
- Separators exactly ` · ` and ` | `; `N°` only followed by digits.
- `Tag` contains no `N°`, `No.`, `N12`, `Corrigé`.
- Every row has `Number` (digits) and a 4-digit `Year`; every compilation row has a session label in `Tag`.
- `Cas`: all rows of one case carry the identical string, and those rows form an unbroken
  chain per §11.2 (same paper, numbers +1).
- No duplicate rows for one question (one row per `uid`).
- `(scope, number)` unique; every flagged row listed in a summary sheet.
- A row that fails a hard check is moved to a `rejected` sheet with the reason, not exported.

---

## 9. Test plan

1. **Parser unit tests** — every OCR variant in §5.1 (taken from the real gyneco PDF) +
   year forms §5.2 + suspect checks §5.3.
2. **Fixtures**
   - `compilation_gyneco`: Step 1 text of pages 201–213 → expected `papers` per QCM (hand-checked).
   - `single_paper_two_parts`: synthetic EMD with *Partie théorique* Q1–40 + *Partie pratique*
     Q1–20 + two answer tables → Step 6 must give each Q1 its own answer.
   - `normale_plus_rattrapage`: two sessions in one PDF, numbering restarts, no headers on
     some pages → inferred scope + flag.
   - `plain_exam`: today's normal case → output identical to current except the new `Exams`
     column and no placeholder values (regression guard).
3. **Step 6 collision test** — same number in two scopes, scoped and unscoped tables.
4. **Export contract test** — run §8 on every fixture; compare `Exams` strings to golden files.
5. **Round-trip** — review xlsx → edit `Exams` in Sheets → sync → `papers` updated.
6. **Live run** on `gyneco QCM classé 2025.pdf` (needs a valid OpenRouter key) and one plain
   EMD PDF; upload the import file to MBset **Preview only** and check: 0 errors, no ignored
   columns, numbers on the right papers.

---

## 10. Phases (each shippable, each behind tests)

| Phase | Content | Risk |
|---|---|---|
| 0 | Remove template placeholder leak (P9); `normalize_year` dash/OCR forms (P8); digit extraction in `_sanitize_qcms` (P3). | Low — pure bug fixes |
| 1 | Parsers §5 + taxonomy vocabularies §7 + unit tests. No pipeline change yet. | Low |
| 2 | Step 1/2 prompts + Step 2 post-pass (mode, scope, papers, flags) — data only, exports unchanged. | Medium (prompt change) — compare on fixtures |
| 3 | Step 6 scoped keys (P6) + scoped correction prompts. | Medium–high: touches every correction path |
| 4 | Step 3 papers precedence + CC detector rule (P7); Step 4/5 carry fields; `Exams` in review xlsx. | Medium (CC characterization tests pin prompt text → update them deliberately) |
| 5 | MBset import workbook + validation §8; Step 8 paper union; Sheets round-trip. | Medium |
| 6 | UI (mode, paper defaults, review filter); live validation run §9.6. | Low |

Normal PDFs keep working after every phase: with no origin lines and one scope, the new
logic reduces to today's behaviour plus one `Exams` column.

**Status 2026-11-21: phases 0–4 implemented** (uncommitted). Core logic in
`modules/utils/exam_papers.py`; tests `tests/test_exam_papers.py` +
`tests/test_exam_papers_pipeline.py`. Deviations from the text above:
- Document period for a single-paper exam is read deterministically from the first page
  header (`EMD1`, `Rattrapage`, `Session normale`, `Synthèse`) instead of a new LLM field;
  overrides: env `EXAM_MODE` (`auto|single_paper|compilation`), `EXAM_PERIOD`.
- Step 6: correction maps may carry part-labelled keys (`"Pratique:1"`); the prompt asks for
  them only when the document has several scopes. Per-page scan keeps one entry per page.
- Real-PDF check (text pages 201–231): 78/79 origin lines parsed; 3 flagged suspect,
  1 unreadable number → `exam_number_missing`, 1 unreadable year → `missing_year`.
**Status 2026-11-21 (later): phases 5–6 implemented** except the live run (§9.6 — the
local OpenRouter key returns 401).
- `modules/utils/mbset_export.py`: `mbset_import_<pdf>.xlsx` (one sheet `Questions`, the
  template's 35 columns, `Exams` empty) + `mbset_report_<pdf>.xlsx` (`rejected` / `review`
  sheets — kept OUT of the import file so the wizard sees no extra sheet). Written by
  Step 5 (also copied to step3 accepted), Step 6, Step 7 and the Step 6 Sheets sync.
- Sheets round-trip: an edited `Exams` / `Number` cell rebuilds `papers` (`qcm_merge`).
- Step 8: matched questions union their papers into the reference `Exams` (conflicting
  number → reference kept, reported in the merge audit).
- UI: "Exam document" block (Auto / Single exam / QCM classé + Source / Session / Year)
  in the Step 2 panel, the interactive autorun and the batch wizard → `EXAM_MODE`,
  `EXAM_SOURCE`, `EXAM_PERIOD`, `EXAM_YEAR`; a typed Session beats header detection,
  never an origin line. Output viewer: "Needs review (N)" toggle on QCM JSON previews.
- Tests: `tests/test_mbset_export.py` (+ the two earlier files) — 74 new tests.

---

## 11. Decisions (updated 2026-11-21)

| # | Question | Answer |
|---|---|---|
| D1 | Year of `2020-2021` | **Start year → 2017 for `2017-2018`, 2020 for `2020-2021`** (confirmed 2026-11-21) |
| D2 | `Partie pratique` | **Neither A nor B: the session + part goes in `Tag`.** `Question N° 02, Partie pratique, Sec 01 de l'année 2017-2018` → `Number = 2`, `Year = 2017`, `Tag` gets `Sec 01 Pratique`. Theory question of the same paper → `Tag` gets `Sec 01`. |
| D3 | Session wording | **Keep the PDF wording**: `Sec 01`, `Sec 02`, `Rattrapage`; pratique part → `<session> Pratique` (`Sec 01 Pratique`, `Rattrapage Pratique`). Written in `Tag`. |
| D4 | `Tag` content | **Source + year + session label + (other free tags)**, e.g. `['Externat Blida', '2017', 'Sec 01 Pratique']`. Never a `N°`. |
| D5 | Create new vs update existing questions | **Import wizard (new questions, no `id`)** — not Smart Import |
| D6 | `Number` column | **`Number` = the ORIGINAL paper number** (`N° 02` → `2`, `QuestionN010` → `10`). For a normal exam, `Number` = printed number. The document position (`29-`, `41-`) stays only in `Num` (review file). |
| D7 | Clinical cases | **Case text copied into `Cas` on EVERY question of the case**, identical string (the wizard groups rows whose `Cas` text is the same). Chain rule in §6.6 below. |

Consequence for the import workbook (§6 "XLSX exports"): per row write `Number`, `Year`,
`Tag` (session label inside), `Cas`; `Exams` empty; one row per paper occurrence.

### 11.1 Open points created by D2

- **O1 — `Period` column: CLOSED.** The official template
  `mbset-question-import-template.xlsx` has no `Period` column. Its columns are:
  `Text, A, B, Correct, C, D, E, F, Year, Number, Exams, Official, Proposed, EXP, Note,
  A_EXP…D_EXP, categoryId, subcategoryId, categoryName, subcategoryName, tagSuggere, Tag,
  Hint, Type, Cas, ModelAnswer, Image, ImagePage, explanationImage, ImageMasks,
  ExplanationImageMasks, SourceFile`. The import workbook uses exactly these columns. The
  session lives in `Tag` (template example: `Externat Tizi Ouzou, EMD 2026, Pratique`).
- **O2 — `Exams` column: CLOSED (2026-11-21, "Way 1").** The import file leaves `Exams`
  EMPTY on every row (a filled `Exams` would override `Number`/`Year`). A question printed in
  several papers is exported as **one row per paper**, each with its own `Number`, `Year`,
  `Tag`. The pipeline does **not** merge duplicates: MBset handles duplicates itself.
  `Exams` may still appear in the review workbook as a read-only summary.
- **O3 — `Sec 01` in `Tag`: CLOSED** (user: not a concern).

### 11.2 Clinical-case chain rule (D7) — replaces the CC part of Step 3

A case = the narrative text + the questions that follow it. Walk the questions in document
order after the narrative; question *k+1* joins the case of question *k* only if **all** hold:

1. same paper: same session label (`Rattrapage`, `Sec 02`, `Sec 01 Pratique`…) **and** same year;
2. `Number(k+1) = Number(k) + 1` — the ORIGINAL number, never the document position
   (`41- 42- 43- 44- 45-` is sequential but `N°25 → N°42` is not);
3. no new narrative / new `Cas clinique` header between them.

The first failing question closes the case and is **not** given the case text.

Example (Rattrapage 2023-2024):

| Doc pos | Origin line | Number | Year | Tag (session) | `Cas` |
|---|---|---|---|---|---|
| 41- | N° 22, Rattrapage 2023-2024 | 22 | 2023 | Rattrapage | case text |
| 42- | N° 23, Rattrapage 2023-2024 | 23 | 2023 | Rattrapage | case text |
| 43- | N° 24, Rattrapage 2023-2024 | 24 | 2023 | Rattrapage | case text |
| 44- | N° 25, Rattrapage 2023-2024 | 25 | 2023 | Rattrapage | case text |
| 45- | N° 42, Sec 02 2024-2025 | 42 | 2024 | Sec 02 | *(empty — paper and number both break)* |

Rules that make it reliable:
- The `Cas` string is copied **byte-identical** (same whitespace, same OCR fixes) on every
  row; one differing character splits the case in two in MBset.
- The LLM CC detector still finds *where* a narrative starts and which question it opens;
  the chain length is decided by this deterministic rule, not by the LLM.
- A missing/unreadable number in the middle (`N> 2`, `N° 401`) → do not guess: keep the
  chain only if the document positions are consecutive AND the paper is the same; flag
  `cas_chain_uncertain`.
- Normal single-paper exam (no origin lines): paper is the same for all, so the rule is
  just "printed numbers consecutive, stop at the next narrative" — same as today.
- Test fixture: the block above (pos 41–45) → exactly 4 rows with `Cas`, row 45 empty.

---

## 12. Evidence from the gyneco PDF (text pages 201–231, 68 origin lines)

**Partie pratique numbers collide with theory numbers inside the SAME paper:**

| Paper | Theory N° | Partie pratique N° |
|---|---|---|
| Sec 01 2017-2018 | 2, 5 | **2**, 4 |
| Sec 01 2021-2022 | 7, 32, 35 | **7** |
| Sec 01 2020-2021 | 1, 25, 40 | 14, 16 |
| Rattrapage 2017-2018 | 2, 34 | 17, 20 |

So `Sec 01 2017-2018 N°2` names two different questions. D2 must make them distinguishable:

- **Option A — separate period**: `Externat Blida · Sec 01 Pratique 2017 · N°2`. Each part is
  its own "paper" in MBset; students filtering by exam see *Sec 01* and *Sec 01 Pratique*
  as two entries. Numbers are never ambiguous.
- **Option B — same period + tag**: `Externat Blida · Sec 01 2017 · N°2` and Tag
  `Partie pratique`. One exam entry for students, but inside it two questions carry N°2;
  the tag is the only difference.

**Same question printed in several papers (must become ONE question with several papers):**

| Question (start) | Papers |
|---|---|
| Une hypertonie utérine … | Rattrapage 2021-2022 N°2 · Sec 01 2021-2022 N°7 · Sec 02 2021-2022 N°8 (all pratique) |
| … corrigé par l'ocytocine (réponses fausses) | Rattrapage 2020-2021 N°19 · Sec 01 2020-2021 N°14 |
| Le thrombus vaginal … | Rattrapage 2020-2021 N°20 · Sec 01 2020-2021 N°16 |

**R-DUP — DROPPED (decision O2, 2026-11-21):** each occurrence stays its own row; MBset
deduplicates on import. Kept below for history only.

~~New requirement R-DUP~~: after Step 2, detect near-identical questions inside the same
document (text + propositions similarity, reuse the Step 8 matcher) and propose merging them
into one row whose `Exams` lists every paper (`… · N°2 | … · N°7 | … · N°8`). Merge only when
the propositions match too (the ocytocine pair differs in "justes/fausses" in other PDFs →
same text but different question). Merges are shown in the review file, never silent.
Fits in Phase 5 next to the Step 8 paper union.
