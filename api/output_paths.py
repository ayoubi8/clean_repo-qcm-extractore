"""Safe paths for step output files (plan frontend-routes-and-switch-lag §10.3 S1).

Every endpoint that reads, serves, uploads or deletes a step output file takes
a filename from the URL. Joined naively to the user's folder, a name such as
`../../<other-user>/<project>/step6_corrections/x.json` escapes it. These
helpers resolve the path and refuse anything that leaves the user's own
project folder — for the local file AND the matching Storage key.
"""
from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import Tuple

from fastapi import HTTPException

# Step id -> output folder (the single copy; endpoints used 7 duplicates).
STEP_FOLDERS = {
    "1": "step1_extraction", "1.5": "step1_extraction", "1.6": "step1_extraction",
    "2": "step2_qcm", "3": "step3_metadata", "4": "step4_format",
    "5": "step5_json", "6": "step6_corrections", "7": "step7_categories", "8": "step8_matches",
}


def output_root() -> Path:
    return Path(os.environ.get("QCM_OUTPUT_ROOT", "/app/output"))


def step_folder(step_id: str) -> str:
    return STEP_FOLDERS.get(str(step_id), f"step{step_id}")


def _bad(detail: str = "Invalid output filename") -> HTTPException:
    return HTTPException(status_code=400, detail=detail)


def _clean_segment(value: str, what: str) -> str:
    """A single path segment: no separators, not '.' or '..', not empty."""
    v = str(value or "")
    if (not v.strip() or v in (".", "..") or "/" in v or "\\" in v
            or "\x00" in v):
        raise _bad(f"Invalid {what}")
    return v


def _clean_relative(rel: str) -> PurePosixPath:
    """A relative file path inside a folder: no absolute path, no '..',
    no drive letters / backslashes, no empty name."""
    raw = str(rel or "")
    if not raw.strip() or "\x00" in raw or "\\" in raw or ":" in raw:
        raise _bad()
    p = PurePosixPath(raw)
    if p.is_absolute() or any(part in ("..", ".") for part in p.parts) or not p.parts:
        raise _bad()
    return p


def _inside(base: Path, target: Path) -> Path:
    """Resolve and check target stays inside base (symlinks included)."""
    base_r = base.resolve()
    tgt_r = target.resolve()
    try:
        tgt_r.relative_to(base_r)
    except ValueError:
        raise _bad()
    return target


def safe_output_path(user_id: str, project: str, step_id: str, filename: str) -> Tuple[Path, str]:
    """(local path, storage key) of one current-output file of a step."""
    uid = _clean_segment(user_id, "user")
    proj = _clean_segment(project, "project name")
    rel = _clean_relative(filename)
    folder = step_folder(step_id)
    base = output_root() / uid / proj / folder
    local = _inside(base, base / Path(*rel.parts))
    return local, f"{uid}/{proj}/{folder}/{rel.as_posix()}"


def safe_history_path(user_id: str, project: str, step_id: str, run_id: str,
                      filename: str) -> Tuple[Path, str]:
    """(local path, storage key) of a file of one archived run (or 'current')."""
    if run_id == "current":
        return safe_output_path(user_id, project, step_id, filename)
    uid = _clean_segment(user_id, "user")
    proj = _clean_segment(project, "project name")
    run = _clean_segment(run_id, "run id")
    step = _clean_segment(str(step_id), "step")
    rel = _clean_relative(filename)
    base = output_root() / uid / proj / "_history" / f"step{step}" / run
    local = _inside(base, base / Path(*rel.parts))
    return local, f"{uid}/{proj}/_history/step{step}/{run}/{rel.as_posix()}"
