"""Auto Run Batch (multi-PDF) engine — docs/plans/autorun-batch-plan.md §4.

Phase 3 backend:
  - 5-slot PDF-level queue (`AUTORUN_BATCH_CONCURRENCY`, default 5; resolved Q2)
  - per-PDF sequential steps ["1","1.5","1.6","2","6"] — Steps 7/8 excluded (Q6)
  - failure isolation: one PDF's step error marks only that project
  - batch manifest `{uid}/_batches/{batch_id}/batch.json` (local + Supabase Storage)
  - `AR_` project-name prefix, numeric suffix on remaining collisions (resolved Q3)
  - Step 6 per-PDF source mapping (last_page / first_page / auto_search; Q6)
  - per-PDF retry (resolved Q9) and startup auto-resume (resolved Q12)

Import contract: this module does NOT import real_api at module level
(real_api imports it) — real_api-side helpers are imported lazily inside
functions so tests can patch them.
"""
import asyncio
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from job_manager import job_manager              # same singleton real_api uses
from project_manager import STEP_FOLDER_MAP       # step id → output folder
from project_manager import invalidate_projects_cache

# Engine paths root at one overridable constant (tests patch this attribute).
OUTPUT_ROOT = Path("/app/output")

BATCH_SEQUENCE = ["1", "1.5", "1.6", "2", "6"]
VALID_CORRECTION_SOURCES = ("last_page", "first_page", "auto_search")
VALID_STEP1_METHODS = ("pypdfium2", "vision_ocr")

MANIFEST_NAME = "batch.json"

# In-memory registries (double-start guards, plan R4).
_BATCH_TASKS: dict = {}        # batch_id → asyncio.Task
_RETRY_TASKS: dict = {}        # (batch_id, project) → asyncio.Task


def batch_enabled() -> bool:
    """Feature flag — on by default; set AUTORUN_BATCH_ENABLED=false to turn off."""
    return str(os.environ.get("AUTORUN_BATCH_ENABLED", "true")).strip().lower() in (
        "1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        raw = str(os.environ.get(name, "")).strip()
        return int(raw) if raw else default
    except (TypeError, ValueError):
        return default


def batch_concurrency() -> int:
    """PDF-level parallelism (resolved Q2: 5 at a time; next start when one finishes)."""
    return max(1, _env_int("AUTORUN_BATCH_CONCURRENCY", 5))


def max_batch_files() -> int:
    """Batch cap (resolved Q11: 10 PDFs maximum per batch)."""
    return max(1, _env_int("MAX_AUTORUN_BATCH_FILES", 10))


# ---------------------------------------------------------------------------
# Paths / manifest persistence
# ---------------------------------------------------------------------------

def _pdir(uid: str, name: str) -> Path:
    return OUTPUT_ROOT / uid / name


def _bdir(uid: str, batch_id: str) -> Path:
    return OUTPUT_ROOT / uid / "_batches" / batch_id


def new_batch_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"batch-{stamp}-{uuid.uuid4().hex[:6]}"


def write_manifest(uid: str, manifest: dict) -> None:
    """Dual-write the manifest: local FS + Supabase Storage (same as project.json)."""
    raw = json.dumps(manifest, ensure_ascii=False)
    batch_id = manifest.get("batch_id") or ""
    try:
        local = _bdir(uid, batch_id) / MANIFEST_NAME
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(raw, encoding="utf-8")
    except Exception as e:
        print(f"[AUTORUN-BATCH] local manifest write failed ({batch_id}): {e}")
    try:
        from storage_client import write_file
        write_file(f"{uid}/_batches/{batch_id}/{MANIFEST_NAME}", raw)
    except Exception as e:
        print(f"[AUTORUN-BATCH] Storage manifest write failed ({batch_id}): {e}")


def read_manifest(uid: str, batch_id: str) -> Optional[dict]:
    """Local-first manifest read; Storage fallback (survives FS wipes)."""
    local = _bdir(uid, batch_id) / MANIFEST_NAME
    try:
        if local.exists():
            return json.loads(local.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[AUTORUN-BATCH] local manifest read failed ({batch_id}): {e}")
    try:
        from storage_client import read_file
        return json.loads(read_file(f"{uid}/_batches/{batch_id}/{MANIFEST_NAME}"))
    except Exception:
        return None


def _mutate_manifest(uid: str, batch_id: str, apply) -> Optional[dict]:
    """Read → mutate → write. Coroutines never await inside the mutation (race-free)."""
    m = read_manifest(uid, batch_id)
    if not m:
        return None
    apply(m)
    write_manifest(uid, m)
    return m


def _set_batch_state(uid: str, batch_id: str, state: str) -> None:
    _mutate_manifest(uid, batch_id, lambda m: m.__setitem__("state", state))


def _mutate_project(uid: str, batch_id: str, project_name: str, state: str,
                    error_step: Optional[str] = None, current_step: Optional[str] = None) -> None:
    def _apply(m):
        for p in m.get("projects", []):
            if p.get("name") == project_name:
                p["state"] = state
                if error_step:
                    p["error_step"] = error_step
                else:
                    p.pop("error_step", None)
                if current_step:
                    p["current_step"] = current_step
                else:
                    p.pop("current_step", None)
                break
    _mutate_manifest(uid, batch_id, _apply)


def _finalise_batch(uid: str, batch_id: str) -> None:
    def _apply(m):
        states = [p.get("state") for p in m.get("projects", [])]
        if states and all(s == "done" for s in states):
            m["state"] = "done"
        elif any(s in ("pending", "running") for s in states):
            m["state"] = "running"
        else:
            m["state"] = "done_with_errors"
    _mutate_manifest(uid, batch_id, _apply)


# ---------------------------------------------------------------------------
# Naming (resolved Q3): AR_ prefix + smallest-free numeric suffix
# ---------------------------------------------------------------------------

def ar_display_name(pdf_name: str) -> str:
    """PDF filename → sanitized project stem (same charset rules as the upload flow)."""
    raw = re.sub(r"\.pdf$", "", (pdf_name or "").strip(), flags=re.IGNORECASE)
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._-")[:60].strip("._-")
    return clean or "pdf"


def assign_ar_names(files: list, existing_names: set) -> dict:
    """files ([{file_id, name}]) → {file_id: unique project name} with the AR_ prefix.

    The used-set grows as names are handed out — two PDFs with the same filename
    become AR_math / AR_math_2 (NOT a `__2` suffix; resolved Q3). Pass existing
    project names so collisions with earlier projects resolve the same way.
    """
    taken = set(existing_names or set())
    mapping: dict = {}
    for f in (files or []):
        stem = ar_display_name(f.get("name"))
        candidate = f"AR_{stem}"
        n = 2
        while candidate in taken:
            candidate = f"AR_{stem}_{n}"
            n += 1
        taken.add(candidate)
        mapping[f.get("file_id")] = candidate
    return mapping


def existing_project_names(uid: str) -> set:
    """Project folder names at the engine root — fast, local-only (no DB round-trip)."""
    try:
        return {d.name for d in (OUTPUT_ROOT / uid).iterdir()
                if d.is_dir() and not d.name.startswith(("_", "."))}
    except OSError:
        return set()


# ---------------------------------------------------------------------------
# Config resolution (resolved Q6)
# ---------------------------------------------------------------------------

def _page_count(pdf_path: Path) -> Optional[int]:
    """Page count via pypdfium2 — the same engine the /pdf-pages route uses."""
    try:
        import io
        import pypdfium2 as pdfium
        if pdf_path.exists():
            pdf = pdfium.PdfDocument(io.BytesIO(pdf_path.read_bytes()))
            try:
                return len(pdf)
            finally:
                try:
                    pdf.close()
                except Exception:
                    pass
    except Exception as e:
        print(f"[AUTORUN-BATCH] page count failed for {pdf_path}: {e}")
    return None


def resolve_step6_config(cfg: dict, uid: str, name: str) -> dict:
    """Wizard correction source → concrete per-PDF Step 6 config.

    last_page   → page_text / specific_pages / pages=str(N) — the per-PDF
                  automated "PDF has 9 pages → use page 9" logic (resolved Q6)
    first_page  → page_text / specific_pages / pages="1"
    auto_search → auto_detect / all_pages
    force_overwrite is ALWAYS False (resolved Q6 — part two: skip).
    Falsy model fields are dropped, so Settings (.env) defaults win (Q7).
    """
    cfg = cfg or {}
    pdf_path = str(_pdir(uid, name) / "source.pdf")
    out = {"pdf_path": pdf_path, "force_overwrite": False}
    for k in ("text_model", "text_fallback", "all_pages_model", "all_pages_fallback",
              "page_text_guidance", "candidate_threshold", "include_neighbors"):
        if cfg.get(k):
            out[k] = cfg[k]
    mode = cfg.get("correction_source", "auto_search")
    if mode == "auto_search":
        out.update({"source": "auto_detect", "correction_search_mode": "all_pages"})
        return out
    if mode == "last_page":
        n = _page_count(Path(pdf_path))
        pages = str(n or 1)
    else:  # first_page
        pages = "1"
    out.update({"source": "page_text", "correction_search_mode": "specific_pages",
                "pages": pages})
    return out


def resolve_step_config(step_id: str, config: dict, uid: str, name: str) -> dict:
    """One step's per-PDF config (wizard config already carries serialized step3 / CC)."""
    config = config or {}
    cfg = dict(config.get(f"step{step_id}") or {})
    pdf_path = str(_pdir(uid, name) / "source.pdf")
    if step_id == "1":
        cfg["pdf_path"] = pdf_path
        cfg.setdefault("force_overwrite", False)
        return cfg
    if step_id == "2":
        cfg.setdefault("page_range", "1-1-1")     # Auto-Loop hardcoded (ConfigPanel contract)
        return cfg
    if step_id == "6":
        return resolve_step6_config(config.get("step6") or {}, uid, name)
    return cfg                                    # 1.5 / 1.6 ride as given


def validate_batch_config(config: dict) -> list:
    """Config problems as a list of messages (empty = OK)."""
    config = config or {}
    problems = []
    method = (config.get("step1") or {}).get("method", "pypdfium2")
    if method not in VALID_STEP1_METHODS:
        problems.append(f"config.step1.method must be one of "
                        f"{VALID_STEP1_METHODS} (got {method!r})")
    source_mode = (config.get("step6") or {}).get("correction_source", "auto_search")
    if source_mode not in VALID_CORRECTION_SOURCES:
        problems.append(f"config.step6.correction_source must be one of "
                        f"{VALID_CORRECTION_SOURCES} (got {source_mode!r})")
    return problems


# ---------------------------------------------------------------------------
# Done-ness / resume entry point (plan §4.5)
# ---------------------------------------------------------------------------

def _step_done_local(uid: str, project: str, step_id: str) -> bool:
    """Container-local check: the step's output folder has at least one file."""
    folder = STEP_FOLDER_MAP.get(step_id, f"step{step_id}")
    step_dir = _pdir(uid, project) / folder
    try:
        return step_dir.is_dir() and any(step_dir.iterdir())
    except OSError:
        return False


def first_not_done_step(uid: str, project: str) -> Optional[str]:
    """First step in BATCH_SEQUENCE that is not a completed run.

    SQL step_results rows are authoritative (badge=success); the container-local
    output check is the fallback (same priority as GET /steps/{id}/status).
    Returns None when every batch step is already done.
    """
    try:
        from real_api import _latest_step_result_row
    except Exception:
        _latest_step_result_row = None

    for sid in BATCH_SEQUENCE:
        done = False
        if _latest_step_result_row is not None:
            try:
                row = _latest_step_result_row(uid, project, sid)
                done = bool(row and row.get("badge") == "success")
            except Exception as e:
                print(f"[AUTORUN-BATCH] step_results lookup failed ({project}/{sid}): {e}")
                done = False
        if not done:
            done = _step_done_local(uid, project, sid)
        if not done:
            return sid
    return None


# ---------------------------------------------------------------------------
# Ingest + origin marking
# ---------------------------------------------------------------------------

def _ingest_drive_project(uid: str, name: str, file_id: str) -> None:
    """Create the project (if needed) + download and store the Drive PDF.

    Reuses the exact ingest tail single-file imports use (route create_project
    + _store_pdf_bytes) — the layout downstream steps depend on is identical.
    """
    from gdrive_import import download_drive_file_by_id
    import real_api as ra

    if not (_pdir(uid, name) / "project.json").exists():
        ra.create_project({"name": name, "pdf_path": ""}, {"id": uid})
    data, display_name = download_drive_file_by_id(file_id)
    ra._store_pdf_bytes({"id": uid}, name, data, display_name or f"{name}.pdf")


def _mark_project_autorun(uid: str, name: str, batch_id: str) -> None:
    """Write origin/batch_id into project.json (local + Storage) and the DB column."""
    pdir = _pdir(uid, name)
    pdir.mkdir(parents=True, exist_ok=True)
    pjson = pdir / "project.json"
    data = {}
    if pjson.exists():
        try:
            data = json.loads(pjson.read_text(encoding="utf-8") or "{}")
        except Exception:
            data = {}
    data.update({"name": name, "origin": "autorun", "batch_id": batch_id})
    data.setdefault("pdf_path", str(pdir / "source.pdf"))
    out = json.dumps(data)
    try:
        pjson.write_text(out, encoding="utf-8")
    except Exception as e:
        print(f"[AUTORUN-BATCH] project.json write failed ({name}): {e}")
    try:
        from storage_client import write_file
        write_file(f"{uid}/{name}/project.json", out)
    except Exception as e:
        print(f"[AUTORUN-BATCH] project.json Storage write failed ({name}): {e}")
    try:
        from supabase_client import get_supabase
        from auth import get_db_user_id
        get_supabase().table("projects").update({"origin": "autorun"}) \
            .eq("user_id", get_db_user_id({"id": uid})).eq("name", name).execute()
    except Exception as e:
        print(f"[AUTORUN-BATCH] origin DB update skipped ({name}): {e}")
    invalidate_projects_cache(uid)


# ---------------------------------------------------------------------------
# Engine: 5-slot PDF queue, per-PDF sequential steps, failure isolation
# ---------------------------------------------------------------------------

def _project_busy(project: str) -> bool:
    """Any batch step of this project currently running/stopping in job_manager."""
    return any(job_manager.get_status(project, sid) in ("running", "stopping")
               for sid in BATCH_SEQUENCE)


def _spawn_runtime_task(project: str, uid: str, step_id: str, cfg: dict):
    """Lazy step dispatcher — real_api._run_step_task resolved at call time so
    tests can patch it in real_api's namespace."""
    from real_api import _run_step_task
    return _run_step_task(project, uid, step_id, cfg)


async def _run_one_project(uid: str, project_name: str, config: dict, batch_id: str,
                           sem: asyncio.Semaphore, drive_file_id: Optional[str] = None) -> None:
    """One PDF through the batch sequence (queued by the batch semaphore)."""
    try:
        async with sem:
            try:
                if drive_file_id:
                    _ingest_drive_project(uid, project_name, drive_file_id)
                _mark_project_autorun(uid, project_name, batch_id)
                entry = first_not_done_step(uid, project_name)
                if entry is None:
                    _mutate_project(uid, batch_id, project_name, "done")
                    return
                for sid in BATCH_SEQUENCE[BATCH_SEQUENCE.index(entry):]:
                    _mutate_project(uid, batch_id, project_name, "running", current_step=sid)
                    cfg = resolve_step_config(sid, config, uid, project_name)
                    task = asyncio.ensure_future(
                        _spawn_runtime_task(project_name, uid, sid, cfg))
                    job_manager.set_running(project_name, sid, task)
                    try:
                        await task
                    except asyncio.CancelledError:
                        _mutate_project(uid, batch_id, project_name, "cancelled")
                        raise
                    status = job_manager.get_status(project_name, sid)
                    if status in ("error", "stopped", "cancelled"):
                        _mutate_project(uid, batch_id, project_name, "error", error_step=sid)
                        return
                _mutate_project(uid, batch_id, project_name, "done")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[AUTORUN-BATCH] project {project_name} failed: {e}")
                _mutate_project(uid, batch_id, project_name, "error", error_message=str(e)[:200])
    except asyncio.CancelledError:
        raise


def run_batch_task(uid: str, batch_id: str) -> bool:
    """Spawn (or re-spawn after an interrupt) the batch task. Double-start safe.

    Returns False when the batch is already live, the manifest is missing, or
    there are no pending/running projects left to work on.
    """
    existing = _BATCH_TASKS.get(batch_id)
    if existing and not existing.done():
        return False
    m = read_manifest(uid, batch_id)
    if not m:
        return False
    pending = [p for p in m.get("projects", []) if p.get("state") in ("pending", "running")]
    if not pending:
        return False
    config = m.get("config_snapshot") or {}
    uid_, batch_id_ = uid, batch_id
    concurrency = asyncio.Semaphore(batch_concurrency())

    async def _runner():
        try:
            await asyncio.gather(*(
                _run_one_project(uid_, p["name"], config, batch_id_, concurrency,
                                 p.get("drive_file_id"))
                for p in pending))
        finally:
            _finalise_batch(uid_, batch_id_)
            _BATCH_TASKS.pop(batch_id_, None)

    _set_batch_state(uid_, batch_id_, "running")
    task = asyncio.ensure_future(_runner())
    _BATCH_TASKS[batch_id_] = task
    print(f"[AUTORUN-BATCH] batch {batch_id_} running for {uid_} — "
          f"{len(pending)} PDF(s) × concurrency {batch_concurrency()}")
    return True


def retry_project(uid: str, batch_id: str, project: str):
    """Per-PDF retry (resolved Q9) → (allowed, reason).

    Allowed only for projects whose state is error/cancelled/done_with_errors
    lineage (NOT done) while nothing of that project is running. The retry re-enters
    at first_not_done_step — done steps are skipped, the failed step re-runs.
    """
    m = read_manifest(uid, batch_id)
    if not m:
        return (False, "batch-not-found")
    proj = next((p for p in m.get("projects", []) if p.get("name") == project), None)
    if not proj:
        return (False, "project-not-in-batch")
    if proj.get("state") in ("pending", "running"):
        return (False, "already-running")
    if proj.get("state") == "done":
        return (False, "already-done")
    if _project_busy(project):
        return (False, "step-busy")

    proj["state"] = "pending"
    proj.pop("error_step", None)
    proj.pop("current_step", None)
    write_manifest(uid, m)

    config = m.get("config_snapshot") or {}
    # Parent batch task still running → its queue doesn't know this project;
    # a dedicated 1-slot worker runs just this PDF (max concurrency may exceed
    # 5 transiently for error+retries of other batches — bounded by API limits).
    parent = _BATCH_TASKS.get(batch_id)
    if parent and not parent.done():
        sem = asyncio.Semaphore(1)
        key = (batch_id, project)
        old = _RETRY_TASKS.get(key)
        if old and not old.done():
            return (False, "already-running")
        task = asyncio.ensure_future(
            _run_one_project(uid, project, config, batch_id, sem, proj.get("drive_file_id")))
        _RETRY_TASKS[key] = task
        task.add_done_callback(lambda _t, _k=key: _RETRY_TASKS.pop(_k, None))
    else:
        if not run_batch_task(uid, batch_id):
            return (False, "could-not-start")
    print(f"[AUTORUN-BATCH] retry queued for {project} (batch {batch_id})")
    return (True, "queued")


# ---------------------------------------------------------------------------
# Startup auto-resume (resolved Q12)
# ---------------------------------------------------------------------------

def _iterate_manifests():
    """Yield (uid, batch_id, manifest) — local FS first, then Storage-only copies."""
    seen = set()
    if OUTPUT_ROOT.is_dir():
        for uid_dir in OUTPUT_ROOT.iterdir():
            if not uid_dir.is_dir() or uid_dir.name.startswith(("_", ".")):
                continue
            bdir = uid_dir / "_batches"
            if not bdir.is_dir():
                continue
            for bd in bdir.iterdir():
                m = read_manifest(uid_dir.name, bd.name)
                if m:
                    seen.add((uid_dir.name, bd.name))
                    yield uid_dir.name, bd.name, m
    # Storage-only manifests (local FS wiped after a container restart)
    try:
        from storage_client import list_files
        for it in list_files(""):
            name = str(it.get("name", ""))
            parts = name.split("/")
            if len(parts) == 3 and parts[1] == "_batches" and \
                    (parts[0], parts[2]) not in seen:
                m = read_manifest(parts[0], parts[2])
                if m:
                    yield parts[0], parts[2], m
    except Exception as e:
        print(f"[AUTORUN-BATCH] Storage manifest scan failed: {e}")


def resume_interrupted_batches() -> int:
    """Re-launch every manifest with pending/running projects. Called by the API
    startup hook; job_manager is fresh (in-memory), so nothing is falsely running.

    Fully done/errored batches are NOT re-launched (errors await explicit retry).
    """
    if not batch_enabled():
        return 0
    started = 0
    for uid, batch_id, manifest in _iterate_manifests():
        states = [p.get("state") for p in manifest.get("projects", [])]
        if not any(s in ("pending", "running") for s in states):
            continue
        for p in manifest.get("projects", []):
            if p.get("state") == "running":
                p["state"] = "pending"    # fresh process — nothing is actually running
        write_manifest(uid, manifest)
        if run_batch_task(uid, batch_id):
            started += 1
    print(f"[AUTORUN-BATCH] auto-resume re-launched {started} interrupted batch(es)")
    return started
