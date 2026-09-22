"""
tags.py — region + module tagging for projects and batches (tags-search plan).

- REGION_TAGS: fixed vocabulary with colors, single source of truth for the
  frontend via GET /env/tags.
- Tags shape on rows: jsonb list like [{"key": "region", "value": "oran"},
  {"key": "module", "value": "anatomie"}].
- All helpers degrade gracefully when api/migration.sql hasn't been applied:
  creation still works (warning printed), listing just omits tags.
"""
import threading


REGION_TAGS = [
    {"key": "region", "value": "oran",    "label": "Oran",    "color": "orange"},
    {"key": "region", "value": "mosta",   "label": "Mosta",   "color": "green"},
    {"key": "region", "value": "tlemcen", "label": "Tlemcen", "color": "brown"},
]

VALID_REGION_VALUES = {t["value"] for t in REGION_TAGS}

_tags_column_ok: dict = {}      # {"projects": True/False}
_tags_probe_lock = threading.Lock()


def region_value(body: dict) -> str:
    """Extract + validate the required region tag from a create/upload body."""
    region = str((body or {}).get("region_tag") or "").strip().lower()
    if region not in VALID_REGION_VALUES:
        raise ValueError(f"region_tag must be one of {sorted(VALID_REGION_VALUES)}")
    return region


def module_value(body: dict) -> str:
    """Optional module tag — free text, sanitized."""
    module = str((body or {}).get("module_tag") or "").strip()
    return module[:60].lower() if module else ""


def build_tags(body: dict) -> list:
    """Build the tags jsonb payload from a request body (region REQUIRED)."""
    tags = []
    region = region_value(body)
    tags.append({"key": "region", "value": region})
    module = module_value(body)
    if module:
        tags.append({"key": "module", "value": module})
    return tags


def probe_tags_column(sb, table: str = "projects") -> bool:
    """Is the `tags` jsonb column migrated? Cached (idempotent probe)."""
    memo = _tags_column_ok.get(table)
    if memo is not None:
        return memo
    try:
        sb.table(table).select("tags").limit(1).execute()
        ok = True
    except Exception:
        ok = False
        print(f"[TAGS] column {table}.tags missing — run api/migration.sql "
              f"(creations will register tags once migrated)")
    _tags_column_ok[table] = ok
    return ok
