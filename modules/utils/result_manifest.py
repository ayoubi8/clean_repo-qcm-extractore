"""Pure helpers for the persistence layer (PERSISTENCE_FIX_PLAN PR-1).

These functions build the metadata we persist to the Supabase SQL
`step_results` table after each pipeline step. The actual artifact BYTES
live in Supabase Storage (the `storage_prefix`); we only record a
manifest + a small payload here so that list/status/listing endpoints
work after a container restart without walking Storage.

Kept dependency-free (stdlib only) so it can be unit-tested without
hitting Supabase or the filesystem layout of a running container.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List

# Skip hashing files above this size to keep the post-step write fast.
# 50 MB — step8_matches.xlsx sometimes approaches this for huge books.
_HASH_SIZE_LIMIT = 50 * 1024 * 1024


_KIND_BY_SUFFIX = {
    ".json": "json",
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".csv": "csv",
    ".txt": "text",
    ".pickle": "pickle",
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
}


def _kind_for(path: Path) -> str:
    return _KIND_BY_SUFFIX.get(path.suffix.lower(), "other")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_file_manifest(local_dir: Path, storage_prefix: str) -> List[Dict]:
    """Walk `local_dir` and emit one manifest entry per file.

    Each entry: {"path": "<rel>", "size_bytes": int, "sha256": str|"",
                 "kind": "json|xlsx|text|..."}.
    Files above _HASH_SIZE_LIMIT get an empty `sha256` (we still record
    size + path so listing works). Empty / non-file entries are skipped.
    Relative paths use forward slashes regardless of OS.
    """
    if local_dir is None or not Path(local_dir).exists():
        return []
    base = Path(local_dir)
    manifest: List[Dict] = []
    for f in sorted(base.rglob("*")):
        if not f.is_file():
            continue
        try:
            size = f.stat().st_size
        except OSError:
            continue
        rel = str(f.relative_to(base)).replace("\\", "/")
        sha = ""
        if 0 < size <= _HASH_SIZE_LIMIT:
            try:
                sha = _sha256_bytes(f.read_bytes())
            except Exception:
                sha = ""
        manifest.append({
            "path": rel,
            "size_bytes": int(size),
            "sha256": sha,
            "kind": _kind_for(f),
        })
    return manifest


def summarize_step(step_id: str, step_dir: Path, badge_stats: Dict | None = None) -> Dict:
    """Return a small JSONB-serialisable `payload` for the `step_results` row.

    Combines the per-badge stats (pages_ok, qcms, etc. produced by
    `_compute_step_badge`) with a few derived counts that help the listing
    endpoints render a step tile without reading the files.
    """
    payload: Dict = {}
    if badge_stats:
        try:
            payload.update(json.loads(json.dumps(badge_stats)))
        except Exception:
            pass
    try:
        sd = Path(step_dir) if step_dir is not None else None
    except Exception:
        sd = None
    if sd is None or not sd.exists():
        return payload
    file_count = 0
    total_bytes = 0
    for f in sd.rglob("*"):
        if f.is_file():
            file_count += 1
            try:
                total_bytes += f.stat().st_size
            except OSError:
                pass
    payload["file_count"] = file_count
    payload["total_bytes"] = int(total_bytes)
    return payload