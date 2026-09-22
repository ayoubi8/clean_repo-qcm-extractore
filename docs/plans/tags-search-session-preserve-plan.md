# Tags & Search Plan — Project/Batch tagging, colored search bar, session preservation

Date: 2026-09-22 · Branch `main`
Status: **PLAN — not yet implemented**

---

## 1. Feature summary (requested)

1. **Tags**: every project and every auto-run batch gets tags:
   - Region tag (REQUIRED for every new creation): `oran` (orange), `mosta` (green),
     `tlemcen` (brown).
   - Module tag (OPTIONAL): selects from a course-module name list (see §3 open question —
     the codebase has no existing module registry; proposals below).
   - User may skip the module tag.
2. **Forced tagging**: New Project creation AND the Auto Run wizard MUST have the region
   tag chosen before a project/batch can start.
3. **Search bar**: filters the project lists (Resume Project tab, Recent Projects) and
   batch lists by **name AND tag**; tags render as colored chips and are themselves
   clickable filters.
4. **Storage**: all tag data persisted to Supabase (SQL), not just local FS.
5. **Session preservation (launcher bug)**: when the user clicks "Switch Project" and
   closes the launcher without selecting anything, the session they were in must be kept
   (no forced launcher re-open on top of the current project).

Existing DB context: `projects` table already exists
(user_id, name, origin, total_tokens, pdf_storage_path, …) — tags extend it; batches get
a new table (matches §Phase C of batch-history-storage-fallback-resume-project-plan.md).

---

## 2. Open question — module names source

No module registry exists in the code (only pipeline step modules like
`modules/post_step2_metadata.py`, which are NOT course modules).
Proposed: **admin-managed module list** (fits existing `users`/`reference_databases`
pattern) — a `module_tags` table seeded editable from the AdminPanel; the wizard shows
the current list. If you have a fixed list in mind, it can be hardcoded in the same
migration instead. **Decide before implementation.**

---

## 3. Backend (Supabase + API)

### 3.1 Migrations (new SQL file)
1. `ALTER TABLE projects ADD COLUMN tags jsonb DEFAULT '[]'`
   — array of `{key: "region"|"module", value: "oran"|"...", }`.
2. New table `batches` (borrowed from batch-history Plan §Phase C):
   `batch_id uuid pk`, `user_id`, `created_at`, `updated_at`, `state`, `source`,
   `counts jsonb`, `preview_names jsonb`, **`tags jsonb DEFAULT '[]'`**.
3. New table `module_tags`: `id uuid pk`, `user_id` (nullable = global), `name` unique
   per user, `created_at`.
4. Backfill: existing projects/batches → `tags` empty; they render **untagged** (grey
   chip) so the search bar still finds them by name.
5. RLS: owner-only, mirror the `projects` policies.

### 3.2 API changes (`api/real_api.py`)
1. `GET /env/step-models` (or a new `GET /env/tags`): return region tag vocabulary with
   colors (single source of truth) + user's module tags.
2. `POST /projects/new`: accept `region_tag` (required → 422 if missing) + optional
   `module_tag`; write into `projects.tags`.
3. Wizard `run_batch` batch-create: validate region tag server-side too; persist a row
   in `batches` with tags (also feeds the Phase 3 SQL-first history listing later).
4. `GET /projects` (fetchProjects) + `GET /autorun/batches`: include `tags` in the rows.
5. `PATCH` endpoints to re-tag an existing project/batch (nice-to-have, not blocking).
6. Migration hook on startup (same pattern as the `total_tokens` idempotent migration at
   real_api.py:~1448).

---

## 4. Frontend

### 4.1 Shared tag primitives (new `frontend/src/lib/tags.ts` + `components/tags/TagChip.tsx`)
- `REGION_TAGS = [{key:'region', value:'oran', color:'orange'},
  {value:'mosta', color:'green'}, {value:'tlemcen', color:'brown'}]` (Tailwind palette
  amber/green/stone-700) — chips rendered as small rounded badges next to the AUTO badge
  in project rows and in batch rows.
- Validation helper: `hasRegionTag(project)`.

### 4.2 Forced selection
1. `NewProjectModal`: at the bottom, a REQUIRED "Wilaya / module" block — region buttons
   (colored) + optional module dropdown (from `/env/tags`); "Create" button disabled +
   inline error until region is selected.
2. `AutoRunWizard` (BatchConfigForm stage): same block; `createProject`/`runBatch`
   disabled until region chosen; the wizard *upload + create* path passes tags through —
   it already `createProject()`s per PDF (one wizard-level choice → same tags for all
   PDFs of the batch).

### 4.3 Search bar
1. New shared `components/search/SearchBar.tsx`: text input (matches project/batch NAME,
   live `startsWith/contains` client-side) + tag-chip filter row (clicking `oran` filters
   to orange-only; AND-able: region + module chips).
2. Mount in:
   - `ResumeProjectModal` (top, above recent batches) — filters BOTH the project list and
     the batch history rows;
   - `RecentProjectsList` (Dashboard);
   - `AutoRunWizard`'s history block (same `BatchHistoryList` component — pass filter
     prop down).
3. Client-side filtering of server rows (lists are ≤50 items — no API change needed).

### 4.4 Session preservation (launcher bug)
Current behavior: `setActiveProject(null)` (TopBar:51) sets `isLauncherOpen = true`
(appStore:11) and closing the launcher without choosing calls `navigate('/')` when no
active project (ProjectLauncher:73) — so abandoning the launcher drops the user back on
a dashboard with NO session.
Fix plan:
1. `topbar/projects` store-side snapshot: `appStore` gains
   `lastActiveProject: Project | null` — updated whenever `setActiveProject(p != null)`
   runs; `setActiveProject(null)` keeps `lastActiveProject` intact.
2. Launcher close (`X` button): if `lastActiveProject` exists → restore it
   (`setActiveProject(lastActiveProject)`) instead of navigating to `/` — the user is
   back exactly where they were (same pipeline page/status); the launcher only
   auto-reopens when there is genuinely no prior session.
3. Keep the current "close → stay on pipeline" behavior when an activeProject exists.
4. Guard: never re-broadcast `isLauncherOpen: true` on rehydration — `partialize`
   keeps it, but add `isLauncherOpen: false` default treatment so a reload with an
   active project doesn't summon the launcher (edge case check in tests).

---

## 5. Tests

Backend:
- T1: `POST` create without region tag → 422; with → `tags` persisted.
- T2: batch create with tags → `batches` row written + manifest mount/index unaffected.
- T3: `/autorun/batches` + `/projects` rows include `tags`.
- T4: tag PATCH re-tag idempotent; backfill leaves old rows untagged, not broken.

Frontend (npm build + manual):
- T5: wizard blocks run until region selected; toggling module optional.
- T6: search filters by name, by chip, combined; empty results state shown.
- T7: switch-project → close launcher → session restored (no dashboard redirect).
- T8: reload page with active project → launcher does NOT auto-open.

## 6. Order of work
1. Decide §2 (module names source) → migrations (§3.1).
2. Backend API (§3.2) + tests T1–T4.
3. Tag primitives + forced selection (§4.1–4.2).
4. Search bar (§4.3).
5. Session preservation fix (§4.4) — independent of tags; can ship first/parallel.
