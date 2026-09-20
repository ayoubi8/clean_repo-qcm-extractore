"""step_cache.py — Phase 5 server cache for step-result checking
(history-progress-cache plan §Phase5).

One process-level TTL cache in front of the expensive result lookups:
the SQL `step_results` round-trips and the Supabase Storage recursive walks
behind GET /projects/{name}/steps/{id}/status and /output, plus the autorun
engine's done-ness probes (first_not_done_step).

Key = (uid, project, step_id). Fields stored per entry:
    status         last known status ("idle"/"running"/"done"/"error"/…)
    output_exists  bool
    files          output manifest rows (same shape the /output route returns)

Correctness contract (Q-C1): the TTL (~180s band 120–300, single knob
STEP_CACHE_TTL) is only a safety net — every mutation path (run start/finish,
output delete, sheets sync, retry/resume) calls invalidate() explicitly, so a
long TTL is safe. The /autorun/batches merge is response-only and never touches
this cache. Tests populate/inspect via get()/put()/invalidate()/clear().
"""
import os
import threading
import time

from typing import Optional

_LOCK = threading.Lock()
_CACHE: dict = {}          # key → {"status", "output_exists", "files", "expires"}


def ttl_seconds() -> int:
    """Single TTL knob — server AND client use the same value (Q-C1)."""
    raw = str(os.environ.get("STEP_CACHE_TTL", "180")).strip()
    try:
        ttl = int(raw)
    except (TypeError, ValueError):
        ttl = 180
    return max(120, min(ttl, 300))


def get(uid: str, project: str, step_id) -> Optional[dict]:
    """Fresh entry dict (copy) or None. Never raises."""
    key = _key(uid, project, step_id)
    now = time.time()
    with _LOCK:
        entry = _CACHE.get(key)
        if entry and entry.get("expires", 0) > now:
            return dict(entry)
        _CACHE.pop(key, None)
    return None


def put(uid: str, project: str, step_id, status: Optional[str] = None,
        output_exists: Optional[bool] = None, files: Optional[list] = None) -> None:
    """Merge fields into the entry and refresh its TTL. Never raises."""
    key = _key(uid, project, step_id)
    now = time.time()
    with _LOCK:
        entry = dict(_CACHE.get(key) or {})
        if status is not None:
            entry["status"] = status
        if output_exists is not None:
            entry["output_exists"] = output_exists
        if files is not None:
            entry["files"] = files
        entry["expires"] = now + max(120, min(ttl_seconds(), 300))
        _CACHE[key] = entry


def invalidate(uid: str, project: Optional[str] = None, step=None) -> None:
    """Explicit invalidation (the correctness mechanism behind the long TTL).

    (uid)              → wipe the user's whole cache (batch ops)
    (uid, project)     → wipe one project (retry/resume, sheets sync)
    (uid, project, st) → one step (delete route)
    """
    with _LOCK:
        if project is None:
            for k in [k for k in _CACHE if k[0] == uid]:
                _CACHE.pop(k, None)
        elif step is None:
            for k in [k for k in _CACHE if k[0] == uid and k[1] == project]:
                _CACHE.pop(k, None)
        else:
            _CACHE.pop(_key(uid, project, step), None)


def clear() -> None:
    """Test hook / full wipe (deploy restart clears naturally)."""
    with _LOCK:
        _CACHE.clear()


def _key(uid: str, project: str, step) -> tuple:
    return (uid, project, str(step))
