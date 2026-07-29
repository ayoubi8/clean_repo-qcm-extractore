"""
storage_client.py — Supabase Storage abstraction layer.
All pipeline and API file I/O should go through these helpers.
Bucket: qcm-projects (private)
Storage path pattern: {user_id}/{project_name}/{...}
"""
import json
import mimetypes
import pickle
from supabase_client import get_supabase

BUCKET = "qcm-projects"


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def write_file(storage_path: str, content) -> None:
    """Upload text or bytes to Supabase Storage. Overwrites if exists."""
    sb = get_supabase()
    data = content.encode("utf-8") if isinstance(content, str) else content
    mime = _guess_mime(storage_path)
    try:
        sb.storage.from_(BUCKET).upload(
            storage_path, data,
            {"content-type": mime, "upsert": "true"}
        )
    except Exception:
        # Older supabase-py versions don't support upsert flag — remove first
        try:
            sb.storage.from_(BUCKET).remove([storage_path])
        except Exception:
            pass
        sb.storage.from_(BUCKET).upload(storage_path, data, {"content-type": mime})


def write_bytes_file(storage_path: str, content: bytes) -> None:
    """Alias for binary uploads."""
    write_file(storage_path, content)


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def read_file(storage_path: str) -> str:
    """Download a file and return its text content."""
    return read_bytes_file(storage_path).decode("utf-8")


def read_bytes_file(storage_path: str) -> bytes:
    """Download a file and return raw bytes."""
    sb = get_supabase()
    return sb.storage.from_(BUCKET).download(storage_path)


# ---------------------------------------------------------------------------
# Existence / listing / deletion
# ---------------------------------------------------------------------------

def file_exists(storage_path: str) -> bool:
    """Return True if the file exists in Supabase Storage."""
    try:
        read_bytes_file(storage_path)
        return True
    except Exception:
        return False


def list_files(prefix: str) -> list:
    """
    List files under a storage prefix.
    Returns list of metadata dicts from Supabase: [{name, id, metadata, ...}].
    Handles pagination.
    NOTE: this is a FLAT listing — sub-folders are returned as a single entry
    with `id: null`. Use list_files_recursive() when you need all files inside
    sub-folders (e.g. step output under `step1_extraction/accepted/page_*.txt`).
    """
    sb = get_supabase()
    all_items = []
    limit = 100
    offset = 0
    try:
        while True:
            page = sb.storage.from_(BUCKET).list(
                prefix,
                {"limit": limit, "offset": offset, "sortBy": {"column": "name", "order": "asc"}}
            ) or []
            all_items.extend(page)
            if len(page) < limit:
                break
            offset += limit
    except Exception as e:
        print(f"[STORAGE] list_files error: {e}")
    return all_items


def list_files_recursive(prefix: str) -> list:
    """
    Recursively list all FILES (objects with an `id`) under a storage prefix.
    Each returned item has its `name` rewritten to be the path RELATIVE to
    `prefix`, including sub-folder segments e.g. "accepted/page_1.txt".
    This mirrors what `Path.rglob("*")` yields relative to a local step_dir,
    so the API endpoints can use the same shape for local FS and Storage fallbacks.

    Folder entries (id == null) are recursed into, not returned.
    """
    if not prefix:
        return []
    sb = get_supabase()
    result = []
    root = prefix.rstrip("/")

    def _recurse(current_prefix: str):
        try:
            items = sb.storage.from_(BUCKET).list(
                current_prefix,
                {"limit": 100, "offset": 0, "sortBy": {"column": "name", "order": "asc"}}
            ) or []
        except Exception as e:
            print(f"[STORAGE] list_files_recursive error at {current_prefix}: {e}")
            return
        for item in items:
            name = item.get("name", "")
            if not name:
                continue
            absolute_path = f"{current_prefix}/{name}"
            if item.get("id"):
                # It's a file — rewrite name to be path relative to original prefix.
                rel_path = absolute_path[len(root) + 1:]
                new_item = dict(item)
                new_item["name"] = rel_path
                result.append(new_item)
            else:
                # Sub-folder — recurse.
                _recurse(absolute_path)

    _recurse(root)
    return result


def delete_prefix(prefix: str) -> None:
    """
    Recursively delete all objects under a storage prefix.
    Works around Supabase not having a native recursive delete.
    """
    sb = get_supabase()
    _recursive_delete(prefix.rstrip("/"), sb)


def _recursive_delete(prefix: str, sb) -> None:
    """Depth-first recursive delete of all objects under prefix."""
    try:
        items = sb.storage.from_(BUCKET).list(prefix) or []
        files_to_remove = []
        for item in items:
            name = item.get("name", "")
            if not name:
                continue
            full_path = f"{prefix}/{name}"
            # Items with an 'id' are files; items without are sub-folders
            if item.get("id"):
                files_to_remove.append(full_path)
            else:
                _recursive_delete(full_path, sb)

        if files_to_remove:
            sb.storage.from_(BUCKET).remove(files_to_remove)
    except Exception as e:
        print(f"[STORAGE] _recursive_delete error at '{prefix}': {e}")


# ---------------------------------------------------------------------------
# Signed / public URL helpers
# ---------------------------------------------------------------------------

def get_signed_url(storage_path: str, expires_in: int = 3600) -> str:
    """Return a time-limited signed URL for a private bucket object."""
    sb = get_supabase()
    res = sb.storage.from_(BUCKET).create_signed_url(storage_path, expires_in)
    # supabase-py returns either a dict or an object depending on version
    if isinstance(res, dict):
        return (
            res.get("signedURL")
            or res.get("signedUrl")
            or (res.get("data") or {}).get("signedUrl", "")
        )
    # Newer client may return an object with .signed_url
    return getattr(res, "signed_url", str(res))


# ---------------------------------------------------------------------------
# Pickle helpers (for Google OAuth token)
# ---------------------------------------------------------------------------

def write_pickle(storage_path: str, obj) -> None:
    """Pickle an object and upload to Supabase Storage."""
    write_bytes_file(storage_path, pickle.dumps(obj))


def read_pickle(storage_path: str):
    """Download bytes from Supabase Storage and unpickle."""
    return pickle.loads(read_bytes_file(storage_path))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _guess_mime(path: str) -> str:
    mt, _ = mimetypes.guess_type(path)
    return mt or "application/octet-stream"
