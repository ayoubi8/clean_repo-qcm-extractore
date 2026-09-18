# Google Drive Link → PDF Import — Implementation Plan

Status: **PLAN ONLY — no code written**
Date: 2026-09-18
Scope: additive input type next to the existing PDF upload. Zero changes to the upload path's behavior.

---

## 1. Current Architecture Summary (audit)

### 1.1 Frontend upload flow

| Concern | Detail |
|---|---|
| Component | `frontend/src/components/launcher/NewProjectModal.tsx` — drag & drop zone + hidden `<input type="file" accept=".pdf">` (lines 94–100), client-side extension check only (`.pdf` suffix, line 23/32), no size check |
| Flow | `handleCreate` (lines 48–73): ① `createProject({name, pdf_path: ''})` → ② `uploadProjectPdf(projectName, file, onProgress)` → ③ `onSuccess({...project, pdf_path})` |
| Success handler | `ProjectLauncher.tsx:40-44` — `setActiveProject(project)`, close modal, `navigate('/pipeline')`. **No pipeline step is auto-run**; the user later clicks "Run Step" on Step 1 from `ConfigPanel.tsx` |
| Request format | multipart/form-data via XHR for progress (api.ts `uploadProjectPdf`, lines 117–150; `xhr.upload.onprogress` percent UI in NewProjectModal lines 145–158). Auto 401 retry on token expiry |
| Project name | Auto-derived from `file.name` (`NewProjectModal.tsx:21-26`), user-editable |
| State machine | `Stage = 'pick' | 'uploading' | 'done' | 'error'` + `uploadPct` + `errorMsg` |

### 1.2 Backend ingest (the tail we must reuse)

- **`POST /projects`** — `real_api.py:581-647` (`create_project`): creates `/app/output/{user_id}/{name}/`, writes local `project.json`, mirrors it to Supabase Storage via `write_file`, upserts the `projects` DB row (`user_id,name` conflict key, `pdf_storage_path`, `total_tokens`/`tokens_synced` with schema-resilient fallback, lines 602-638), then `invalidate_projects_cache()` (line 639). **No project-name validation/sanitization** — name goes straight into `Path()`.
- **`POST /projects/{name}/pdf`** — `real_api.py:897-940` (`upload_project_pdf`): extension check only (`.endswith(".pdf")`, line 899), `await file.read()` (**entire file into memory**, line 826↔903), then:
  1. writes local `/app/output/{uid}/{name}/source.pdf` (fixed name — original filename discarded)
  2. `write_bytes_file("{uid}/{name}/source.pdf", content)` → Supabase Storage (dual-write)
  3. writes `project.json` = `{"name", "pdf_path": "/app/.../source.pdf", "pdf_filename": <original>}` locally + Storage. `pdf_filename` feeds `pdf_stem_for_context()` (`modules/utils/output_naming.py:8-25`) → result xlsx naming
  4. updates `projects.pdf_storage_path` DB column + `invalidate_projects_cache()`
  5. returns `{"pdf_path", "size_bytes"}`
- **PDF serving**: `GET /projects/{name}/pdf` (`real_api.py:709-726`) — signed URL from Storage, local `FileResponse` fallback. Page count: `GET /projects/{name}/pdf-pages` (`real_api.py:729-805`).
- **Files** (`api/storage_client.py`): local first-restore semantics already exist — `_run_step_task` (real_api.py ≈1956-1972) re-downloads `source.pdf` from Storage if local FS was wiped, and rewrites `project.json`.

### 1.3 Pipeline entry point

Step 1 (`modules/step1_extraction.py`, pypdfium2 text mode or Vision OCR) is triggered manually per step:

- `POST /projects/{name}/steps/{step_id}/run` (real_api.py ≈1828) → `asyncio.ensure_future(_run_step_task(...))` → `job_manager` bookkeeping (`api/job_manager.py` — in-memory dict keyed `"{project}-{step}"`)
- `_run_step_task` (real_api.py ≈1865) restores inputs from Storage, then `ProjectContext(project)` + step modules read **file paths** from `context.get_path(...)`. The PDF is read **from disk** as `source.pdf`.
- Status polled via `GET /steps/{step_id}/status` (real_api.py:2516); logs streamed over WS `/ws/log/{project}/{step_id}` (2547).

**Conclusion: the pipeline consumes a file path at `/app/output/{uid}/{name}/source.pdf`. A Drive import only has to produce that file (+ project.json + Storage + DB row) with byte-for-byte identical layout — nothing downstream changes.**

### 1.4 Jobs / auth / quotas today

- Step execution: async, per-(project,step) singleton task `job_manager.set_running/append_log/set_done/set_error` with stop/cancel support. Project creation itself is **synchronous** — no job infra involved.
- Auth: JWT `Depends(get_current_user)` on every project route (`api/auth.py:302 get_current_user`).
- Rate limiting: **only login (5/min) and register (3/min)** — `check_rate_limit` (`api/auth.py:25-47`, in-memory sliding window, IP-keyed). **Uploads are not rate-limited and have no size quota.**
- Validation: upload = extension check only. **No magic-byte check, no MIME check, no size cap.**
- Timeouts: no upload timeout; uvicorn default (h11) has no body-size limit; `python-multipart` spools multipart to disk — memory only hit at `await file.read()`.

### 1.5 Infrastructure / conflicts relevant to remote fetches

- `httpx` is already a dependency (`api/requirements.txt:10`) — no new package needed. No `requests`/urllib3 use server-side.
- Outbound HTTPS works on the host (routes already call Google APIs: `googleapiclient`, OpenRouter, DeepSeek). No egress proxy config anywhere. Docker (`api/Dockerfile`) is a plain `python:3.11-slim` + uvicorn; **no network policy restrictions** beyond the host.
- Docker CMD uses `--reload` in "prod" (line 7) — existing risk, unaffected.
- CORS is `allow_origins=["*"]` (real_api.py:53) — unaffected.
- HuggingFace Space deployment (`/app` path convention everywhere): outbound internet is available on HF Spaces.
- No existing feature-flag/env exposure endpoint for frontend toggles; models flags are read from Storage-persisted `.env` via `GET` step-models route (`useStepModels` → real_api.py ≈2639 `read_env`).

---

## 2. Proposed Design (minimal)

```
┌ Frontend (NewProjectModal, additive under upload dropzone)
│  "— or import from a Google Drive link —"
│  [paste link input] [Import from Drive]
│        │  POST /projects/{name}/pdf-from-drive  {link}   (after POST /projects)
│        ▼
┌ Backend new route (real_api.py)
│  auth → name check → feature flag
│        ▼
┃ gdrive_import.py (new service, pure functions — unit-testable)
│  ① extract file ID (strict regex, reject everything else)
│  ② build download URL server-side from the ID (never fetch user URL)
│  ③ SSRF-guarded streaming download (allowlist + DNS private-range block
│     re-validated per redirect hop, ≤3 hops, size cap, timeouts)
│  ④ magic-byte + MIME validation
│        ▼  bytes (%PDF- verified)
┃ _store_pdf_bytes(...) — EXACT same tail as upload_project_pdf:
│  local source.pdf → Storage → project.json → projects.pdf_storage_path → invalidate cache
│        ▼
└ Response identical to upload: {"pdf_path", "size_bytes", "file_name"?}
   → frontend onSuccess → /pipeline → user runs Step 1 as always
```

- New service module `api/gdrive_import.py`; a small shared tail helper `_store_pdf_bytes(...)` extracted in `real_api.py` and called by **both** the existing upload route and the new route (refactor is 1:1 code move; upload behavior provably unchanged — see regression checklist §9).
- Google Docs/Sheets/Slides links are **rejected explicitly** (they are not PDFs natively; converting them silently is out of scope — Open question Q6).

### Google Drive specifics

| Case | Detection | User-facing message |
|---|---|---|
| `/file/d/<ID>/view`, `/view?usp=sharing`, `open?id=<ID>`, `uc?id=<ID>` | ID extraction regexes (§4) | — (accepted) |
| Virus-scan confirm page (>25 MB) | HTML body (content-type `text/html`) contains `confirm=` / `uc-name-size` → retry once with `&confirm=t&uuid=<token>` | Transparent |
| Not public / requires login (403, or redirect to `accounts.google.com`) | status + redirect host check | "This file is not public. Set sharing to 'Anyone with the link' → Viewer, then try again." |
| File not found / deleted (404) | HTTP 404 | "Drive file not found — check the link and that the file still exists." |
| Quota exceeded (429 from Drive) | HTTP 429 | "Drive is rate-limiting this file. Try again in a few minutes." |
| Docs/Sheets/Slides link | URL pattern `/document/d/`, `/spreadsheets/d/`, `/presentation/d/` rejected before download | "That link is a Google Doc/Sheet/Slide, not a PDF. Use File → Download → PDF in Google Docs and upload that." |
| Folder link `/drive/folders/` | rejected pre-download | "That's a folder link — share a single PDF file." |
| Non-PDF file (no `%PDF-` magic) | magic bytes after download | "The Drive file is not a PDF." |
| Too large | byte-cap exceeded mid-stream | "File is over the N MB limit for Drive import." |
| Link not parseable | regex miss | "Paste a valid Drive link, e.g. https://drive.google.com/file/d/…/view" |

---

## 3. Frontend Changes

**File: `frontend/src/components/launcher/NewProjectModal.tsx`**

- Keep the dropzone, name field, progress and submit button untouched.
- Under the dropzone: divider — `— or import from a Google Drive link —` — then:
  - text input (placeholder `https://drive.google.com/file/d/…/view`)
  - small "Import from Drive" button
- New state: `mode: 'file' | 'link'` (tab/segmented switch so both options never run at once), `link` string, `importing` boolean. Missing link input yields stage `'importing'` with an indeterminate progress bar (server-side download — no XHR progress possible) + "Importing PDF from Google Drive… this can take a minute for large files."
- Flow (link mode): ① `createProject({name, pdf_path: ''})` (same as today) → ② `importPdfFromDrive(projectName, link)` (new api.ts fn) → ③ `onSuccess({...project, pdf_path: imported.pdf_path})` → identical to upload success.
- Project name: typed by user (no filename to auto-derive); suggest sanitizing to `[^A-Za-z0-9._-] → '_'` client-side to match backend conventions, same as current `\s+ → '_'` rule (NewProjectModal.tsx:133).
- Error state: render `err.message` from the backend `detail` strings above, verbatim (they are already user-friendly). Reuse existing error box (lines 160-165).

**File: `frontend/src/lib/api.ts`** — add one function, JSON body:

```ts
export async function importPdfFromDrive(projectName: string, link: string)
  : Promise<{ pdf_path: string; size_bytes: number; file_name?: string }>
```
(using `fetchWithRefresh` + `getAuthHeaders`, same conventions as `createProject`, api.ts:103-114).

**File: `frontend/src/components/launcher/ProjectLauncher.tsx`** — no change.

---

## 4. Backend Changes

**New file: `api/gdrive_import.py`** (service, no FastAPI imports → pure unit-testable)

1. `extract_drive_file_id(link: str) -> str | None` — strict patterns:
   - `https://drive.google.com/file/d/<ID>/...` → `r"^https://drive\.google\.com/file/d/([A-Za-z0-9_-]{20,})(?:/|$)"`
   - `https://drive.google.com/open?id=<ID>` / `?id=` → `r"^https://drive\.google\.com/open\?id=([A-Za-z0-9_-]{20,})"`
   - Legacy `uc?id=<ID>` → same `id=` family
   - **Reject anything else** (docs/sheets/slides/folders/short links — Open question Q3 on `drive.usercontent.google.com` raw paste).
2. `ALLOWED_HOSTS = {"drive.google.com", "docs.google.com", "drive.usercontent.google.com"}`.
   `build_download_urls(file_id)` → initial URL **always constructed**:
   `https://drive.google.com/uc?export=download&id=<ID>` (follows to `drive.usercontent.google.com/download?id=<ID>&export=download`), confirm-retry variant `...&confirm=t&uuid=<token>`.
3. `_assert_public_host(url)` — scheme must be `https`, hostname ∈ allowlist, port absent or 443.
4. `_dns_guard(hostname)` — `socket.getaddrinfo` → for every resolved IP: `ipaddress` private/loopback/link-local/reserved/multicast check (`0.0.0.0/8, 10/8, 100.64/10, 127/8, 169.254/16, 172.16/12, 192.168/16, ::1, fc00::/7, fe80::/10`).
5. `download_drive_pdf(link, max_bytes, on_progress=None) -> (path, filename, size)`:
   - `httpx.Client(follow_redirects=False, timeout=httpx.Timeout(connect=10, read=30, write=30, pool=30))`
   - manual redirect loop: ≤3 hops; **re-run `_assert_public_host` + `_dns_guard` on every hop's hostname**; `307` with `confirm=t` token handled here
   - if response is `text/html` and contains a Drive confirm form → extract `uuid`/`confirm` params, retry once
   - stream to a `SpooledTemporaryFile` in 1 MiB chunks; **hard byte counter aborts past `max_bytes`** (never trust `Content-Length`)
   - validate magic: first 999 bytes start with `%PDF-`; content-type secondary check (`application/pdf` or Drive-attachment octet-stream on `drive.usercontent.google.com/download`)
   - 403 → `NOT_PUBLIC`, 404 → `NOT_FOUND`, 429 → `QUOTA`; redirects to `accounts.google.com` → `NOT_PUBLIC`; non-PDF magic → `NOT_PDF`
   - filename: **only extracted from an RFC-compliant `Content-Disposition` and kept as display metadata**; never used for any path (the stored file is always `source.pdf`)
   - log only: file id length, status codes, hop hostnames, byte count — **never the raw link** (may carry `resourcekey`; treat as sensitive)
6. Error contract: raise `GoogleDriveImportError(code, message)`; route maps `code` → HTTP 4xx with the friendly `message` as `detail`.

**File: `api/real_api.py`** — two small pieces:

- Extract the tail of `upload_project_pdf` (lines ~903-940: local write → Storage write → project.json write → DB `pdf_storage_path` → cache invalidate) into `def _store_pdf_bytes(user, name, content: bytes, pdf_filename: str) -> dict` — called by both routes. Byte-for-byte identical behavior for upload.
- New route (sync `def`, runs in FastAPI threadpool — matches how LLM steps already use `run_in_executor`):

```python
@app.post("/projects/{name}/pdf-from-drive")
def import_pdf_from_drive(name: str, body: dict, request: Request,
                          user: dict = Depends(get_current_user)):
    # GDRIVE_IMPORT_ENABLED flag → 404 when off
    # per-user rate limit (reuse check_rate_limit pattern, key "gdrive:<user_id>", Proposed: 10/min)
    # extract_drive_file_id → 400 on miss
    # download_drive_pdf(request.body.link) inside run_in_executor w/ cancellable thread?  (see Q1)
    # _store_pdf_bytes(user, name, content, pdf_filename)
    # return {"pdf_path", "size_bytes"}
```

**Specifics vs upload (stricter, additive):** magic-byte validation, size cap, timeout, DNS guard — upload path gains nothing, loses nothing.

### Config / env vars

| Var | Default | Purpose |
|---|---|---|
| `GDRIVE_IMPORT_ENABLED` | `false` | Feature flag; route returns 404 "not enabled" when off; frontend hides the input |
| `MAX_DRIVE_PDF_BYTES` | `209715200` (200 MB) | Stream byte cap (do not trust Content-Length; streamed) |
| Derived timeouts | — | hard-coded connect=10s / total≈120s in service, not env (keep surface small) |

---

## 5. Storage Impact

- **Identical file layout to upload** (mandated):
  - local `/app/output/{uid}/{name}/source.pdf`
  - Supabase Storage `{uid}/{name}/source.pdf`
  - `{uid}/{name}/project.json` (local + Storage) with `pdf_filename` — see Open question Q4 (Drive's real filename vs project name for `pdf_stem_for_context()`)
  - `projects.pdf_storage_path` DB column + cache invalidation
- No new folders, no duplicates, no cleanup: `source.pdf` is overwritten on re-import exactly as re-upload overwrites it (`upload_project_pdf` upsert behavior, storage_client.py:19-35).
- Temp spool during download: in-memory `SpooledTemporaryFile` (rolls to `/tmp` past a threshold) → freed when route returns. Container local FS is ephemeral (HF Space) — Storage dual-write already compensates (real_api.py:1956-1972 restore path).

---

## 6. Security Design

| Threat | Mitigation |
|---|---|
| SSRF via crafted URL | File-ID only; host allowlist; `https` only; hostname/port re-pinned **per redirect hop**; DNS resolved and every IP checked against private/loopback/link-local/reserved ranges (`ipaddress`); never fetch the raw user string |
| DNS rebinding | DNS resolve + IP check immediately before each stream open; hostname (not IP) in URL prevents double-resolution TOCTOU gaps beyond the per-hop check (note residual risk for rebind between check and connect — mitigated by allowlisted hosts controlled by Google) |
| Redirect abuse | Cap 3 hops; re-validate allowlist + DNS every hop; never follow `follow_redirects=True` blindly |
| Decompression bombs | `httpx` never transparently decompressed beyond content-encoding; we count **raw** body bytes vs cap; gzip only if Drive sends it and cap still applies |
| Oversized file | Streaming chunk counter aborts at `MAX_DRIVE_PDF_BYTES`; no disk spill of full unauthorized payloads |
| Malformed PDF | `%PDF-` magic check server-side; downstream protections unchanged (pypdfium2 in Step 1 already isolates parse failures — `modules/step1_extraction.py:61-92`) |
| Path injection via filename | File is always stored as `source.pdf`; alert on any use of Content-Disposition name for paths (metadata only) |
| Quota/DoS | Per-user rate limit (10/min proposed) + auth required — stricter than upload's current "nothing" |
| Token/PII leakage in logs | Log sanitized fields only, no raw link, no full URL with query |
| Upstream trust | Only Google allowlisted hosts; TLS enforced by `https` scheme pinning |

Timeouts: connect 10s, per-read 30s, overall ~120s (request-scoped); streaming keeps memory flat at ~1 chunks buffer × concurrency.

---

## 7. Conflicts / Risks Found + Minimal Fixes

| # | Finding | Fix (minimal) |
|---|---|---|
| R1 | `create_project` doesn't validate `name`; `.name` enters `Path()` (real_api.py:581-593) | Pre-existing. Wrap the new endpoint with the same `[^A-Za-z0-9._-]` check; recommend (optional) hardening in `create_project` itself |
| R2 | `upload_project_pdf` loads whole PDF into RAM (real_api.py:903) | Drive import streams to spooled file instead; note asymmetry; (optional follow-up: stream upload too) |
| R3 | No rate limit on ingest endpoints | Add per-user action key to `check_rate_limit`-style store for BOTH drive-import and (stricter parity) upload |
| R4 | Drive "can't scan" page shape is undocumented and changes | Confirm-page handling via content-type sniffing + `confirm=t`; covered by integration test + graceful "file not public / too large" fallback message |
| R5 | `file.exists()` from `storage_client` (storage_client.py:62-68) downloads the entire object just to check existence — used in the persistence tail | Our route writes immediately after download, so `file_exists` is not needed; only note |
| R6 | Endpoint may exceed HF/uvicorn default request timeouts for very slow downloads on **sync** route | Keep total ≤120s, chunked; document; if deployment timeout surfaces, switch route to job_manager pattern (existing infra) — see Q1 |
| R7 | Frontend `Stage` enum tightly couples upload with filename auto-derive | mode flag isolates link flow; no shared mutating state |
| R8 | `pdf_filename` is used by `pdf_stem_for_context()` for xlsx naming | Decide Q4; default to project name to avoid needing a second metadata write |

---

## 8. Testing Strategy

**Unit (pytest, `tests/test_gdrive_import.py`)**
- `extract_drive_file_id`: all 4 accepted formats (`/file/d/…/view`, with `?usp=sharing`, `open?id=`, `uc?id=`), plus rejects: Docs/Sheets/Slides, folders, non-Google hosts, `http:`, missing ID, JS injection payloads
- `_dns_guard`: mock `getaddrinfo` returning loopback / 10.x / 172.16.x / 192.168.x / 169.254.x / ::1 → each blocked; public IP → pass
- magic-byte: PDF pass; ZIP/PNG/HTML → `NOT_PDF`
- confirm-page: fixture HTML → retry URL with `confirm=t&uuid=…`
- error mapping: 403/404/429/redirect-to-accounts.google.com → messages

**Integration (FastAPI TestClient, Storage mocked)**
- happy path: small public PDF → `source.pdf` written locally + Storage + project.json + DB upsert called
- private file → 403 message "Set sharing to 'Anyone with the link' → Viewer"
- >200 MB simulated → capped, `TOO_LARGE`
- Google Doc link → 400 with Google-Docs message
- redirect to `http://127.0.0.1:9999` → blocked
- non-PDF Drive file (magic fails)
- flag off → 404

**Manual QA**
- upload flow regression: create + upload + run step 1 end-to-end
- 5 real links of every shape; slow-host large file; rate-limit hits its 429 message; HuggingFace Space real deployment (media-storage + egress verified)

---

## 9. Regression Checklist (upload unchanged)

- [ ] `NewProjectModal` file tab pixel-identical: same `id="btn-create-project"`, `id="input-project-name"`, same dropzone ids/behavior
- [ ] `POST /projects/{name}/pdf` request format, auth, response unchanged
- [ ] `_store_pdf_bytes` refactor passes: upload writes local + Storage `source.pdf`, `project.json` has same 3 keys, DB `pdf_storage_path` updated, `invalidate_projects_cache` called
- [ ] Original-filename → `pdf_filename` still honored for xlsx naming (compare before/after on a sample)
- [ ] `pdf-pages` endpoint still resolves (reads same `source.pdf`)
- [ ] Pipeline Step 1 runs from a local `source.pdf` produced by upload — same logs
- [ ] Existing suite green: `tests/test_persistence_pr*.py` cover the Storage/local dual-write paths

---

## 10. Files to Create / Modify

| Action | File |
|---|---|
| CREATE | `api/gdrive_import.py` — service: parsing, SSRF guard, streaming download, magic-byte validation |
| CREATE | `tests/test_gdrive_import.py` — unit + integration (FastAPI TestClient) |
| CREATE | `docs/plans/gdrive-link-import-plan.md` — this plan |
| MODIFY | `api/real_api.py` — extract `_store_pdf_bytes()`; add `POST /projects/{name}/pdf-from-drive`; read feature flag |
| MODIFY | `frontend/src/lib/api.ts` — add `importPdfFromDrive()` |
| MODIFY | `frontend/src/components/launcher/NewProjectModal.tsx` — link tab, states, errors |
| OPTIONAL | `api/auth.py` — generalize `check_rate_limit` to arbitrary (action, key) pairs if per-user limit chosen |

---

## 11. Rollout & Rollback

- **Flag**: `GDRIVE_IMPORT_ENABLED=false` default. Backend returns 404 when off. Frontend reads the flag from the step-models config response (`useStepModels` already surfaces server env); hide the Drive input when false. Zero-flag deployed state == today's app exactly.
- **Rollout**: deploy backend behind flag → verify with admin link tests → flip to `true` → ship frontend.
- **Rollback**: flip flag off (backend 404s, frontend hides input). No data migration; removing the route + service is a clean revert; `_store_pdf_bytes` refactor is behavior-preserving and independently revertable (its own commit).

---

## 12. Final Implementation Checklist

- [ ] Verify current upload behavior snapshot (record response shape of `upload_pdf` before refactor)
- [ ] Refactor `upload_project_pdf` → `_store_pdf_bytes()`; run regression checklist §9; commit in isolation
- [ ] Create `api/gdrive_import.py`: `extract_drive_file_id`, allowlist/DNS guard, `download_drive_pdf`, error enum
- [ ] Unit tests green on parsing + SSRF blocking
- [ ] Add `POST /projects/{name}/pdf-from-drive` + flag + per-user rate limit
- [ ] Integration tests green (mock Storage + mocked Drive responses)
- [ ] Add `importPdfFromDrive()` to `frontend/src/lib/api.ts`
- [ ] Frontend: mode switch + link input + importing/error/success states in `NewProjectModal.tsx`
- [ ] Wire flag into `useStepModels` response / feature endpoint so UI respects `GDRIVE_IMPORT_ENABLED`
- [ ] `npm run build` (frontend) + `pytest tests/test_gdrive_import.py`
- [ ] Manual QA on real Drive links (public, private, huge, Docs, folder) on local + staging
- [ ] Set `GDRIVE_IMPORT_ENABLED=true`; ship; monitor logs for `[GDRIVE]` markers

---

## Open Questions

1. **Q1 — sync download vs job:** sync-with-120s-cap (simplest, matches how Google Sheets tokens & ref-db downloads already behave on this server) assumed. If deployment latency >120s becomes a problem, migrate to the existing `job_manager` pattern (async task + `GET status`); flag in code as a TODO. Decision needed if plan accepted?
2. **Q2 — rate limit granularity:** per-user (needs a small generalization of `auth.check_rate_limit`) or reuse IP-window with a bigger limit? Proposed latter if no data.
3. **Q3 — raw `drive.usercontent.google.com/download?…` links pasted by users**: reject for now (strict ID regex only)? Most users paste `/file/d/`.
4. **Q4 — `pdf_filename` for xlsx naming**: use Drive's real filename (from `Content-Disposition`, sanitized) or reuse the project name? Recommend the latter (matches `project.json` single-writer simplicity).
5. **Q5 — max size for Drive import vs upload**: upload currently uncapped; importing capped at 200 MB. Acceptable asymmetry?
6. **Q6 — auto-conversion of Google Docs/Sheets to PDF** via `export?format=pdf`: explicitly out of scope for v1 (adds scope creep; only `/file/d/<ID>` PDFs).
