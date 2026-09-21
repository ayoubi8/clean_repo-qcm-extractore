# Batch History — "No past batches yet" Root Cause + Fix & Resume-Project Integration Plan

Date: 2026-09-21 · Branch `main`
Follow-up to: docs/plans/session-resume-batch-history-progress-cache.md (Phases 1–7 DONE)

> **Status: IMPLEMENTED (Phases B + D + E, 2026-09-21).**
> - Phase B: `_storage_batch_ids` / `_storage_uids` helpers (correct flat-listing
>   traversal), `_hydrate_local` re-persistence; `list_user_batches` + `_iterate_manifests`
>   fallbacks rewritten; F18 regression test added (`tests/test_autorun_batch.py`).
> - Phase D: shared `frontend/src/components/batch/BatchHistoryList.tsx` used by the
>   Auto Run wizard AND `ResumeProjectModal` (new `onOpenBatch` prop → `/batch/:id`).
> - Phase C (SQL `batches` table): still optional/open.

---

## 1. Root cause (question: "is it stored in env? is it in Supabase?")

Batch manifests are **NOT stored in env vars**. The batch manifest (`batch.json`)
is dual-written at every update to two places (`api/autorun_batch.py:88-122`):

1. **Local FS**: `{uid}/_batches/{batch_id}/batch.json`
2. **Supabase Storage**: bucket `qcm-projects` at `{uid}/_batches/{batch_id}/batch.json`
   (`api/autorun_batch.py:107-109`, via `storage_client.write_file`)

So the history *should* survive a HF Space rebuild via Storage — but there is a
real bug that explains the symptom:

### The bug: broken Storage fallback listing

When a Space restart/rebuild wipes the local FS, `list_user_batches`
(`api/autorun_batch.py:791-801`) and `_iterate_manifests`
(`api/autorun_batch.py:681-693`) try to recover manifests from Storage by
calling `list_files("")` and expecting items shaped like
`{uid}/_batches/{batch_id}` (3 path parts).

But Supabase Storage `list("")` is a **FLAT root listing** — it returns only
top-level per-user folder entries (`{uid}`, 1 part), never 3-part paths.
Result: after a rebuild, zero batches are found. The frontend then gets `[]`
and `loadBatches` silently treats a fetch failure as "empty"
(`frontend/src/components/launcher/autorun-wizard/AutoRunWizard.tsx:91-98`) →
**"No past batches yet."**

### Secondary possibilities (verify before fixing)

- The old batch ran on a version **before** Phase 1 shipped → no `batch.json`
  was ever written back then (data unrecoverable; new batches will work after
  the fix regardless).
- Storage manifest writes were failing on the Space — check logs for
  `[AUTORUN-BATCH] Storage manifest write failed`.

---

## 2. Plan (no code written yet)

### Phase A — Verify (diagnostics)

1. Check Supabase Storage directly (Dashboard → `qcm-projects` bucket): does
   `{uid}/_batches/*/batch.json` exist?
2. Grep Space logs for `Storage manifest write failed` /
   `Storage batch listing failed`.

→ This tells us whether old batches are in Storage (fixlisting, Phase B) or
never got written (they lost the data — but new batches will work after Phase B).

### Phase B — Fix the Storage fallback (backend)

1. `list_user_batches`: fallback = `list_files(f"{uid}/_batches")` → each
   returned entry name is a `batch_id` → call `read_manifest(uid, batch_id)`
   for each entry. Batch folder count per user is tiny; O(entries) read is
   acceptable. Keep local FS first (fast path), dedup by batch_id.
2. `_iterate_manifests` (startup auto-resume, same bug at :681-693): fallback =
   list root → per-user folder entries → recurse into `{uid}/_batches` with the
   same per-batch `read_manifest` pattern. Keeps startup auto-resume working
   after rebuilds too.
3. Summaries / merge behavior unchanged — only the listing traversal changes.

### Phase C — Optional hardening: SQL `batches` table (Supabase DB)

- New table: `batches (batch_id pk, uid, created_at, updated_at, state, source,
  counts jsonb, preview_names jsonb)` upserted best-effort at manifest write
  time (in `write_manifest`).
- `list_user_batches` reads SQL first (instant, no object scans), Storage
  manifests as fallback (unchanged Phase B path survives SQL loss).
- Migration script + RLS policy. Aligns with still-open **Phase 4b**
  (`projects.batch_id` for clickable AUTO badge) — can share one migration.

### Phase D — Batches inside "Resume Project" (frontend)

1. `frontend/src/components/launcher/ResumeProjectModal.tsx`: add a
   "Recent batches" section above/below the project list — same row style as
   the wizard's block (date · N PDFs · preview names · state chip;
   `interrupted` → inline Resume button). Reuse `fetchBatches`, `resumeBatch`,
   `shortDate`, `HISTORY_CHIP` from the wizard.
2. Wire the click: `ProjectLauncher` / parent receives `onOpenBatch(batchId)` →
   navigate to `/batch/:id` (same mechanism as the wizard's `onStarted`), so
   clicking a past batch opens the batch cockpit directly.
3. Loading / empty states: skeleton rows while `batches === null`; hide the
   block silently on fetch failure (same policy as wizard).
4. Follow-up (Phase 4b): a `projects.batch_id` column would let a project row
   link directly to the parent batch that created it.

### Phase E — Tests + deploy

- Backend regression test: mock `list_files` returning a flat root listing →
  the patched per-folder helper must still surface Storage-only batches.
- Manual E2E: rebuild Space → history block shows pre-rebuild batches → click
  → `/batch/:id` opens → Resume works for interrupted rows; Resume Project
  modal shows the same rows and opens `/batch/:id` on click.
- `npm run build` green; standard deploy routine (`git push space main`, etc.).
