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
    """
    sb = get_supabase()
    try:
        return sb.storage.from_(BUCKET).list(prefix) or []
    except Exception:
        return []


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
