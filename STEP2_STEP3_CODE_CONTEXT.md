# STEP 2 + STEP 3 — Code excerpts for re-engineering clinical-case extraction

> Context pack: give this file to Claude so it can re-engineer how clinical
> cases ("Cas Clinique") are extracted/linked in ALL situations.
> Explanation of behavior lives in `STEP2_STEP3_EXPLAINER.md`.
> All excerpts trimmed to the parts that define CURRENT behavior.

---

## 1. File map (what owns what)

| File | Role |
|---|---|
| `modules/step2_qcm_extract_batch.py` | Per-chunk QCM extraction; `clinical_case_hint` emission |
| `modules/post_step2_metadata.py` | The merged cascade: hint → cas-split → Step 3 → CC checker → build |
| `modules/step3_metadata.py` | Metadata + CC detection (`_detect_cc_sequential_page`) + propagation |
| `modules/clinical_case_checker.py` | Phase-1 verification (chains, early-stop, §7 re-check) |
| `modules/cas_text_split.py` | Removes narrative from question `text` |
| `modules/hint_detector.py` | Parses `A(1+2+3)` trailing lines into `hint` arrays |
| Env knobs | STEP3_MODEL / STEP3_FALLBACK_MODEL / STEP3_MAX_TOKENS / STEP3_MAX_INPUT_CHARS(24000) / CC_CHECKER_MODEL(mercury) / CC_CHECKER_FALLBACK_MODEL / CC_CHECKER_MAX_TOKENS(500) / CC_CHECKER_MAX_PARALLEL(5) / CC_CHECKER_EARLY_STOP(1) |

---

## 2. CASCADE ORDER — `post_step2_metadata.py`

```python
DEFAULT_STEP3_CONFIG = {
    "fields": {
        "year":          {"strategy": "per_qcm",  "value": None},
        "source":        {"strategy": "skip",      "value": "Externat"},
        "category":      {"strategy": "global",    "value": None},
        "clinical_case": {"strategy": "per_group", "value": None},
    },
    "global_pages": "1",
}

def _clinical_case_enabled(step3_config):
    # UI shape {"fields": {"clinical_case": {"strategy": "per_group"}}}
    # or autorun shape {"config": {"ClinicalCase": "CC"}}; default = per_group

def run_post_step2_metadata(tracker, context, user_id, project, step3_config=None, cancel_check=None):
    # order:
    #  1. guard: no accepted Step 2 QCMs -> {"status": "no_qcms"}
    #  2. hint        = run_hint_detection(context)          # pure python
    #  3. cas_split   = run_cas_text_split(context)          # pure python
    #  4. Step 3 skip iff _step3_covers_current_step2(context)  # Q8 fast-path: uid sets equal
    #     else: Step3Metadata(tracker, context).run(auto_mode=True,
    #               config=fields, global_pages=gp_list, cancel_check=cancel_check)
    #  5. if _clinical_case_enabled(step3_config):
    #         cc_check = run_clinical_case_checker(tracker, context)   # soft-fail
    #  6. run_post_step3_build(tracker, context)                # Step 4+5 auto-build
```

Config normalization inside `Step3Metadata.run` (auto-mode):
```python
# {"clinical_case": {"strategy": "per_group"}} -> "CC",
# {"strategy": "global"} -> "G"; missing -> "S"; default ClinicalCase = "S"
```

---

## 3. STEP 2 — hint emission in the extraction prompt — `step2_qcm_extract_batch.py`

```python
cc_hint_rule = (
    "- If a 'Cas Clinique' (clinical case) header and patient narrative appears immediately "
    "BEFORE this question (not another QCM, but a patient story block), add a field "
    "\"clinical_case_hint\" with the label exactly as written (e.g. \"CAS CLINIQUE 1\"). "
    "Otherwise omit this field entirely."
)

# in run(): self._step2_promoted_to_fallback / _step2_primary_fail_streak
# loop mode default page_range "1-1-1" -> _run_loop_mode(txt_files, chunk_size, ...)
# per chunk: full_text = self._concatenate_pages(chunk)  # "=== PAGE X ===\n<text>"
#            qcms = self._extract_all_qcms_batch(full_text, start_p, end_p, config,
#                                                prev_page_qcm_numbers=prev_page_qcm_numbers)
#            qcms = self._stamp_pages(qcms, chunk)          # clamp page to chunk range
#            qcms = self._apply_incomplete_fix(qcms, txt_files, config, cancel_check)
#            self._save_batch_results_accumulate(qcms)      # uid-keyed merge into all_qcms.json

# uid assignment:
qcm.setdefault('uid', f"{qcm.get('page', 0)}_{qcm.get('number', 0)}_{i}")   # i = position in batch
```

---

## 4. STEP 3 — per-page sequential CC detection — `step3_metadata.py`

```python
def _detect_cc_sequential_page(self, page_text: str, qcm_numbers: List[int]) -> Dict:
    # returns { qcm_number: "LABEL\r\nNarrative" } for trigger QCMs, None for others
    nums_str = ", ".join(str(n) for n in qcm_numbers)

    prompt = f"""You are analyzing a French medical exam page for Cas Clinique (clinical case) detection.

TASK: For each QCM number listed below, decide if it is the VERY FIRST question of a NEW clinical case narrative introduced on this page.

CRITICAL RULES:
1. Return a JSON array with EXACTLY ONE entry per QCM number listed below — no more, no less.
2. "cas_text" must be non-null ONLY for the very first question of each new clinical case.
3. All other questions of the SAME case → "cas_text": null  (do NOT repeat the narrative)
4. Questions with no clinical case → "cas_text": null
5. "cas_text" must contain ONLY the patient story (everything between the "CAS CLINIQUE"
   header and the first numbered question). Do NOT include the case title.
6. "cas_label" must be the exact label as written in the text (e.g. "CAS CLINIQUE 1").
   Use "CAS CLINIQUE" if no label exists.

QCM NUMBERS ON THIS PAGE: [{nums_str}]

PAGE TEXT:
{page_text[:max_input_chars]}"""
    # parse: strip fences, find first '[...]', fix trailing commas, json.loads
    # convert -> result[num] = f"{cas_label}\r\n{cas_text}" if cas_text else None
    # models: primary os.getenv("STEP3_MODEL", "qwen/qwen3.6-plus-preview:free")
    #         fallback os.getenv("STEP3_FALLBACK_MODEL", "google/gemini-2.0-flash-lite-001")
```

### 4.1 Deterministic propagation + cross-page carry-over

```python
def _propagate_cas_clinique(self, qcms, llm_results, carry_over=None) -> tuple:
    current_cas = carry_over                      # inherited from previous page
    for qcm in qcms:
        num = qcm.get("number") or qcm.get("Num")
        llm_cas = llm_results.get(num) if num is not None else None
        if llm_cas is not None:
            current_cas = llm_cas                  # new trigger replaces running case
        if current_cas is not None:
            qcm["cas"] = current_cas               # applied until next trigger
    return qcms, current_cas                       # returns new carry-over

# In _process_qcms (merged path): pages grouped from QCM 'page' field, sorted,
# one _detect_cc_sequential_page call per page; carry-over persists across pages.
# No page text -> carry-over applied to all QCMs of the page without LLM call.
# Strategy "G": one _detect_clinical_cases(page1_text) call; first case -> every QCM.
```

### 4.2 Dormant document-level variant (page+number pairs)

```python
def _detect_clinical_cases_document(self, full_doc_text, qcm_pairs) -> list:
    # one call, whole doc; returns [{"label", "text", "qcm_pairs": [{"page":N,"number":M}]}]
    # key rules in prompt:
    #   - numbers can REPEAT across sections -> always include page number
    #   - question belongs to case AFTER its narrative until the next CAS header
    #   - page breaks do not break membership
    #   - questions BEFORE the narrative never belong; between two headers ->
    #     belongs to the first one
```

---

## 5. PHASE-1 CC CHECKER — verification policy — `clinical_case_checker.py`

```python
VERIFICATION_FILENAME = "clinical_case_verification.json"

def _build_chains(entries):     # entries = [(file_path, qcm)] in document order
    # consecutive QCMs sharing same non-null cas text -> one chain
    # (two identical case runs separated by anything = two chains)

def _verification_prompt(cas, qcm):
    label, narrative = _split_cas(cas)
    return f"""You verify whether a QCM really belongs to a clinical case.

DEFINITION — apply it exactly:
A QCM belongs to the clinical case only when the information contained in that
case is necessary or materially useful to answer the QCM correctly. If the QCM
can be answered correctly without using the case-specific information, it does
NOT belong — even if it deals with the same medical subject.

CLINICAL CASE — {label}:
{narrative}

QUESTION:
{question}

PROPOSITIONS:
{propositions}

Reply with ONE line of JSON only: {{"applies": true, "confidence": 0.9}}"""

# _recheck_prompt(cas, suspicious_qcm, next_qcm):  # spec §7 — only used when
#   a provisional NO is followed by a YES; decides ONLY for the suspicious QCM,
#   showing the confirmed YES as context evidence.

async def _verify_chain_async(chain_index, chain, entries, client, tracker,
                              primary_model, fallback_model, max_tokens, early_stop):
    consecutive_no = 0; suspicious = None; closed_early = False
    for pos, entry_idx in enumerate(chain["items"]):
        verdict = await _verify_one_async(client, tracker, qcm, chain["cas"], ...)
        if verdict["status"] != "ok":
            unresolved; link KEPT; counter untouched; continue
        if verdict["applies"]:
            keep; consecutive_no = 0
            if suspicious is not None and early_stop:      # §7 re-check
                recheck = await _ask_verdict_async(... _recheck_prompt(...))
                if recheck ok and not applies: unlink suspicious QCM ONLY
                elif recheck ok: link kept
                else: downgrade to unresolved (link kept)
        else:  # applies == false
            if not early_stop:
                unlink immediately                                   # legacy
            elif consecutive_no >= 1 and suspicious is not None:
                closed_early = True                                  # TWO NOs
                unlink suspicious first NO + this QCM
                remaining tail of chain: unlinked_by_boundary, ZERO LLM calls
                break
            else:
                consecutive_no = 1; provisional; link kept
    if suspicious pending at chain end: unlink that QCM only
    # unlink implementation:
    for d in decisions:
        if d.get("corrected"):
            entries[d["entry_idx"]][1].pop("cas", None)   # corrections applied
            # caller writes files back after asyncio.gather
```

Parallelism + idempotency:
```python
semaphore = asyncio.Semaphore(max(1, int(c_cc_max_parallel)))   # default 5
chains run concurrently BUT QCMs sequential within a chain
audit file stores decisions + "uid_set"; if equal to current uid set -> skip run
```

---

## 6. CAS TEXT SPLIT — dedupe narrative vs question — `cas_text_split.py`

```python
MIN_NARRATIVE_LEN = 20

def split_cas_from_text(text, cas) -> Tuple[new_text, removed_flag]:
    # 1. exact substring removal of the narrative from text
    # 2. whitespace-normalized fallback: collapse ws in both, locate span,
    #    map span back to original indices, strip it (format preserved outside)
    # 3. then drop a surviving standalone label line ("CAS CLINIQUE 1")
    # never scrub if narrative missing/short (<20 ch)/removal would empty text
```

---

## 7. Invariants any re-engineering MUST preserve

1. `cas` string format: `"{label}\r\n{narrative}"` (split by `_split_cas`).
2. QCM identity = **uid** (`page_number_position`); CC numbers repeat across
   pages/sections — never key APIs on bare question number globally.
3. Cross-page cases: carry-over state machine (trigger on page N, questions on
   pages N..M) must keep working.
4. Failure policy: unresolved/technical failure ⇒ keep the link; two
   consecutive verified NOs ⇒ close the chain at the QCM before the first NO.
5. Idempotency: uid-set equality gates (Step 3 re-run + checker re-run).
6. Narrative lives ONLY in the Cas column — `text` must never contain it
   (cas_text_split), and must never be mangled on uncertain matches.
7. Stages are soft-fail; the cascade order is
   hint → cas_split → step3 → cc_checker → build(any error must not block the
   next stage beyond the current contract).
