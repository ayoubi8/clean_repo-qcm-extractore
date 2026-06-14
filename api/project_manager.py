import json
import os
from pathlib import Path
from datetime import datetime

STEP_FOLDER_MAP = {
    "1": "step1_extraction", "1.5": "step1_extraction", "1.6": "step1_extraction",
    "2": "step2_qcm", "3": "step3_metadata", "4": "step4_format",
    "5": "step5_json", "6": "step6_corrections", "7": "step7_categories", "8": "step8_matches",
}

# NOTE: sys.path manipulation needed because modules/ is at /app/modules
import sys
sys.path.insert(0, "/app")

from modules.utils.project_context import ProjectContext
from modules.utils.cost_tracker import CostTracker

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

def list_projects(email: str) -> list:
    projects = []
    output_dir = Path(f"/app/output/{email}")

    # ── Local filesystem (fast path) ────────────────────────────────────────
    if output_dir.exists():
        for d in sorted(output_dir.iterdir()):
            if not d.is_dir() or d.name.startswith(("_", ".", "global")):
                continue

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
                "name": d.name,
                "last_step": last_step,
                "last_modified": datetime.fromtimestamp(d.stat().st_mtime).isoformat() + "Z",
                "total_tokens": total_tokens,
                "pdf_path": pdf_path
            })

    # ── Supabase Storage fallback (container restarted — local FS is empty) ─
    if not projects:
        try:
            from storage_client import list_files, read_file
            items = list_files(f"{email}/")
            project_names: set = set()
            for item in items:
                name = item.get("name", "")
                parts = name.split("/")
                if parts and parts[0] and not parts[0].startswith(("_", ".", "global")):
                    project_names.add(parts[0])

            for pname in sorted(project_names):
                proj: dict = {
                    "name": pname, "last_step": 0,
                    "last_modified": "", "total_tokens": 0, "pdf_path": ""
                }
                # Restore project.json locally so subsequent ops work
                try:
                    pjson_text = read_file(f"{email}/{pname}/project.json")
                    local_pdir = Path(f"/app/output/{email}/{pname}")
                    local_pdir.mkdir(parents=True, exist_ok=True)
                    (local_pdir / "project.json").write_text(pjson_text)
                    pdata = json.loads(pjson_text)
                    proj["pdf_path"] = pdata.get("pdf_path", "")
                except Exception:
                    pass
                # Restore costs locally
                try:
                    costs_text = read_file(f"{email}/{pname}/total_costs.json")
                    local_pdir = Path(f"/app/output/{email}/{pname}")
                    local_pdir.mkdir(parents=True, exist_ok=True)
                    (local_pdir / "total_costs.json").write_text(costs_text)
                    costs = json.loads(costs_text)
                    summary = costs.get("summary", costs)
                    proj["total_tokens"] = summary.get("total_tokens", 0)
                except Exception:
                    pass
                projects.append(proj)
            if projects:
                print(f"[list_projects] Restored {len(projects)} project(s) from Supabase for {email}")
        except Exception as e:
            print(f"[list_projects] Supabase fallback error: {e}")

    return projects



def step_output_exists(project_name: str, step_id: str, email: str) -> bool:
    folder_name = STEP_FOLDER_MAP.get(str(step_id), f"step{step_id}")
    step_dir = Path(f"/app/output/{email}/{project_name}/{folder_name}")
    if not step_dir.exists():
        return False
    # If it's a directory, check if it has files
    return any(step_dir.iterdir())

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
