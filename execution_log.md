📦 Chunk 7/8: pages 7–7  (1 pages)
[08:59:19]
============================================================
[08:59:19]
   📌 [SEQ-CONTEXT] Previous chunk QCM numbers: [33, 34, 35, 36, 37, 38] → next expected #39
[08:59:19]
[API] Trying google/gemini-2.5-flash-lite...  (attempt 1/3)
[08:59:22]
[OK] Used google/gemini-2.5-flash-lite ($0.0004)
[08:59:22]
[SUCCESS] Extracted 2 QCMs
[08:59:22]
  Q39: Votre conduite pratique en urgence consiste à : (c... (5 props)
[08:59:22]
  Q40: Un souffle cardique chez l'enfant (cochez les répo... (5 props)
[08:59:22]

[INTEGRITY] Dynamic proposition threshold for this batch: 5
[08:59:22]
[INTEGRITY] ✅ All QCMs have complete propositions.
[08:59:22]
[MERGE] Found 38 existing QCMs in all_qcms.json
[08:59:22]
[SAVE] Saved to: /app/output/admin/cardio_sec_1/step2_qcm/accepted/all_qcms.json
[08:59:22]
💾 Total QCMs in file: 40  (+2 new  |  0 updated)
[08:59:22]

============================================================
[08:59:22]
📦 Chunk 8/8: pages 8–8  (1 pages)
[08:59:22]
============================================================
[08:59:22]
   📌 [SEQ-CONTEXT] Previous chunk QCM numbers: [39, 40] → next expected #41
[08:59:22]
[API] Trying google/gemini-2.5-flash-lite...  (attempt 1/3)
[08:59:30]
[OK] Used google/gemini-2.5-flash-lite ($0.0022)
[08:59:30]
[SUCCESS] Extracted 40 QCMs
[08:59:30]
  Q41: Cocher les cases au stylo noir avec un astérisque ... (5 props)
[08:59:30]
  Q42: ... (5 props)
[08:59:30]
  Q43: ... (5 props)
[08:59:30]
  ... and 37 more
[08:59:30]

[INTEGRITY] Dynamic proposition threshold for this batch: 5
[08:59:30]
[INTEGRITY] ✅ All QCMs have complete propositions.
[08:59:30]
[MERGE] Found 40 existing QCMs in all_qcms.json
[08:59:30]
[SAVE] Saved to: /app/output/admin/cardio_sec_1/step2_qcm/accepted/all_qcms.json
[08:59:30]
💾 Total QCMs in file: 80  (+40 new  |  0 updated)
[08:59:30]

✅ AUTO-LOOP COMPLETE — All 8 chunks processed.
[08:59:30]

✅ Step 2 Complete. Total new/updated QCMs in this loop run: 80
[08:59:30]
✅ Step 2 completed successfully.
[08:59:30]

============================================================
[08:59:30]
POST-STEP-2 AUTO-ENRICH  (Step 3 metadata + Step 4-5 build)
[08:59:30]
============================================================
[08:59:30]
[CASCADE-TRACE] stage=cascade event=START
[08:59:30]
[CASCADE-TRACE] stage=guard event=START
[08:59:30]
[CASCADE-TRACE] stage=guard event=END elapsed_ms=0 detail=accepted_qcms_present
[08:59:30]
[CASCADE-TRACE] stage=hint event=START
[08:59:30]

════════════════════════════════════════════════════════════
[08:59:30]
HINT DETECTION  (Phase 3 — always-on, deterministic)
[08:59:30]
════════════════════════════════════════════════════════════
[08:59:30]
[HINT] 💾 Hint fields written → all_qcms.json
[08:59:30]

════════════════════════════════════════════════════════════
[08:59:30]
📊 HINT DETECTION SUMMARY
[08:59:30]
════════════════════════════════════════════════════════════
[08:59:30]
  QCMs scanned:       80
[08:59:30]
  QCMs with hints:    0
[08:59:30]
  Combos extracted:   0
[08:59:30]
  Fields scrubbed:    0
[08:59:30]
════════════════════════════════════════════════════════════
[08:59:30]
[CASCADE-TRACE] stage=hint event=END elapsed_ms=6 detail=status=ok
[08:59:30]
[CASCADE-TRACE] stage=cas_split event=START
[08:59:30]

════════════════════════════════════════════════════════════
[08:59:30]
CAS COLUMN SPLIT  (Phase 4 — case text out of question text)
[08:59:30]
════════════════════════════════════════════════════════════
[08:59:30]

════════════════════════════════════════════════════════════
[08:59:30]
📊 CAS SPLIT SUMMARY
[08:59:30]
════════════════════════════════════════════════════════════
[08:59:30]
  QCMs scanned:       80
[08:59:30]
  QCMs carrying cas:  0
[08:59:30]
  Texts scrubbed:     0
[08:59:30]
════════════════════════════════════════════════════════════
[08:59:30]
[CASCADE-TRACE] stage=cas_split event=END elapsed_ms=2 detail=status=ok
[08:59:30]
[AUTO-ENRICH] Running Step 3 (metadata) — fields=['year', 'source', 'category', 'clinical_case'], global_pages=[1]
[08:59:30]
[CASCADE-TRACE] stage=step3 event=START detail=llm_run fields=['year', 'source', 'category', 'clinical_case'] global_pages=[1]
[08:59:30]
[OpenRouterClient] Loaded API Key: sk-or-v1****6924
[08:59:30]
[OpenRouterClient] Loaded API Key: sk-or-v1****6924
[08:59:30]

============================================================
[08:59:30]
STEP 3: METADATA DETECTION (Smart Config)
[08:59:30]
============================================================
[08:59:30]

⚙️  Using Auto-Mode Config: {'Year': 'G', 'Source': 'G', 'Category': 'G', 'ClinicalCase': 'CC'}
[08:59:30]

⚙️  Strategy: {'Year': 'G', 'Source': 'G', 'Category': 'G', 'ClinicalCase': 'CC'}
[08:59:30]

🔍 Scanning for Global/AI Metadata...
[08:59:30]
   Extracting from pages: [1]
[08:59:31]

--- Detected Metadata ---
[08:59:31]
  Year: 2025
[08:59:31]
  Source: Externat Tlemcen
[08:59:31]
  Category: Cardiologie
[08:59:31]
   Global Values set:
[08:59:31]
{'Year': '2025', 'Source': 'Externat Tlemcen', 'Category': 'Cardiologie'}
[08:59:31]

🚀 Processing 1 file batches with Cas Clinique detection [strategy=CC]...
[08:59:31]
   Batch 1/1: Applying metadata...
[08:59:31]
   📑 Merged file: 8 distinct pages found → 
processing sequentially (1–8)
[08:59:31]
      🔍 Page 1: Detecting CC (6 QCMs) → LLM call...
[08:59:33]
         📋 CC triggered at Q1 (CAS CLINIQUE): ""
[08:59:33]
         📋 CC triggered at Q4 (CAS CLINIQUE): "HTA
38
30"
[08:59:33]
         ↪️  Carry-over to next page: "CAS CLINIQUE" (active)
[08:59:33]
      🔍 Page 2: Detecting CC (5 QCMs) → LLM call...
[08:59:35]
         📋 CC triggered at Q9 (CAS CLINIQUE): "Un patient âgé de 75 ans, sans antécédents particuliers présente des palpitation..."
[08:59:35]
         ↪️  Carry-over to next page: "CAS CLINIQUE" (active)
[08:59:35]
      🔍 Page 3: Detecting CC (7 QCMs) → LLM call...
[08:59:37]
         📋 CC triggered at Q12 (CAS CLINIQUE): ""
[08:59:37]
         📋 CC triggered at Q14 (CAS CLINIQUE): ""
[08:59:37]
         📋 CC triggered at Q16 (CAS CLINIQUE): ""
[08:59:37]
      🔍 Page 4: Detecting CC (7 QCMs) → LLM call...
[08:59:39]
         📋 CC triggered at Q22 (CAS CLINIQUE): "Parmi les causes de syncope au cours de la cardiomyopathie hypertrophique, on pe..."
[08:59:39]
         📋 CC triggered at Q25 (CAS CLINIQUE): "Concernant le syndrome coronaire aigu sans sus décalage de ST : (cochez la répon..."
[08:59:39]
         ↪️  Carry-over to next page: "CAS CLINIQUE" (active)
[08:59:39]
      🔍 Page 5: Detecting CC (7 QCMs) → LLM call...
[08:59:41]
         ↩️  No new CC on page 5 — carry-over active.
[08:59:41]
      🔍 Page 6: Detecting CC (6 QCMs) → LLM call...
[08:59:43]
         📋 CC triggered at Q38 (CAS CLINIQUE): "Réveillé en pleine nuit par une douleur méso cardiaque intense, Mr MD agé de 54 ..."
[08:59:43]
         ↪️  Carry-over to next page: "CAS CLINIQUE" (active)
[08:59:43]
      🔍 Page 7: Detecting CC (2 QCMs) → LLM call...
[08:59:45]
         📋 CC triggered at Q39 (CAS CLINIQUE): "Vous évoquez: (cochez la réponse juste)
a- Une ischémie sous épicardique dans le..."
[08:59:45]
      🔍 Page 8: Detecting CC (40 QCMs) → LLM call...
[08:59:48]
         ℹ️  No Cas Clinique on page 8.
[08:59:48]

════════════════════════════════════════════════════════════
[08:59:48]
📊 CAS CLINIQUE SUMMARY
[08:59:48]
════════════════════════════════════════════════════════════
[08:59:48]

  [CAS 1] CAS CLINIQUE
[08:59:48]
  ├─ Narrative: "HTA 38 30"
[08:59:48]
  ├─ Total QCMs linked: 3
[08:59:48]
  └─ Breakdown by page:
[08:59:48]
       Page 1 → Q4, Q5, Q6
[08:59:48]

  [CAS 2] CAS CLINIQUE
[08:59:48]
  ├─ Narrative: "Un patient âgé de 75 ans, sans antécédents particuliers présente des palpitation..."
[08:59:48]
  ├─ Total QCMs linked: 3
[08:59:48]
  └─ Breakdown by page:
[08:59:48]
       Page 2 → Q9, Q10, Q11
[08:59:48]

  [CAS 3] CAS CLINIQUE
[08:59:48]
  ├─ Narrative: "Parmi les causes de syncope au cours de la cardiomyopathie hypertrophique, on pe..."
[08:59:48]
  ├─ Total QCMs linked: 3
[08:59:48]
  └─ Breakdown by page:
[08:59:48]
       Page 4 → Q22, Q23, Q24
[08:59:48]

  [CAS 4] CAS CLINIQUE
[08:59:48]
  ├─ Narrative: "Concernant le syndrome coronaire aigu sans sus décalage de ST : (cochez la répon..."
[08:59:48]
  ├─ Total QCMs linked: 1
[08:59:48]
  └─ Breakdown by page:
[08:59:48]
       Page 4 → Q25
[08:59:48]

  [CAS 5] CAS CLINIQUE
[08:59:48]
  ├─ Narrative: "Réveillé en pleine nuit par une douleur méso cardiaque intense, Mr MD agé de 54 ..."
[08:59:48]
  ├─ Total QCMs linked: 1
[08:59:48]
  └─ Breakdown by page:
[08:59:48]
       Page 6 → Q38
[08:59:48]

  [CAS 6] CAS CLINIQUE
[08:59:48]
  ├─ Narrative: "Vous évoquez: (cochez la réponse juste) a- Une ischémie sous épicardique dans le..."
[08:59:48]
  ├─ Total QCMs linked: 1
[08:59:48]
  └─ Breakdown by page:
[08:59:48]
       Page 7 → Q39
[08:59:48]

  [NO CASE] QCMs with no clinical case:
[08:59:48]
  └─ Page 1 → Q1, Q2, Q3
[08:59:48]
  └─ Page 2 → Q7, Q8
[08:59:48]
  └─ Page 3 → Q12, Q13, Q14, Q15, Q16, Q17, Q18
[08:59:48]
  └─ Page 4 → Q19, Q20, Q21
[08:59:48]
  └─ Page 5 → Q26, Q27, Q28, Q29, Q30, Q31, Q32
[08:59:48]
  └─ Page 6 → Q33, Q34, Q35, Q36, Q37
[08:59:48]
  └─ Page 7 → Q40
[08:59:48]
  └─ Page 8 → Q41, Q42, Q43, Q44, Q45, Q46, Q47, Q48, Q49, Q50, Q51, Q52, Q53, Q54, Q55, Q56, Q57, Q58, Q59, Q60, Q61, Q62, Q63, Q64, Q65, Q66, Q67, Q68, Q69, Q70, Q71, Q72, Q73, Q74, Q75, Q76, Q77, Q78, Q79, Q80
[08:59:48]

  ──────────────────────────────────────────────────────
[08:59:48]
  Total: 6 clinical case(s) | 12 QCMs linked | 68 QCMs standalone
[08:59:48]
════════════════════════════════════════════════════════════
[08:59:48]
[CC-STATE] 1 ends_here transition(s) queued for the boundary check
[08:59:48]
[CASCADE-TRACE] stage=step3 event=END elapsed_ms=18874 detail=status=done
[08:59:48]
[CASCADE-TRACE] stage=boundary event=START
[08:59:48]
[OpenRouterClient] Loaded API Key: sk-or-v1****6924
[08:59:50]
[CC-CHECK] ⚠️ Verification call failed (google/gemini-2.5-flash-lite): invalid JSON verdict
[08:59:54]
[CC-CHECK] ⚠️ Verification call failed (nvidia/nemotron-3.5-lightning): invalid JSON verdict
[08:59:54]
[CC-BOUNDARY] 💾 written → all_qcms.json
[08:59:54]
[CC-BOUNDARY] 💾 audit → cc_boundary_checks.json
[08:59:54]
[CASCADE-TRACE] stage=boundary event=END elapsed_ms=5376 detail=status=ok
[08:59:54]
[AUTO-ENRICH] Clinical Case Checker (per_group) — verification pass...
[08:59:54]
[CASCADE-TRACE] stage=checker event=START
[08:59:54]

════════════════════════════════════════════════════════════
[08:59:54]
CLINICAL CASE CHECKER  (Phase 1 — per-QCM cascade verification)
[08:59:54]
════════════════════════════════════════════════════════════
[08:59:54]
[CC-CHECK] Model: google/gemini-2.5-flash-lite (fallback: nvidia/nemotron-3.5-lightning)
[08:59:54]
[OpenRouterClient] Loaded API Key: sk-or-v1****6924
[08:59:54]
[CC-CHECK] ▶ Starting: 6 clinical case chain(s) over 12 QCMs — parallel (max 5), early_stop=on
[08:59:54]
[CC-CHECK] Parallel verification: 6 chain(s), max 5 concurrent, early_stop=on
[08:59:54]

  [CC-CHECK] [CAS 1] CAS CLINIQUE — 3 QCM(s) (Q4 p.1 → Q6 p.1)
[08:59:54]
  [CC-CHECK]   Case: "HTA 38 30"
[08:59:54]
[CC-CHECK] Verifying chain 1 — QCM 1/3 (Q4 p.1) ...
[08:59:54]

  [CC-CHECK] [CAS 2] CAS CLINIQUE — 3 QCM(s) (Q9 p.2 → Q11 p.2)
[08:59:54]
  [CC-CHECK]   Case: "Un patient âgé de 75 ans, sans antécédents particuliers présente des p..."
[08:59:54]
[CC-CHECK] Verifying chain 2 — QCM 1/3 (Q9 p.2) ...
[08:59:54]

  [CC-CHECK] [CAS 3] CAS CLINIQUE — 3 QCM(s) (Q22 p.4 → Q24 p.4)
[08:59:54]
  [CC-CHECK]   Case: "Parmi les causes de syncope au cours de la cardiomyopathie hypertrophi..."
[08:59:54]
[CC-CHECK] Verifying chain 3 — QCM 1/3 (Q22 p.4) ...
[08:59:54]

  [CC-CHECK] [CAS 4] CAS CLINIQUE — 1 QCM(s) (Q25 p.4 → Q25 p.4)
[08:59:54]
  [CC-CHECK]   Case: "Concernant le syndrome coronaire aigu sans sus décalage de ST : (coche..."
[08:59:54]
[CC-CHECK] Verifying chain 4 — QCM 1/1 (Q25 p.4) ...
[08:59:54]

  [CC-CHECK] [CAS 5] CAS CLINIQUE — 1 QCM(s) (Q38 p.6 → Q38 p.6)
[08:59:54]
  [CC-CHECK]   Case: "Réveillé en pleine nuit par une douleur méso cardiaque intense, Mr MD ..."
[08:59:54]
[CC-CHECK] Verifying chain 5 — QCM 1/1 (Q38 p.6) ...
[08:59:56]
     ❓ provisional NO — link kept pending next verdict (§6.2)
[08:59:56]
     ❌ End of chain: pending NO confirmed — Q25 link removed (that QCM only)
[08:59:56]
  [CC-CHECK] [CAS 4] ✅ Done — 0 kept, 1 unlinked, 0 unresolved
[08:59:56]
     ❓ provisional NO — link kept pending next verdict (§6.2)
[08:59:56]
[CC-CHECK] Verifying chain 1 — QCM 2/3 (Q5 p.1) ...
[08:59:56]

  [CC-CHECK] [CAS 6] CAS CLINIQUE — 1 QCM(s) (Q39 p.7 → Q39 p.7)
[08:59:56]
  [CC-CHECK]   Case: "Vous évoquez: (cochez la réponse juste) a- Une ischémie sous épicardiq..."
[08:59:56]
[CC-CHECK] Verifying chain 6 — QCM 1/1 (Q39 p.7) ...
[08:59:56]
     ✅ belongs (0.90) — keeps the clinical case
[08:59:56]
  [CC-CHECK] [CAS 5] ✅ Done — 1 kept, 0 unlinked, 0 unresolved
[08:59:56]
     ❓ provisional NO — link kept pending next verdict (§6.2)
[08:59:56]
[CC-CHECK] Verifying chain 2 — QCM 2/3 (Q10 p.2) ...
[08:59:56]
     ✅ belongs (0.90) — keeps the clinical case
[08:59:56]
[CC-CHECK] Verifying chain 3 — QCM 2/3 (Q23 p.4) ...
[08:59:57]
     ⛔ Two consecutive NOs — case closed before Q4; 1 remaining QCM(s) unlinked without LLM calls
[08:59:57]
  [CC-CHECK] [CAS 1] ✅ Done — 0 kept, 3 unlinked, 0 unresolved
[08:59:57]
     ❓ provisional NO — link kept pending next verdict (§6.2)
[08:59:57]
[CC-CHECK] Verifying chain 3 — QCM 3/3 (Q24 p.4) ...
[08:59:57]
     ✅ belongs (0.90) — keeps the clinical case
[08:59:57]
  [CC-CHECK] [CAS 6] ✅ Done — 1 kept, 0 unlinked, 0 unresolved
[08:59:57]
     ⛔ Two consecutive NOs — case closed before Q9; 1 remaining QCM(s) unlinked without LLM calls
[08:59:57]
  [CC-CHECK] [CAS 2] ✅ Done — 0 kept, 3 unlinked, 0 unresolved
[08:59:59]
     ✅ belongs (0.90) — keeps the clinical case
[08:59:59]
     ↩️ §7 re-check: Q23 (provisional NO followed by YES) ...
[09:00:01]
     ✅ §7 re-check: Q23 actually belongs — provisional NO was a model error, link kept
[09:00:01]
  [CC-CHECK] [CAS 3] ✅ Done — 2 kept, 0 unlinked, 0 unresolved
[09:00:01]
[CC-CHECK] ⛔ Chain 1 closed early (two consecutive NOs) — 1 LLM call(s) saved in 3101 ms
[09:00:01]
[CC-CHECK] ⛔ Chain 2 closed early (two consecutive NOs) — 1 LLM call(s) saved in 3461 ms
[09:00:01]
[CASCADE-TRACE] stage=cas_scrub event=START
[09:00:01]
[CASCADE-TRACE] stage=cas_scrub event=END elapsed_ms=1 detail=with_cas=5 scrubbed=0
[09:00:01]
[CC-CHECK] 💾 Corrections written → all_qcms.json
[09:00:01]

══════════════════════════════════════════════════════════════
[09:00:01]
📊 CLINICAL CASE VERIFICATION & EXTRACTION SUMMARY
[09:00:01]
══════════════════════════════════════════════════════════════
[09:00:01]
  Total QCMs extracted:    80
[09:00:01]
  Total Clinical Cases:    3
[09:00:01]
  QCMs with Case:          5
[09:00:01]
  QCMs without Case:       75
[09:00:01]
──────────────────────────────────────────────────────────────
[09:00:01]
  Chains verified:         6
[09:00:01]
  Kept:                    4
[09:00:01]
  Unlinked (wrong links):  7
[09:00:01]
  Unresolved (flagged):    0
[09:00:01]
  Closed early:            2
[09:00:01]
  LLM calls:               11 made, 2 saved
[09:00:01]
  Cas text scrubbed:       0
[09:00:01]
  Model used:              google/gemini-2.5-flash-lite
[09:00:01]
──────────────────────────────────────────────────────────────
[09:00:01]
📋 Breakdown by Case:
[09:00:01]
  🔹 Case 1 (CAS CLINIQUE): 3 QCMs (Q22 → Q24, p.4) — "Parmi les causes de syncope au cours de la cardiomyopat..."
[09:00:01]
  🔹 Case 2 (CAS CLINIQUE): 1 QCMs (Q38 → Q38, p.6) — "Réveillé en pleine nuit par une douleur méso cardiaque ..."
[09:00:01]
  🔹 Case 3 (CAS CLINIQUE): 1 QCMs (Q39 → Q39, p.7) — "Vous évoquez: (cochez la réponse juste) a- Une ischémie..."
[09:00:01]
══════════════════════════════════════════════════════════════
[09:00:01]
[CC-CHECK] 💾 Audit saved → clinical_case_verification.json
[09:00:01]
[CASCADE-TRACE] stage=checker event=END elapsed_ms=6762 detail=status=ok
[09:00:01]
[AUTO-ENRICH] Chaining Step 4+5 auto-build (run_post_step3_build)...
[09:00:01]
[CASCADE-TRACE] stage=build event=START
[09:00:01]

============================================================
[09:00:01]
POST-STEP-3 AUTO-BUILD  (Step 4 + Step 5 merged)
[09:00:01]
============================================================
[09:00:01]
✓ Template saved: Default-Template-xlsx
[09:00:01]
[AUTO-BUILD] Template 'Default-Template-xlsx' saved with keys: ['Num', 'Cas', 'Text', 'A', 'B', 'C', 'D', 'E', 'Hint', 'Correct', 'Exp', 'categoryName', 'tagSuggere', 'Year', 'Tag', 'Type']
[09:00:01]

============================================================
[09:00:01]
STEP 4: JSON FORMAT TEMPLATE
[09:00:01]
============================================================
[09:00:01]

[AUTO] Selecting template: Default-Template-xlsx
[09:00:01]

✅ Template selected.
[09:00:01]

============================================================
[09:00:01]
STEP 5: JSON BUILDING & MERGING
[09:00:01]
============================================================
[09:00:01]
📄 Loaded 80 QCMs from 1 files. Mapping to template...
[09:00:01]
  Processed 10/80...
[09:00:01]
  Processed 20/80...
[09:00:01]
  Processed 30/80...
[09:00:01]
  Processed 40/80...
[09:00:01]
  Processed 50/80...
[09:00:01]
  Processed 60/80...
[09:00:01]
  Processed 70/80...
[09:00:01]
  Processed 80/80...
[09:00:01]

✅ Merged JSON saved to /app/output/admin/cardio_sec_1/step5_json/merged_qcms.json
[09:00:01]
[XLSX] Saved -> 80_qcms_source.xlsx
[09:00:01]
[AUTO-BUILD] ✅ Auto-build done: 80 QCMs merged.
[09:00:01]
[AUTO-BUILD] ✅ Copied merged_qcms.json → step3_metadata/accepted/
[09:00:01]
[AUTO-BUILD] ✅ Copied xlsx → step3_metadata/accepted/80_qcms_source.xlsx
[09:00:01]
[CASCADE-TRACE] stage=build event=END elapsed_ms=224 detail=status=ok
[09:00:01]
[AUTO-ENRICH] ✅ Cascade complete: 80 total QCMs, 3 clinical case(s) verified.
[09:00:01]
[CASCADE-TRACE] stage=copyback event=START
[09:00:01]
[AUTO-ENRICH] ✅ Copied merged_qcms.json → step2_qcm/accepted/
[09:00:01]
[AUTO-ENRICH] ✅ Copied 80_qcms_source.xlsx → step2_qcm/accepted/
[09:00:01]
[CASCADE-TRACE] stage=copyback event=END elapsed_ms=0 detail=surfaced
[09:00:01]
[CASCADE-TRACE] stage=cascade event=END elapsed_ms=31244 detail=status=ok
[09:00:01]
⚡ Auto-enrich (Step 3 + build) completed: 80 QCMs merged.