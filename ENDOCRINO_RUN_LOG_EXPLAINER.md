# Log explainer — Step 3 CC detection on the Endocrinologie run (Externat Alger, 2023)

> Reference: excerpt of `execution_log.md`-style output from a NEW run
> (6 pages, 35 QCMs, strategy `ClinicalCase = CC` on 2026-09-17). This file
> explains each block of that log in plain terms. Vocabulary reference:
> `CC_PRODUCTION_EVIDENCE_DIAGNOSIS_AND_FIX_PLAN.md` §1–2.

---

## 1. The header block

```
STEP 3: METADATA DETECTION (Smart Config)
⚙️  Using Auto-Mode Config: {'Year': 'G', 'Source': 'G', 'Category': 'G', 'ClinicalCase': 'CC'}
```

- This is the **post-step-2 auto-enrich** configuring HOW each metadata field
  is detected:
  - `Year/Source/Category = G` → **Global strategy**: detected ONCE from
    page 1 and stamped onto every QCM (that's the next block: page `[1]` →
    `Year 2023`, `Source Externat Alger`, `Category Endocrinologie` → set
    globally).
  - `ClinicalCase = CC` → **per_group linkage strategy**: clinical-case
    detection walks page by page, attaches `cas` fields, and later chains go
    through the CC Checker for verification. This is the full pipeline
    (linkage ON, unlike `skip`/`S`).

## 2. The per-page CC detection walk

```
📑 Merged file: 6 distinct pages found → processing sequentially (1–6)
```

- The QCM list is a merged `all_qcms.json`, so Step 3 rebuilds the page
  sequence (`page` groups) and processes pages 1→6 in order, **one LLM call
  per page** (the per-page budget contract).

What each line means:

- `🔍 Page N: Detecting CC (x QCMs) → LLM call...`
  → the per-page detection call (`_detect_cc_sequential_page`) is sent with
  that page's OCR text and that page's QCM numbers.
- `📋 CC triggered at Q< n > (CAS CLINIQUE): "<preview>"`
  → the model returned `status: new_case` for that QCM **with a narrative
  (cas_text)**. That QCM becomes the first member of a new case; the
  narrative is stored as `cas = "CAS CLINIQUE\r\n<narrative>"`.
- `↪️ Carry-over to next page: "CAS CLINIQUE" (active)`
  → the case that started on this page did NOT close here (`continues`
  semantics), so its `cas` string is carried forward and attached to later
  pages' QCMs until a status change (`ends_here`/new case). This is
  `carry_over` — an already-ATTACHED running case.
- `↩️ No new CC on page 6 — carry-over active`
  → no fresh `new_case`, but the running case keeps flowing.
- `ℹ️ No Cas Clinique on page N` would mean: nothing new AND nothing running.

Good calls in this run:

- Page 1: `Zhor, 77 ans, diabétique de type II…` — real patient context →
  CAS 1 over Q1–Q5. ✅
- Page 2: `En novembre 2023, elle revient consulter…` — this is actually the
  CONTINUATION of Zhor's case (an evolution paragraph), detected as a new
  case at Q6 rather than a `continues` of CAS 1 → becomes CAS 2 (Q6–Q7).
  🟡 Defensible split, but arguably one case.
- Page 3: `Chez une femme de 40 ans, porteuse d'un panhypopituitarisme…` →
  CAS 3 (Q15–Q17). ✅
- Page 5: three cases — nodule thyroïdien (CAS 4, Q25–26), Madame F.
  Hashimoto (CAS 5, Q27–28)… ✅

## 3. The problems this run still shows (same as the diagnosis plan)

1. **Page 4 — the empty anchor again (G-3):**
   `CC triggered at Q18 … ""` — a `new_case` with an EMPTY cas_text attached
   to Q18. Nothing was linked (see `NO CASE` list: Q18–Q24 all separate), so
   it produced nothing useful — but per OQ-2's decision the correct
   post-fix behavior would be `uncertain` + manual-review flag; here it was
   still silently accepted as an anchor and attached nothing.
2. **Page 5 — a question stem posed as a case (G-4-adjacent/V-2):**
   `CC triggered at Q29: "Le goitre simple se définit par:"` — that is a
   DEFINITION QUESTION stem, not a patient-situation description (no
   symptoms/signs/history/exam/test results). It forked CAS 6 (Q29–Q30).
   Under the decided OQ-1/OQ-5 rules this text FAILS the clinical-context
   definition gate → would have been refused (no CAS 6).
3. **Page 5 carry-over interplay:** after the three page-5 executions,
   carry-over stayed "active" into page 6, where nothing claimed it
   (`No new CC on page 6`) — page 6's QCMs all land in `NO CASE`. If the
   running case truly continues on page 6 is exactly the "two runs' worth
   of ambiguity" the `ends_here` boundary check is for (one queued
   transition here: `[CC-STATE] 1 ends_here transition(s) queued`).

Also note the page numbering collision in the summary: pages are echoed per
QCM (`Page 2 → Q6, Q7`), QCM numbers are GLOBAL across the doc, and the
`NO CASE § Page 6 → Q26, Q27…` line lists Q-numbers that were ALSO listed
as "Page 5" cases — that is because Q26–Q30 belong to page 6 but their
detection happened inside page 5's call… wait, no: the summary's "Page" is
the QCM's own recorded page; the same Q-numbers appear under both lists only
because Page 5's call emitted cases whose members were recorded with page 5,
and `NO CASE` then lists the OTHER QCMs of page 6. Read those two blocks as
mutually exclusive per QCM number, not additive.

## 4. The checker section (last visible block)

```
CLINICAL CASE CHECKER (Phase 1 — per-QCM cascade verification)
[CC-CHECK] ▶ Starting: 6 clinical case chain(s) over 16 QCMs — parallel (max 5), early_stop=on
```

- After detection + the `ends_here` boundary stage, EACH chain (CAS 1…6) is
  verified question by question INDEPENDENTLY (parallel, max 5 at a time):
  "does this QCM actually depend on this case's missing patient facts?"
- Verdicts visible in the excerpt:
  - `✅ belongs (0.90) — keeps the clinical case` → the link is confirmed
    and stays.
  - `❓ provisional NO — link kept pending next verdict (§6.2)` → first NO
    is provisional: the link is kept until the NEXT question's verdict
  - (not shown in this excerpt, but per the shipped policy: a second NO
    closes the chain — remaining QCMs unlinked without more calls.)
- `sk-or-v1****6924` is a masked API-key log line (key never printed).

## 4b. The checker END-GAME (second excerpt, decoded chain by chain)

This is the tail of the same checker pass. The 6 chains were running in
parallel, so **their log lines interleave** — read each line's chain label
(`[CAS n]`) first, then its QCM step (`chain n — QCM x/y`).

Chain-by-chain outcome from the excerpt:

| Chain | QCMs | Progression shown | Final status |
|---|---|---|---|
| CAS 1 (Zhor) Q1–Q5 | 5 | Q1 ✅, Q2 ✅, Q3 ❓ provisional NO, then **two consecutive NOs → closes before Q3** | 2 kept (Q1,Q2), 3 unlinked (Q3,Q4,Q5) — early close saved 1 call |
| CAS 2 (novembre 2023) Q6–Q7 | 2 | Q6 ✅, Q7 ❓ provisional NO → **end of chain, pending NO confirmed** | Q7 link REMOVED (that QCM only) — 1 kept, 1 unlinked |
| CAS 3 (femme 40 ans) Q15–Q17 | 3 | consecutive NOs → **closes before Q15** (Q15's NO is the 2nd of two NOs; Q16's ✅ landed but under the wrong chain-label print), remaining QCMs unlinked WITHOUT LLM calls | 0 kept, 3 unlinked — early close saved 1 call |
| CAS 4 (nodule) Q25–Q26 | 2 | Q25 ✅, Q26 ❓ → **pending NO confirmed at end of chain** | Q26 link REMOVED (that QCM only) — 1 kept, 1 unlinked |
| CAS 5 (Mme F.) Q27–Q28 | 2 | Q27 ✅, Q28 ❓ → **pending NO confirmed** | Q28 link removed — 1 kept, 1 unlinked |
| CAS 6 ("goitre se définit") Q29–Q30 | 2 | Q29 ❓ provisional NO; Q30 ❓ → second NO → closes | **0 kept — the whole fork unlinked** (detection had already mis-born this chain), 2 early-close savings |

Key mechanics visible here:

- **`❌ End of chain: pending NO confirmed — Q< n > link removed (that QCM
  only)`** — this is the end-of-chain name-noise trap: the line prints AFTER
  a `[CC-CHECK] [CAS m]` header from a DIFFERENT interleaving chain, so the
  Q-number named ("Q26") belongs to the chain whose narrative began the
  preceding metric line — the three "pending NO confirmed" lines resolve
  Q26 (CAS 4), Q7 (CAS 2) and Q28 (CAS 5) respectively. Blocks of 2 QCMs:
  a single NO anywhere is end-of-chain because there is no "next verdict"
  to wait for — the §6.2 provisional NO is immediately confirmed and that
  ONE qcm is unlinked.
- **`⛔ Two consecutive NOs — case closed before Q< n >; N remaining QCM(s)
  unlinked without LLM calls`** — the early_stop rule: the first NO that is
  immediately followed by another NO closes the WHOLE chain; all QCMs after
  the NOs are released WITHOUT any more verification calls (the
  "1 LLM call(s) saved" lines at the end of the block quantify the saving).
- **Always separately print the chain's own `[CAS n] ✅ Done — X kept,
  Y unlinked` line** — that is the authoritative per-chain final state, NOT
  the interleaving noise around it.
- **`cas_scrub` stage:**
  `[CAS-SCRUB] Q25 p.5 — narrative removed from 'text' (28 chars kept)` →
  This is the reverse of the split stage: the Q25 QCM's own Text was
  carrying a copy of the case narrative — scrubbed OF the narrative, leaving
  only the (short) residual 28 chars of the question stem ("texte"). Keeps
  questions clean, narrative only in `Cas`.
  `with_cas=5 scrubbed=1` → 5 QCMs ended with a Cas, 1 piece of text was
  scrubbed.

## 4c. The final summary + build (what to read off it)

```
📊 CLINICAL CASE VERIFICATION & EXTRACTION SUMMARY
  Total QCMs extracted:    35
  Total Clinical Cases:    4
  QCMs with Case:          5
  QCMs without Case:       30
```

- 35 QCMs total; after verification **4 cases survive** (6 detected − 2
  whose members all got unlinked), but only **5 Q-CMs keep a `Cas`** (Q1,
  Q2, Q6, Q25, Q27 shown in the breakdown): 11 links proved wrong and were
  removed; 3 chains closed early on the two-NO rule.
- `Unlinked (wrong links): 11` — the count of reverted links. In this run
  the checker UNLINKED MORE than it kept (5 kept vs 11 unlinked) — again the
  "detect then remove" pattern, same class of failure as the cardio run.
- Detection layer named the shape, the checker regretted it:
  - CAS 6 ("Le goitre simple se définit par:") died 2/2 — a question stem
    was never a case (the exact V-2/OQ-1 gate target).
  - CAS 3 died 3/3 (empty-ish/stem-shaped anchor), leaving Q15–Q17 bare.
  - CAS 1 was split-checked and half-saved (Q1–Q2 ✅).
- `Cas text scrubbed: 1` matches the single Q25 scrub.

Then the **build tail** is mechanical (no intelligence left here):

1. `STEP 4 / STEP 5 (merged)` → maps the 35 finished QCMs onto the chosen
   xlsx template and writes
   `/app/output/.../step5_json/merged_qcms.json` +
   `35_qcms_examen_endocrino_section_2_avec_CT.xlsx`.
2. Copies of both surfaces are pushed into `step3_metadata/accepted/` and
   copied BACK into `step2_qcm/accepted/` (`copyback` — so the newest
   artifacts sit in the same folder the UI reads).
3. `[CASCADE-TRACE] stage=…event=END` lines are timing audit markers per
   stage, not decisions.

## 5. One-line reading template for future runs

> Header = strategies per field. Per page = 1 detection call; lines below it
> = what that call concluded (`new_case` anchors / carry-over propagation).
> Summary block = the 6 cases that detection chose to build. Checker block =
> independent re-verification of each link it formed. Checker tail = which
> links it kept, which it unlinked, which chains closed early. cas_scrub =
> dedup of narrative text out of `text`. Build tail = mechanical template
> mapping + xlsx, no decisions.

Two things to keep watching in future logs (per the diagnosis plan):
`CC triggered at Q< n > (CAS CLINIQUE): ""` (empty cas_text anchors) and any
trigger whose text is a question stem / definition ("…se définit par:",
"Vous évoquez:") — both are the failure shapes the planned D-phases close,
and this run's checker summary is a direct preview of what that fix is
meant to remove.

## 6. The decisive checker rule visible in this excerpt (end-of-chain trap)

When a chain has only 2 QCMs, "the NO is immediately end-of-chain", so §6.2
provisional + confirmation collapse into one step, and the log prints the
`End of chain: pending NO confirmed` line WHILE the interleaved header of a
NEIGHBORING chain is also mid-line — the Q-number in that suffix is the
truth (the line's own chain context) and MUST be matched against the
preceding `chain n` label, not against the `[CAS m]` header that happened to
be the line the printer encountered last. Three "pending NO confirmed" lines
in this excerpt resolve to CAS 4/Q26, CAS 2/Q7 and CAS 5/Q28 — all three
correctly unlink ONLY their own member, per the "that QCM only" wording.
