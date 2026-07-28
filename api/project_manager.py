import json
import os
from pathlib import Path
from datetime import datetime

STEP_FOLDER_MAP = {
    "1": "step1_extraction", "1.5": "step1_extraction", "1.6": "step1_extraction",
    "2": "step2_qcm", "3": "step3_metadata", "4": "step4_format",
    "5": "step5_json", "6": "step6_corrections", "7": "step7_categories", "8": "step8_matches",
}


def _is_missing_column_error(err: any, column: str = "last_activity_at") -> bool:
    """Supabase/PostgREST emits the column-not-found error either as
    'column projects.<column> does not exist' (42703) or as
    'Could not find the <column> column of <table> in the schema cache' (PGRST204).
    Returns True if `err` matches either shape, so callers can retry a slimmed
    payload that omits the column and degrades gracefully until the migration runs.
    """
    try:
        msg = str(err)
        needle = column
        return (
            f"column projects.{needle} does not exist" in msg
            or f"Could not find the '{needle}' column of 'projects'" in msg
        )
    except Exception:
        return False

# NOTE: sys.path manipulation needed because modules/ is at /app/modules
import sys
sys.path.insert(0, "/app")

from modules.utils.project_context import ProjectContext
from modules.utils.cost_tracker import CostTracker
from auth import get_db_user_id

# In-memory registry: project_name → {"context": ..., "tracker": ...}
_registry = {}

def get_or_create(project_name: str, email: str) -> dict:
    registry_key = f"{email}/{project_name}"
    if registry_key not in _registry:
        context = ProjectContext(registry_key)
        tracker = CostTracker()
        
        # Restore costs if file exists
        cost_path = Path(f"/app/output/{email}/{project_name}/total_costs.json")
        if cost_path.exists():
            tracker.load(str(cost_path))
            
        _registry[registry_key] = {"context": context, "tracker": tracker}
    return _registry[registry_key]

def _build_project_from_storage(email: str, pname: str, meta: dict) -> dict:
    local_pdir = Path(f"/app/output/{email}/{pname}")
    proj = {
        "name": pname,
        "last_step": 0,
        "last_modified": meta.get("created_at") or meta.get("lastUpdated") or meta.get("updated_at") or "",
        "total_tokens": 0,
        "pdf_path": ""
    }

    # Try to list files in f"{email}/{pname}/" to find project.json and get its metadata created_at timestamp
    try:
        from storage_client import list_files
        p_files = list_files(f"{email}/{pname}/")
        pjson_item = next((x for x in p_files if x.get("name") == "project.json"), None)
        if pjson_item:
            proj["last_modified"] = pjson_item.get("created_at") or pjson_item.get("updated_at") or ""
    except Exception as e:
        print(f"[_build_project_from_storage] failed to get project.json metadata for {pname}: {e}")

    # Restore project.json locally so pipeline works
    try:
        from storage_client import read_file
        pjson_text = read_file(f"{email}/{pname}/project.json")
        local_pdir.mkdir(parents=True, exist_ok=True)
        (local_pdir / "project.json").write_text(pjson_text)
        pdata = json.loads(pjson_text)
        proj["pdf_path"] = pdata.get("pdf_path", "")
    except Exception:
        pass
        
    # Restore costs locally
    try:
        from storage_client import read_file
        costs_text = read_file(f"{email}/{pname}/total_costs.json")
        local_pdir.mkdir(parents=True, exist_ok=True)
        (local_pdir / "total_costs.json").write_text(costs_text)
        costs = json.loads(costs_text)
        summary = costs.get("summary", costs)
        proj["total_tokens"] = summary.get("total_tokens", 0)
    except Exception:
        pass

    # Check last step
    STEP_CHECK_ORDER = [
        (8, "8"), (7, "7"), (6, "6"), (5, "5"),
        (4, "4"), (3, "3"), (2, "2"), (1.6, "1.6"),
        (1.5, "1.5"), (1, "1"),
    ]
    for snum, sid in STEP_CHECK_ORDER:
        if step_output_exists(pname, sid, email):
            proj["last_step"] = snum
            break
            
    return proj


def list_projects(email: str) -> list:
    projects = []
    seen = set()
    
    # 1. DB query with retry (RC-1).
    # Resilient to a missing `last_activity_at` column: retry a slim SELECT
    # that selects/orders by `created_at` only so list_projects keeps working
    # until the operator runs migration.sql (which adds the column).
    db_projects = []
    for attempt in range(2):
        try:
            from supabase_client import get_supabase
            sb = get_supabase()
            db_uid = get_db_user_id({"id": email})
            res = (sb.table("projects")
                     .select("name,created_at,last_activity_at,pdf_storage_path")
                     .eq("user_id", db_uid)
                     .order("last_activity_at", desc=True)
                     .order("created_at", desc=True)
                     .execute())
            db_projects = res.data or []
            break
        except Exception as e:
            print(f"[list_projects] DB query attempt {attempt+1} failed: {e}")
            # If the column is genuinely missing in the live DB schema,
            # retry without last_activity_at so the app stays usable.
            if _is_missing_column_error(e, "last_activity_at"):
                try:
                    from supabase_client import get_supabase
                    sb = get_supabase()
                    db_uid = get_db_user_id({"id": email})
                    res = (sb.table("projects")
                             .select("name,created_at,pdf_storage_path")
                             .eq("user_id", db_uid)
                             .order("created_at", desc=True)
                             .execute())
                    db_projects = res.data or []
                    print("[list_projects] falling back to created_at (last_activity_at missing)")
                    break
                except Exception as fe:
                    print(f"[list_projects] created_at fallback failed: {fe}")
                    db_projects = []
            elif attempt == 1:
                db_projects = []

    # Process DB projects
    if db_projects:
        for row in db_projects:
            pname = row["name"]
            seen.add(pname)
            pdf_path = row.get("pdf_storage_path", "")
            last_modified = row.get("last_activity_at") or row.get("created_at", "")
            
            # Check local FS first for last_step and tokens (fast path)
            local_pdir = Path(f"/app/output/{email}/{pname}")
            last_step = 0
            total_tokens = 0
            
            STEP_ORDER = [
                (8, "step8_matcher"), (7, "step7_categories"), (6, "step6_corrections"),
                (5, "step5_json"), (4, "step4_format"), (3, "step3_metadata"), (2, "step2_qcm"),
                (1.6, "step1_extraction"), (1.5, "step1_extraction"), (1, "step1_extraction"),
            ]
            
            if local_pdir.exists():
                for step_num, folder_name in STEP_ORDER:
                    folder_path = local_pdir / folder_name
                    if folder_path.exists() and any(folder_path.iterdir()):
                        last_step = step_num
                        break

            # If not found locally, probe Storage
            if last_step == 0:
                STEP_CHECK_ORDER = [
                    (8, "8"), (7, "7"), (6, "6"), (5, "5"),
                    (4, "4"), (3, "3"), (2, "2"), (1.6, "1.6"),
                    (1.5, "1.5"), (1, "1"),
                ]
                for snum, sid in STEP_CHECK_ORDER:
                    if step_output_exists(pname, sid, email):
                        last_step = snum
                        break

            # Restore project.json locally so pipeline works
            if not local_pdir.exists() or not (local_pdir / "project.json").exists():
                try:
                    from storage_client import read_file
                    pjson_text = read_file(f"{email}/{pname}/project.json")
                    local_pdir.mkdir(parents=True, exist_ok=True)
                    (local_pdir / "project.json").write_text(pjson_text)
                    if not pdf_path:
                        pdata = json.loads(pjson_text)
                        pdf_path = pdata.get("pdf_path", "")
                except Exception:
                    pass

            # Find tokens
            cost_file = local_pdir / "total_costs.json"
            if cost_file.exists():
                try:
                    data = json.loads(cost_file.read_text())
                    summary = data.get("summary", data)
                    total_tokens = summary.get("total_tokens", 0)
                except:
                    pass
            else:
                # Restore costs locally
                try:
                    from storage_client import read_file
                    costs_text = read_file(f"{email}/{pname}/total_costs.json")
                    local_pdir.mkdir(parents=True, exist_ok=True)
                    (local_pdir / "total_costs.json").write_text(costs_text)
                    costs = json.loads(costs_text)
                    summary = costs.get("summary", costs)
                    total_tokens = summary.get("total_tokens", 0)
                except Exception:
                    pass

            projects.append({
                "name": pname,
                "last_step": last_step,
                "last_modified": last_modified,
                "total_tokens": total_tokens,
                "pdf_path": pdf_path
            })

    # 2. Merge: discover any project in Storage missing from DB and self-heal
    try:
        from storage_client import list_files
        items = list_files(f"{email}/")
        storage_names = set()
        for it in items:
            name = it.get("name", "")
            parts = name.split("/")
            if parts and parts[0] and not parts[0].startswith(("_", ".", "global")):
                storage_names.add(parts[0])

        missing = storage_names - seen
        for pname in sorted(missing):
            proj = _build_project_from_storage(email, pname, {})
            projects.append(proj)
            seen.add(pname)
            # Self-heal: upsert missing row so future calls hit DB first.
            # Resilient to a missing `last_activity_at` column: drop it from
            # the upsert payload and retry once so the self-heal still registers
            # the project (using created_at as a stand-in timestamp).
            try:
                sb = get_supabase()
                row = {
                    "user_id": get_db_user_id({"id": email}),
                    "name": pname,
                    "pdf_storage_path": proj.get("pdf_path", ""),
                    "created_at": proj.get("last_modified") or datetime.utcnow().isoformat(),
                    "last_activity_at": proj.get("last_modified") or datetime.utcnow().isoformat(),
                }
                sb.table("projects").upsert(row, on_conflict="user_id,name").execute()
            except Exception as ue:
                if _is_missing_column_error(ue, "last_activity_at"):
                    try:
                        sb = get_supabase()
                        sb.table("projects").upsert({
                            "user_id": get_db_user_id({"id": email}),
                            "name": pname,
                            "pdf_storage_path": proj.get("pdf_path", ""),
                            "created_at": proj.get("last_modified") or datetime.utcnow().isoformat(),
                        }, on_conflict="user_id,name").execute()
                        print(f"[list_projects] self-heal registered {pname} without last_activity_at (column missing)")
                    except Exception as ue2:
                        print(f"[list_projects] self-heal upsert failed for {pname}: {ue2}")
                else:
                    print(f"[list_projects] self-heal upsert failed for {pname}: {ue}")
    except Exception as e:
        print(f"[list_projects] Storage merge error: {e}")

    # 3. Third-tier fallback: Local filesystem scan if STILL no projects
    # (e.g. offline container with local data)
    if not projects:
        output_dir = Path(f"/app/output/{email}")
        if output_dir.exists():
            for d in sorted(output_dir.iterdir()):
                if not d.is_dir() or d.name.startswith(("_", ".", "global")):
                    continue
                
                pname = d.name
                last_step = 0
                STEP_ORDER = [
                    (8, "step8_matcher"), (7, "step7_categories"), (6, "step6_corrections"),
                    (5, "step5_json"), (4, "step4_format"), (3, "step3_metadata"), (2, "step2_qcm"),
                    (1.6, "step1_extraction"), (1.5, "step1_extraction"), (1, "step1_extraction"),
                ]
                for step_num, folder_name in STEP_ORDER:
                    folder_path = d / folder_name
                    if folder_path.exists() and any(folder_path.iterdir()):
                        last_step = step_num
                        break

                total_tokens = 0
                cost_file = d / "total_costs.json"
                if cost_file.exists():
                    try:
                        data = json.loads(cost_file.read_text())
                        summary = data.get("summary", data)
                        total_tokens = summary.get("total_tokens", 0)
                    except:
                        pass

                pdf_path = ""
                project_json = d / "project.json"
                if project_json.exists():
                    try:
                        pdata = json.loads(project_json.read_text())
                        pdf_path = pdata.get("pdf_path", "")
                    except:
                        pass

                projects.append({
                    "name": pname,
                    "last_step": last_step,
                    "last_modified": datetime.fromtimestamp(d.stat().st_mtime).isoformat() + "Z",
                    "total_tokens": total_tokens,
                    "pdf_path": pdf_path
                })

    # Final sort (descending by last_modified)
    projects.sort(key=lambda p: p.get("last_modified") or "", reverse=True)
    return projects

def step_output_exists(project_name: str, step_id: str, email: str) -> bool:
    """
    Check whether output files exist for a given step.

    Priority:
    1. Local container filesystem (fast — no network call).
    2. Supabase Storage fallback (handles container restart where local FS was wiped).
    """
    folder_name = STEP_FOLDER_MAP.get(str(step_id), f"step{step_id}")
    step_dir = Path(f"/app/output/{email}/{project_name}/{folder_name}")

    # ── Fast path: local FS ─────────────────────────────────────────────────
    if step_dir.exists() and any(step_dir.iterdir()):
        return True

    # ── Fallback: Supabase Storage (FIX-01) ─────────────────────────────────
    # Only reach here if local FS is empty or the container was restarted.
    try:
        from storage_client import list_files
        prefix = f"{email}/{project_name}/{folder_name}"
        items = list_files(prefix)
        # Items with an 'id' field are real files; items without are sub-folders.
        return any(f.get("id") for f in items)
    except Exception as e:
        print(f"[step_output_exists] Storage fallback failed for {email}/{project_name}/{folder_name}: {e}")
        return False

def get_weekly_costs(email: str = None) -> dict:
    """Aggregate total_costs.json files across projects, grouped by week."""
    weeks = {}
    if email:
        search_dirs = [Path(f"/app/output/{email}")]
    else:
        # Global aggregation for admin stats if needed, or just iterate all users
        output_root = Path("/app/output")
        search_dirs = [d for d in output_root.iterdir() if d.is_dir() and not d.name.startswith(".")]

    for base_dir in search_dirs:
        if not base_dir.exists(): continue
        for proj_dir in base_dir.iterdir():
            if not proj_dir.is_dir(): continue
            cost_file = proj_dir / "total_costs.json"
            if cost_file.exists():
                # Use file modification time as the reference for the cost record
                mtime = datetime.fromtimestamp(cost_file.stat().st_mtime)
                # Format: 2026-W14
                week_key = mtime.strftime("%Y-W%U")
                try:
                    data = json.loads(cost_file.read_text())
                    # Support both new format {models, steps, summary} and old flat format
                    summary = data.get("summary", data)
                    cost = summary.get("total_cost", 0)
                    
                    if week_key not in weeks:
                        weeks[week_key] = {"cost": 0, "projects": []}
                    
                    weeks[week_key]["cost"] += cost
                    if proj_dir.name not in weeks[week_key]["projects"]:
                        weeks[week_key]["projects"].append(proj_dir.name)
                except:
                    pass
    return weeks
