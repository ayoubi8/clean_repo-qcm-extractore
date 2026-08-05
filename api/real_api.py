import asyncio
import builtins
import json
import sys
import os
import time
from datetime import datetime
import yaml
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, BackgroundTasks, HTTPException, UploadFile, File, Depends, Request, Header

from fastapi.responses import FileResponse, RedirectResponse
import shutil
import mimetypes
import pickle
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
from googleapiclient.discovery import build
from fastapi.middleware.cors import CORSMiddleware

load_dotenv("/app/.env" if Path("/app").exists() else ".env", override=False)
load_dotenv(override=False)


# Setup path to include the root /app (so modules can be imported)
sys.path.insert(0, "/app")

from job_manager import job_manager
from log_capture import LogCapture
from project_manager import get_or_create, list_projects, step_output_exists, get_weekly_costs
from env_manager import read_env, mask, write_env_keys, EDITABLE_KEYS
from auth import (get_current_user, require_admin, load_users,
                     find_user_by_email, hash_password, verify_password, rehash_if_legacy,
                     create_access_token, add_user, update_user_field, delete_user,
                     check_rate_limit,
                     create_refresh_token, verify_and_rotate_refresh_token, revoke_all_refresh_tokens,
                     ADMIN_EMAIL, ADMIN_PASSWORD, ensure_admin_exists, get_db_user_id)
import uuid
from supabase_client import get_supabase
from storage_client import (
    write_file, write_bytes_file, read_file, read_bytes_file,
    file_exists, list_files, list_files_recursive, delete_prefix, get_signed_url,
    write_pickle, read_pickle
)

app = FastAPI(title="QCM Extractor API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
async def _startup():
    """Seed admin user and decode Google credentials on every container start."""
    ensure_admin_exists()

    # Restore .env from Supabase Storage for persistence across restarts
    try:
        if file_exists("config/.env"):
            env_content = read_file("config/.env")
            dest_path = Path("/app/.env") if Path("/app").exists() else Path(__file__).parent / ".env"
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_text(env_content)
            print("[STARTUP] ✅ Restored .env from Supabase Storage")
            load_dotenv(str(dest_path), override=True)
            print("[STARTUP] ✅ Reloaded env variables with override=True")
    except Exception as e:
        print(f"[STARTUP] ❌ Failed to restore .env from Supabase Storage: {e}")


    # Decode Google OAuth client secret from base64 env var → write to disk
    google_secret_b64 = os.environ.get("GOOGLE_CLIENT_SECRET_B64", "")
    if google_secret_b64:
        import base64
        try:
            secret_bytes = base64.b64decode(google_secret_b64)
            secret_path = Path(GOOGLE_CLIENT_SECRET_PATH)
            secret_path.parent.mkdir(parents=True, exist_ok=True)
            secret_path.write_bytes(secret_bytes)
            print(f"[STARTUP] ✅ Google client secret written to {GOOGLE_CLIENT_SECRET_PATH}")
        except Exception as e:
            print(f"[STARTUP] ❌ Could not decode GOOGLE_CLIENT_SECRET_B64: {e}")
    else:
        print("[STARTUP] ⚠️ GOOGLE_CLIENT_SECRET_B64 not set — Google Sheets integration will NOT work")

    # Log Google Sheets readiness
    print(f"[STARTUP] Google OAuth redirect URI: {GOOGLE_REDIRECT_URI}")
    if Path(GOOGLE_CLIENT_SECRET_PATH).exists():
        print(f"[STARTUP] ✅ Google client secret file exists at {GOOGLE_CLIENT_SECRET_PATH}")
    else:
        print(f"[STARTUP] ❌ Google client secret file MISSING at {GOOGLE_CLIENT_SECRET_PATH}")

    # PERSISTENCE_FIX_PLAN PR-1: probe for the step_results table so the
    # operator gets one clear log line telling them to run the new
    # migration. Writes are wrapped in try/except anyway, so a missing
    # table degrades gracefully — this probe just makes the gap visible.
    try:
        sb = get_supabase()
        try:
            sb.table("step_results").select("id").limit(1).execute()
            print("[STARTUP] ✅ step_results table present — run metadata will persist to SQL")
        except Exception as _e:
            print(f"[STARTUP] ⚠️ step_results table missing — run the new CREATE TABLE block in api/migration.sql via the Supabase SQL editor. Run metadata will stay in Storage/JSON until then. (probe error: {_e})")
    except Exception as _e2:
        print(f"[STARTUP] ⚠️ Supabase unreachable for step_results probe: {_e2}")


def _migrate_legacy_projects():
    """Move folders from /app/output/ to /app/output/admin_email/ if they aren't isolated yet."""
    base_dir = Path("/app/output")
    if not base_dir.exists():
        return

    admin_isolated_dir = base_dir / ADMIN_EMAIL
    migrated_count = 0

    try:
        for item in base_dir.iterdir():
            if not item.is_dir():
                continue

            name = item.name
            # Skip already isolated folders (contain @), special folders, and hidden folders
            if "@" in name or name == "_history" or name.startswith("."):
                continue

            # This is a legacy project folder. Move it to the admin's account.
            admin_isolated_dir.mkdir(parents=True, exist_ok=True)
            dest = admin_isolated_dir / name

            if dest.exists():
                print(f"[MIGRATION] Target '{dest}' already exists, skipping '{name}'")
                continue

            shutil.move(str(item), str(dest))
            print(f"[MIGRATION] Moved legacy project '{name}' to admin account ({ADMIN_EMAIL})")
            migrated_count += 1

        if migrated_count == 0:
            print("[MIGRATION] No legacy projects found, skipping.")
        else:
            print(f"[MIGRATION] Migration complete. {migrated_count} project(s) moved.")
    except Exception as e:
        print(f"[MIGRATION] Error during migration: {e}")

    # --- Phase 2: email-folder → UUID-folder migration ---
    try:
        users = load_users()
        for u in users:
            src = base_dir / u["email"]
            dst = base_dir / u["id"]
            if src.exists() and not dst.exists():
                src.rename(dst)
                print(f"[UUID-MIGRATION] {u['email']} → {u['id']}")
        # Admin folder
        admin_src = base_dir / ADMIN_EMAIL
        admin_dst = base_dir / "admin"
        if admin_src.exists() and not admin_dst.exists():
            admin_src.rename(admin_dst)
            print("[UUID-MIGRATION] admin email folder → admin")
    except Exception as e:
        print(f"[UUID-MIGRATION] Error: {e}")

def _backfill_projects_to_db():
    """
    One-time startup backfill. Enumerates all projects from Storage 
    for all registered users (including admin) and registers them in the projects DB table.
    """
    try:
        from auth import load_users, find_user_by_email, ADMIN_EMAIL
        from storage_client import list_files, read_file
        from supabase_client import get_supabase
        import json

        sb = get_supabase()
        
        # 1. Gather all users
        users = []
        try:
            users = load_users()
        except Exception as e:
            print(f"[BACKFILL] Failed to load users: {e}")
            return
            
        admin_rec = find_user_by_email(ADMIN_EMAIL)
        user_mappings = [] # list of dicts: {"storage_id": ..., "db_uid": ...}
        
        for u in users:
            user_mappings.append({"storage_id": u["id"], "db_uid": u["id"]})
        if admin_rec:
            # Check if admin is already added as its UUID or if we need to add the storage_id='admin' mapping
            user_mappings.append({"storage_id": "admin", "db_uid": admin_rec["id"]})
            
        print(f"[BACKFILL] Starting backfill scan for {len(user_mappings)} user(s)")

        for mapping in user_mappings:
            storage_id = mapping["storage_id"]
            db_uid = mapping["db_uid"]
            
            # List all storage items for this user
            try:
                items = list_files(f"{storage_id}/")
            except Exception as e:
                print(f"[BACKFILL] Failed to list files for {storage_id}: {e}")
                continue
                
            project_names = set()
            for item in items:
                name = item.get("name", "")
                parts = name.split("/")
                if parts and parts[0] and not parts[0].startswith(("_", ".", "global")):
                    project_names.add(parts[0])
                    
            for pname in project_names:
                # Retrieve pdf_path if project.json exists, and get its timestamp
                pdf_path = ""
                created_at = None
                try:
                    pjson_text = read_file(f"{storage_id}/{pname}/project.json")
                    pdata = json.loads(pjson_text)
                    pdf_path = pdata.get("pdf_path", "")

                    # Fetch project.json metadata to get actual created_at/last_activity_at
                    p_files = list_files(f"{storage_id}/{pname}/")
                    pjson_item = next((x for x in p_files if x.get("name") == "project.json"), None)
                    if pjson_item:
                        created_at = pjson_item.get("created_at") or pjson_item.get("updated_at") or pjson_item.get("metadata", {}).get("lastModified")
                except Exception:
                    pass
                    
                # Register in database projects table.
                # Resilient to a missing `last_activity_at` column: retry the
                # upsert with a slim payload (created_at only) so the project
                # still registers until the operator runs migration.sql.
                try:
                    upsert_row = {
                        "user_id": db_uid,
                        "name": pname,
                        "pdf_storage_path": pdf_path
                    }
                    if created_at:
                        upsert_row["created_at"] = created_at
                        upsert_row["last_activity_at"] = created_at
                    sb.table("projects").upsert(upsert_row, on_conflict="user_id,name").execute()
                    print(f"[BACKFILL] Registered project {pname} for user {storage_id}")
                except Exception as e:
                    if created_at and (
                        "column projects.last_activity_at does not exist" in str(e)
                        or "Could not find the 'last_activity_at' column of 'projects'" in str(e)
                    ):
                        try:
                            slim_row = {
                                "user_id": db_uid,
                                "name": pname,
                                "pdf_storage_path": pdf_path,
                                "created_at": created_at,
                            }
                            sb.table("projects").upsert(slim_row, on_conflict="user_id,name").execute()
                            print(f"[BACKFILL] Registered project {pname} for user {storage_id} (without last_activity_at — column missing)")
                        except Exception as e2:
                            print(f"[BACKFILL] DB register failed for {storage_id}/{pname}: {e2}")
                    else:
                        print(f"[BACKFILL] DB register failed for {storage_id}/{pname}: {e}")
                    
        print("[BACKFILL] Finished backfill scan.")
    except Exception as e:
        print(f"[BACKFILL] Error during backfill: {e}")

@app.on_event("startup")
async def startup_event():
    _migrate_legacy_projects()
    _backfill_projects_to_db()
    # PERSISTENCE_FIX_PLAN PR-4: prefetch the projects table into an
    # in-memory registry so the first /projects call after a restart is a
    # dict hit. One SELECT, no per-project round-trips.
    _eager_rebuild_registry()
    # PERSISTENCE_FIX_PLAN PR-4: backfill synthetic step_results rows for
    # pre-fix projects whose outputs already live in Storage but who never
    # re-ran since PR-1 was deployed. Idempotent — re-runs no-op.
    try:
        inserted = _backfill_step_results_from_storage()
        if inserted:
            print(f"[STARTUP] ✅ backfilled {inserted} synthetic step_results row(s) from Storage")
    except Exception as e:
        print(f"[STARTUP] ⚠️ step_results backfill failed: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """Best-effort flush of any in-progress step output to Supabase Storage."""
    print("[SHUTDOWN] Graceful shutdown triggered. Flushing in-progress jobs...")
    from project_manager import STEP_FOLDER_MAP
    for key, task in list(job_manager._jobs.items()):
        if not task.done():
            parts = key.split("-")
            if len(parts) >= 2:
                step_id = parts[-1]
                project = "-".join(parts[:-1])
                user_id = _job_user_ids.get(key, "admin")
                
                # Resolve folder name mapping
                s_id = "8" if step_id == "8-export" else step_id
                folder_name = STEP_FOLDER_MAP.get(str(s_id), f"step{s_id}")
                step_storage_prefix = f"{user_id}/{project}/{folder_name}"
                
                try:
                    print(f"[SHUTDOWN] Flushing step {step_id} folder for {project}...")
                    _upload_step_folder_to_storage(user_id, project, folder_name, step_storage_prefix)
                    
                    # Also flush total_costs.json
                    cost_path = f"/app/output/{user_id}/{project}/total_costs.json"
                    if Path(cost_path).exists():
                        write_file(f"{user_id}/{project}/total_costs.json", Path(cost_path).read_text())
                    print(f"[SHUTDOWN] Flush complete for {project}/{step_id}")
                except Exception as e:
                    print(f"[SHUTDOWN] Flush failed for {project}/{step_id}: {e}")


# --- Auth Endpoints ---

@app.post("/auth/register")
def register(body: dict, request: Request):
    check_rate_limit(request.client.host, "register")
    email = body.get("email")
    password = body.get("password")
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password required")

    if email == ADMIN_EMAIL or find_user_by_email(email):
        raise HTTPException(status_code=400, detail="Email already registered")

    new_user = {
        "id": str(uuid.uuid4()),
        "email": email,
        "password_hash": hash_password(password),
        "is_approved": False,
        "is_admin": False,
        "api_key": "",
        "allowed_models": {},
        "created_at": datetime.utcnow().isoformat()
    }
    add_user(new_user)
    return {"message": "Registration successful. Awaiting admin approval."}

@app.post("/auth/login")
def login(body: dict, request: Request):
    check_rate_limit(request.client.host, "login")
    email    = body.get("email", "").strip().lower()
    password = body.get("password", "")

    user = find_user_by_email(email)
    if not user or not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Transparently upgrade legacy hash to bcrypt
    new_hash = rehash_if_legacy(password, user["password_hash"])
    if new_hash:
        update_user_field(user["id"], "password_hash", new_hash)

    if not user.get("is_approved"):
        raise HTTPException(status_code=403, detail="PENDING_APPROVAL")

    is_admin      = user.get("is_admin", False) or (email == ADMIN_EMAIL)
    token         = create_access_token(user["id"], user["email"], is_admin)
    refresh_token = create_refresh_token(user["id"])
    return {
        "access_token":  token,
        "refresh_token": refresh_token,
        "token_type":    "bearer",
        "is_admin":      is_admin,
        "email":         user["email"]
    }

@app.get("/auth/me")
def get_me(user: dict = Depends(get_current_user)):
    # Return user info without password hash
    return {k: v for k, v in user.items() if k != "password_hash"}

@app.post("/auth/refresh")
def refresh_access(body: dict):
    raw_token = body.get("refresh_token")
    if not raw_token:
        raise HTTPException(status_code=400, detail="refresh_token required")
    new_access, new_refresh = verify_and_rotate_refresh_token(raw_token)
    return {"access_token": new_access, "refresh_token": new_refresh, "token_type": "bearer"}

@app.post("/auth/logout")
def logout_user(user: dict = Depends(get_current_user)):
    revoke_all_refresh_tokens(user["id"])
    return {"ok": True}

# --- Admin Endpoints ---

@app.get("/admin/users")
def list_admin_users(admin: dict = Depends(require_admin)):
    users = load_users()
    enriched_users = []

    # Inject Admin synthetic record — folder is /app/output/admin
    admin_dir = Path("/app/output/admin")
    admin_project_count = 0
    admin_total_cost = 0.0
    admin_total_tokens = 0

    if admin_dir.exists():
        admin_projects = [d for d in admin_dir.iterdir() if d.is_dir() and not d.name.startswith(("_", "."))]
        admin_project_count = len(admin_projects)
        for p_dir in admin_projects:
            cost_file = p_dir / "total_costs.json"
            if cost_file.exists():
                try:
                    data = json.loads(cost_file.read_text())
                    summary = data.get("summary", data)
                    admin_total_cost += summary.get("total_cost", 0.0)
                    admin_total_tokens += summary.get("total_tokens", 0)
                except: pass

    admin_record = {
        "id": "admin",
        "email": ADMIN_EMAIL,
        "is_approved": True,
        "is_admin": True,
        "api_key": "",
        "allowed_models": {},
        "created_at": "2024-01-01T00:00:00",
        "project_count": admin_project_count,
        "total_cost": round(admin_total_cost, 4),
        "total_tokens": admin_total_tokens,
    }
    enriched_users.append(admin_record)

    for user in users:
        user_dir = Path(f"/app/output/{user['id']}")

        project_count = 0
        total_cost = 0.0
        total_tokens = 0

        if user_dir.exists():
            projects = [d for d in user_dir.iterdir() if d.is_dir() and not d.name.startswith("_") and not d.name.startswith(".")]
            project_count = len(projects)

            for p_dir in projects:
                cost_file = p_dir / "total_costs.json"
                if cost_file.exists():
                    try:
                        data = json.loads(cost_file.read_text())
                        summary = data.get("summary", data)
                        total_cost += summary.get("total_cost", 0.0)
                        total_tokens += summary.get("total_tokens", 0)
                    except: pass

        user_copy = {k: v for k, v in user.items() if k != "password_hash"}
        user_copy.update({
            "project_count": project_count,
            "total_cost": round(total_cost, 4),
            "total_tokens": total_tokens
        })
        enriched_users.append(user_copy)

    return enriched_users

@app.patch("/admin/users/{uid}/approve")
def approve_user(uid: str, admin: dict = Depends(require_admin)):
    if not find_user_by_id(uid):
        raise HTTPException(status_code=404, detail="User not found")
    update_user_field(uid, "is_approved", True)
    return {"ok": True}

@app.patch("/admin/users/{uid}/reject")
def reject_user(uid: str, admin: dict = Depends(require_admin)):
    if not find_user_by_id(uid):
        raise HTTPException(status_code=404, detail="User not found")
    delete_user(uid)
    return {"ok": True}

@app.patch("/admin/users/{uid}/api-key")
def set_user_api_key(uid: str, body: dict, admin: dict = Depends(require_admin)):
    api_key = body.get("api_key", "")
    if not find_user_by_id(uid):
        raise HTTPException(status_code=404, detail="User not found")
    update_user_field(uid, "api_key", api_key)
    return {"ok": True}

@app.patch("/admin/users/{uid}/models")
def set_user_models(uid: str, body: dict, admin: dict = Depends(require_admin)):
    allowed_models = body.get("allowed_models", {})
    if not find_user_by_id(uid):
        raise HTTPException(status_code=404, detail="User not found")
    update_user_field(uid, "allowed_models", allowed_models)
    return {"ok": True}

@app.get("/admin/stats")
def get_admin_stats(admin: dict = Depends(require_admin)):
    users_data = list_admin_users(admin)
    
    total_users = len(users_data)
    total_projects = sum(u["project_count"] for u in users_data)
    total_cost = sum(u["total_cost"] for u in users_data)
    total_tokens = sum(u["total_tokens"] for u in users_data)
    
    return {
        "total_users": total_users,
        "total_projects": total_projects,
        "total_cost": round(total_cost, 4),
        "total_tokens": total_tokens,
        "per_user": users_data
    }

@app.get("/admin/users/{uid}/projects")
def get_user_projects(uid: str, admin: dict = Depends(require_admin)):
    # uid is either "admin" or a UUID — use directly as folder name
    if uid != "admin":
        from auth import find_user_by_id
        if not find_user_by_id(uid):
            raise HTTPException(status_code=404, detail="User not found")

    user_dir = Path(f"/app/output/{uid}")
    if not user_dir.exists():
        return {"projects": []}
    
    projects = []
    for d in user_dir.iterdir():
        if d.is_dir() and not d.name.startswith(("_", ".")):
            total_cost = 0.0
            total_tokens = 0
            cost_file = d / "total_costs.json"
            if cost_file.exists():
                try:
                    data = json.loads(cost_file.read_text())
                    summary = data.get("summary", data)
                    total_cost = summary.get("total_cost", 0.0)
                    total_tokens = summary.get("total_tokens", 0)
                except: pass
            
            last_modified = datetime.utcfromtimestamp(
                os.path.getmtime(str(d))
            ).isoformat()
            
            projects.append({
                "name": d.name,
                "last_modified": last_modified,
                "total_cost": round(total_cost, 4),
                "total_tokens": total_tokens,
            })
    
    return {"projects": sorted(projects, key=lambda p: p["last_modified"], reverse=True)}

def _apply_user_env(user: dict):
    key = user.get("api_key", "")
    if key:
        os.environ["GEMINI_API_KEY"] = key
        os.environ["OPENAI_API_KEY"] = key
        os.environ["ANTHROPIC_API_KEY"] = key
        os.environ["OPENROUTER_API_KEY"] = key


# --- Project Endpoints ---

@app.get("/projects")
def get_projects(user: dict = Depends(get_current_user)):
    return {"projects": list_projects(user["id"])}

@app.post("/projects")
def create_project(body: dict, user: dict = Depends(get_current_user)):
    name = body.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="Project name required")
    get_or_create(name, user["id"])

    pdf_path = body.get("pdf_path", "")
    project_meta = json.dumps({"name": name, "pdf_path": pdf_path})

    # Write project.json locally (pipeline modules need it)
    project_dir = Path(f"/app/output/{user['id']}/{name}")
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "project.json").write_text(project_meta)

    # Also persist to Supabase Storage (survives container restarts)
    try:
        write_file(f"{user['id']}/{name}/project.json", project_meta)
    except Exception as e:
        print(f"[STORAGE] project.json upload failed: {e}")

    # Register in projects DB table (source of truth for list_projects)
    registered = False
    for attempt in range(2):
        try:
            sb = get_supabase()
            db_uid = get_db_user_id(user)
            sb.table("projects").upsert({
                "user_id": db_uid,
                "name": name,
                "pdf_storage_path": pdf_path,
                "last_activity_at": datetime.utcnow().isoformat(),
            }, on_conflict="user_id,name").execute()
            registered = True
            break
        except Exception as e:
            print(f"[DB] projects upsert attempt {attempt+1} failed: {e}")
    if not registered:
        print(f"[DB] WARNING: project '{name}' created in Storage but NOT in DB — S-1 self-heal will recover on next list")

    return {
        "name": name,
        "pdf_path": pdf_path,
        "last_step": 0,
        "last_modified": "",
        "total_tokens": 0
    }

# --- Google Sheets Config ---
GOOGLE_CLIENT_SECRET_PATH = "/app/google_client_secret.json" if Path("/app").exists() else str(Path(__file__).parent / "google_client_secret.json")
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive",
]
GOOGLE_REDIRECT_URI = os.environ.get(
    "GOOGLE_REDIRECT_URI",
    "https://ayoubi8-qcm-extractor.hf.space/oauth2callback"   # production default
)


def _get_google_creds(user_id: str):
    """Load saved token from Supabase Storage or local FS. Returns None if not authorized."""
    storage_path = f"{user_id}/.google_token.pickle"

    # Try Supabase Storage first
    try:
        creds = read_pickle(storage_path)
        if creds and creds.valid:
            print(f"[GOOGLE] Valid creds loaded from Supabase for {user_id}")
            return creds
        if creds and creds.expired and creds.refresh_token:
            print(f"[GOOGLE] Creds expired for {user_id}, refreshing...")
            creds.refresh(GoogleAuthRequest())
            try:
                write_pickle(storage_path, creds)
            except Exception:
                pass
            print(f"[GOOGLE] Creds refreshed successfully for {user_id}")
            return creds
        print(f"[GOOGLE] Creds from Supabase exist but not valid/refreshable for {user_id}")
    except Exception as e:
        print(f"[GOOGLE] Supabase token load failed for {user_id}: {e}")

    # Fallback to local filesystem
    token_path = Path(f"/app/output/{user_id}/.google_token.pickle")
    if token_path.exists():
        with open(token_path, "rb") as f:
            try:
                creds = pickle.load(f)
                if creds and creds.valid:
                    print(f"[GOOGLE] Valid creds loaded from local FS for {user_id}")
                    return creds
                if creds and creds.expired and creds.refresh_token:
                    print(f"[GOOGLE] Local creds expired for {user_id}, refreshing...")
                    creds.refresh(GoogleAuthRequest())
                    with open(token_path, "wb") as f2:
                        pickle.dump(creds, f2)
                    print(f"[GOOGLE] Local creds refreshed successfully for {user_id}")
                    return creds
            except Exception as e:
                print(f"[GOOGLE] Error loading local google token for {user_id}: {e}")
    else:
        print(f"[GOOGLE] No token found (Supabase or local) for {user_id}")
    return None

# --- PDF Upload & View Endpoints ---

@app.get("/projects/{name}/pdf")
def serve_project_pdf(name: str, user: dict = Depends(get_current_user)):
    """Serve the project's source PDF — from Supabase Storage (signed URL) or local FS fallback."""
    storage_path = f"{user['id']}/{name}/source.pdf"

    # Try Supabase Storage first
    try:
        if file_exists(storage_path):
            signed_url = get_signed_url(storage_path)
            return RedirectResponse(signed_url)
    except Exception as e:
        print(f"[STORAGE] signed URL failed: {e}")

    # Fallback to local filesystem
    pdf_path = Path(f"/app/output/{user['id']}/{name}/source.pdf")
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(str(pdf_path), media_type="application/pdf")

@app.get("/auth/google")
def start_google_auth(
    project: str = "", step: str = "", filename: str = "",
    token: str = "",          # JWT passed as query param from browser redirects
    authorization: str = Header(None),
):
    """Redirect user to Google consent screen. Accepts JWT via header OR ?token= query param."""
    from auth import decode_token, find_user_by_id
    # Resolve JWT — prefer header, fall back to query param
    raw_token = None
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization.split(" ")[1]
    elif token:
        raw_token = token
    if not raw_token:
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    payload = decode_token(raw_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user_id = payload.get("sub", "admin")

    flow = Flow.from_client_secrets_file(
        GOOGLE_CLIENT_SECRET_PATH,
        scopes=GOOGLE_SCOPES,
        redirect_uri=GOOGLE_REDIRECT_URI
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=f"{project}||{step}||{filename}||{user_id}"
    )
    return RedirectResponse(auth_url)

@app.get("/oauth2callback")
def google_oauth_callback(code: str, state: str = ""):
    """Handle Google OAuth callback, save token, redirect back to frontend."""
    print(f"[OAUTH] Callback received. redirect_uri={GOOGLE_REDIRECT_URI}")
    try:
        os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"  # Allow Google to grant extra scopes
        flow = Flow.from_client_secrets_file(
            GOOGLE_CLIENT_SECRET_PATH,
            scopes=GOOGLE_SCOPES,
            redirect_uri=GOOGLE_REDIRECT_URI
        )
        flow.fetch_token(code=code)
        creds = flow.credentials
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Google token exchange failed: {str(e)}")

    # Parse state: project||step||filename||user_id
    parts = state.split("||")
    project  = parts[0] if len(parts) > 0 else ""
    step     = parts[1] if len(parts) > 1 else ""
    filename = parts[2] if len(parts) > 2 else ""
    user_id  = parts[3] if len(parts) > 3 else "admin"

    # Save to Supabase Storage (primary — survives restarts)
    try:
        write_pickle(f"{user_id}/.google_token.pickle", creds)
        print(f"[OAUTH] Token saved to Supabase for user {user_id}")
    except Exception as e:
        print(f"[STORAGE] Google token Supabase upload failed: {e}")

    # Also save to local filesystem (fallback for pipeline compatibility)
    try:
        token_path = Path(f"/app/output/{user_id}/.google_token.pickle")
        token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)
    except Exception as e:
        print(f"[OAUTH] Local token save failed: {e}")

    # Token saved — redirect back to frontend to retry the upload via /open-sheets
    frontend_url = os.environ.get("FRONTEND_URL", "https://qcm-extractor-frontend.vercel.app")
    from urllib.parse import quote as _url_quote
    return RedirectResponse(
        f"{frontend_url}/pipeline"
        f"?sheets_pending=1"
        f"&project={_url_quote(project, safe='')}"
        f"&step={_url_quote(step, safe='')}"
        f"&filename={_url_quote(filename, safe='')}"
    )







@app.post("/projects/{name}/pdf")
async def upload_project_pdf(name: str, file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """Upload a PDF — dual-write to Supabase Storage and local FS for pipeline compatibility."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    content = await file.read()
    storage_pdf_path = f"{user['id']}/{name}/source.pdf"

    # Upload to Supabase Storage (cloud-persistent)
    # Store the absolute local path in project.json so that after a container
    # restart, list_projects restores the correct path and Step 1 can find the file.
    project_dir = Path(f"/app/output/{user['id']}/{name}")
    project_dir.mkdir(parents=True, exist_ok=True)
    local_pdf_path = project_dir / "source.pdf"
    local_pdf_path.write_bytes(content)
    internal_path = str(local_pdf_path)          # /app/output/{uid}/{name}/source.pdf

    try:
        write_bytes_file(storage_pdf_path, content)
        # ✅ Store the LOCAL absolute path so restored project.json is correct
        write_file(
            f"{user['id']}/{name}/project.json",
            json.dumps({"name": name, "pdf_path": internal_path})
        )
    except Exception as e:
        print(f"[STORAGE] PDF upload to Supabase failed: {e}")

    # Write the same project.json locally
    (project_dir / "project.json").write_text(
        json.dumps({"name": name, "pdf_path": internal_path})
    )

    return {"pdf_path": internal_path, "size_bytes": len(content)}


# --- Reference Database Management Endpoints ---


@app.get("/ref-db/diagnose")
def diagnose_ref_db():
    """Public diagnostic: check if reference_databases table exists."""
    result = {"table_exists": False, "row_count": None, "error": None,
              "users_table_ok": False, "supabase_ok": False}
    try:
        sb = get_supabase()
        result["supabase_ok"] = True
    except Exception as e:
        result["supabase_error"] = str(e)
        return result
    try:
        res = sb.table("reference_databases").select("id").limit(1).execute()
        result["table_exists"] = True
        result["row_count"] = len(res.data or [])
    except Exception as e:
        result["error"] = str(e)
    try:
        res2 = sb.table("users").select("id").limit(1).execute()
        result["users_table_ok"] = True
        result["users_count"] = len(res2.data or [])
    except Exception as e2:
        result["users_error"] = str(e2)
    return result

@app.get("/ref-db")
def list_ref_dbs(user: dict = Depends(get_current_user)):
    """List all reference databases uploaded by the current user."""
    sb = get_supabase()
    user_id = get_db_user_id(user)
    try:
        res = sb.table("reference_databases").select("*").eq("user_id", user_id).order("created_at").execute()
        return {"files": res.data or []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"[ref-db list] DB error: {str(e)}")

@app.post("/ref-db/upload")
async def upload_ref_db(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """Upload reference database, parse line count, upload to Supabase storage, cache locally, and store metadata in DB."""
    filename = file.filename
    if not filename.lower().endswith((".xlsx", ".xls", ".json")):
        raise HTTPException(status_code=400, detail="Only Excel (.xlsx, .xls) and JSON (.json) files are accepted")
    
    # Enforce limit of max 5 files per user
    sb = get_supabase()
    user_id = get_db_user_id(user)
    try:
        existing_res = sb.table("reference_databases").select("id").eq("user_id", user_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"[ref-db upload] Table check failed — table may not exist: {str(e)}")
    if len(existing_res.data or []) >= 5:
        raise HTTPException(status_code=400, detail="Maximum limit of 5 reference database files reached. Please delete an existing file first.")
    
    content = await file.read()
    size_bytes = len(content)
    
    # Parse file to determine total line/QCM count
    line_count = 0
    try:
        import io
        if filename.lower().endswith(".json"):
            data = json.loads(content.decode("utf-8"))
            if isinstance(data, list):
                line_count = len(data)
            elif isinstance(data, dict):
                for key in ("qcms", "questions", "data", "items"):
                    if key in data and isinstance(data[key], list):
                        line_count = len(data[key])
                        break
                else:
                    line_count = len(data.keys())
        else:
            # Excel files: try pandas first, fall back to openpyxl
            try:
                import pandas as pd
                df = pd.read_excel(io.BytesIO(content))
                line_count = len(df)
            except Exception:
                from openpyxl import load_workbook
                wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
                ws = wb.active
                rows = list(ws.iter_rows(values_only=True))
                count = sum(1 for r in rows if any(v is not None for v in r))
                line_count = max(0, count - 1)  # Subtract header row
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse reference database: {str(e)}")
    
    storage_path = f"{user['id']}/ref_dbs/{filename}"
    
    # Upload to Supabase Storage
    try:
        write_bytes_file(storage_path, content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload to storage: {str(e)}")
    
    db_record = {
        "user_id": user_id,
        "filename": filename,
        "storage_path": storage_path,
        "size_bytes": size_bytes,
        "line_count": line_count
    }
    
    try:
        # Delete if existing file with same name exists to avoid UNIQUE constraint violation
        sb.table("reference_databases").delete().eq("user_id", user_id).eq("filename", filename).execute()
        res = sb.table("reference_databases").insert(db_record).execute()
        record = res.data[0] if res.data else db_record
    except Exception as e:
        try:
            # Clean up uploaded storage file if database recording fails
            sb.storage.from_("qcm-projects").remove([storage_path])
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to save record to database: {str(e)}")
    
    # Cache locally on the container filesystem for execution compatibility
    try:
        local_dir = Path(f"/app/output/{user['id']}/ref_dbs")
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / filename).write_bytes(content)
    except Exception as e:
        print(f"[REF-DB] Local write failed: {e}")
    
    return record

@app.delete("/ref-db/{file_id}")
def delete_ref_db(file_id: str, user: dict = Depends(get_current_user)):
    """Delete reference database record from database, cloud storage, and local cache."""
    sb = get_supabase()
    
    user_id = get_db_user_id(user)

    res = sb.table("reference_databases").select("*").eq("id", file_id).eq("user_id", user_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Reference database file not found")
    
    record = res.data[0]
    filename = record["filename"]
    storage_path = record["storage_path"]
    
    # Delete from Database
    sb.table("reference_databases").delete().eq("id", file_id).execute()
    
    # Delete from Supabase Storage
    try:
        sb.storage.from_("qcm-projects").remove([storage_path])
    except Exception as e:
        print(f"[STORAGE] Failed to delete reference db from storage: {e}")
    
    # Delete local cached file
    try:
        local_file = Path(f"/app/output/{user['id']}/ref_dbs/{filename}")
        if local_file.exists():
            local_file.unlink()
    except Exception as e:
        print(f"[REF-DB] Failed to delete local file: {e}")
        
    return {"status": "deleted", "id": file_id}


@app.delete("/projects/{name}")
def delete_project(name: str, user: dict = Depends(get_current_user)):
    """Delete a project from Supabase Storage and local FS."""
    storage_prefix = f"{user['id']}/{name}"
    project_dir = Path(f"/app/output/{user['id']}/{name}")

    # Check existence in either location
    if not file_exists(f"{storage_prefix}/project.json") and not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")

    # Delete from Supabase Storage
    try:
        delete_prefix(storage_prefix)
    except Exception as e:
        print(f"[STORAGE] Supabase delete failed: {e}")

    # Delete from local filesystem
    if project_dir.exists():
        try:
            shutil.rmtree(project_dir)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete locally: {str(e)}")

    # Delete from projects DB table
    try:
        sb = get_supabase()
        db_uid = get_db_user_id(user)
        sb.table("projects").delete().eq("user_id", db_uid).eq("name", name).execute()
    except Exception as e:
        print(f"[DB] projects delete failed: {e}")

    return {"deleted": name}

# --- Step Run History & Badges ---

_step_start_time: dict = {}
_job_user_ids: dict = {}

def _record_step_history(project: str, user_id: str, step_id: str, start_time: float, badge: str, stats: dict):
    storage_path = f"{user_id}/{project}/step_history.json"

    # Read existing history — try Supabase first, then local FS
    history = {}
    try:
        if file_exists(storage_path):
            history = json.loads(read_file(storage_path))
    except Exception:
        local_hist = Path(f"/app/output/{user_id}/{project}/step_history.json")
        try:
            history = json.loads(local_hist.read_text()) if local_hist.exists() else {}
        except Exception:
            history = {}

    entry = {
        "run_at": datetime.now().isoformat(),
        "badge": badge,
        "duration_seconds": round(time.time() - start_time, 1),
        **stats
    }
    if step_id not in history:
        history[step_id] = []
    history[step_id].append(entry)
    history_json = json.dumps(history, indent=2)

    # Write to Supabase Storage
    try:
        write_file(storage_path, history_json)
    except Exception as e:
        print(f"[STORAGE] step_history upload failed: {e}")

    # Also write locally (pipeline badge computation reads local FS)
    local_hist = Path(f"/app/output/{user_id}/{project}/step_history.json")
    local_hist.parent.mkdir(parents=True, exist_ok=True)
    local_hist.write_text(history_json)

def _compute_step_badge(project: str, user_id: str, step_id: str) -> tuple[str, dict]:
    stats = {}
    badge = "success"
    try:
        if step_id == "1":
            accepted = Path(f"/app/output/{user_id}/{project}/step1_extraction/accepted")
            rejected = Path(f"/app/output/{user_id}/{project}/step1_extraction/rejected")
            acc = len(list(accepted.glob("*.txt"))) if accepted.exists() else 0
            rej = len(list(rejected.glob("*.txt"))) if rejected.exists() else 0
            stats = {"pages_ok": acc, "pages_failed": rej}
            badge = "success" if rej == 0 and acc > 0 else ("warning" if acc > 0 else "error")
        elif step_id == "2":
            qcm_dir = Path(f"/app/output/{user_id}/{project}/step2_qcm")
            total_qcms = 0
            empty_pages = 0
            for f in (qcm_dir.rglob("*.json") if qcm_dir.exists() else []):
                try:
                    data = json.loads(f.read_text())
                    qcms = len(data) if isinstance(data, list) else 0
                    total_qcms += qcms
                    if qcms == 0: empty_pages += 1
                except: pass
            stats = {"qcms": total_qcms, "empty_pages": empty_pages}
            badge = "error" if total_qcms == 0 else ("warning" if empty_pages > 0 else "success")
        elif step_id == "5":
            merged = Path(f"/app/output/{user_id}/{project}/step5_json/merged_qcms.json")
            merged_count = len(json.loads(merged.read_text())) if merged.exists() else 0
            stats = {"merged_qcms": merged_count}
            badge = "error" if merged_count == 0 else "success"
        elif step_id in ("3", "4", "6", "7", "1.5", "1.6"):
            badge = "success"
        # step 8: no badge
    except Exception:
        badge = "success"
    return badge, stats


def _resolve_project_id(user_id: str, project: str) -> str | None:
    """Look up the SQL `projects.id` for a (user_id, project_name) pair.

    PERSISTENCE_FIX_PLAN PR-4: goes through the in-memory PROJECT_REGISTRY
    (populated eagerly on startup by rebuild_project_registry_from_db) so
    the common case is a dict hit with no round-trip. On miss falls back
    to lookup_project_id which does a single SELECT and populates the cache.
    Returns None if the row is missing (legacy / not yet backfilled).
    """
    try:
        from project_manager import lookup_project_id
        uid = get_db_user_id({"id": user_id}) if not _is_uuid(user_id) else user_id
        return lookup_project_id(uid, project)
    except Exception as e:
        print(f"[PERSIST] _resolve_project_id failed ({user_id}/{project}): {e}")
        return None


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except Exception:
        return False


def _record_step_result(
    project: str,
    user_id: str,
    step_id: str,
    run_id: str,
    start_time: float,
    badge: str,
    stats: dict,
    folder_name: str,
    auto_build_folders: list | None = None,
):
    """Persist run metadata to the SQL tables after a step completes.

    Inserts:
      - one row into `step_results` per (project, step) folder produced
        (the primary step folder + any auto-build folders from the
        Step 2 → 3 → 4 → 5 cascade)
      - one row into `step_history` per folder
      - per-step cost rows into `costs` (best-effort, keyed by step_number)

    All SQL writes are isolated in try/except so a Supabase blip never
    flips a successful run to failure — the artifact bytes are already
    in Storage (uploaded by _do_post_step) and the local files are on
    disk; a backfill can reconstruct SQL rows later.
    """
    try:
        project_id = _resolve_project_id(user_id, project)
        if not project_id:
            print(f"[PERSIST] skipping SQL record — no projects row for {user_id}/{project}")
            return
        sb = get_supabase()
        duration = round(time.time() - start_time, 1) if start_time else 0.0
        from modules.utils.result_manifest import build_file_manifest, summarize_step

        folders = [folder_name] + list(auto_build_folders or [])
        seen = set()
        for folder in folders:
            if folder in seen:
                continue
            seen.add(folder)
            step_dir = Path(f"/app/output/{user_id}/{project}/{folder}")
            # Map the auto-build folders to their step_number for the row
            row_step_id = step_id if folder == folder_name else folder.replace("step", "").split("_")[0]
            storage_prefix = f"{user_id}/{project}/{folder}"
            try:
                manifest = build_file_manifest(step_dir, storage_prefix)
                payload = summarize_step(row_step_id, step_dir, stats)
                sb.table("step_results").upsert({
                    "project_id": project_id,
                    "step_number": str(row_step_id),
                    "run_id": run_id,
                    "badge": badge,
                    "duration_seconds": duration,
                    "storage_prefix": storage_prefix,
                    "file_manifest": manifest,
                    "payload": payload,
                }, on_conflict="project_id,step_number,run_id").execute()
            except Exception as e:
                print(f"[PERSIST] step_results insert failed ({folder}): {e}")
            try:
                sb.table("step_history").insert({
                    "project_id": project_id,
                    "step_number": str(row_step_id),
                    "run_at": datetime.utcnow().isoformat(),
                    "badge": badge,
                    "duration_seconds": duration,
                    "metadata": {"run_id": run_id, "folder": folder, **(stats or {})},
                }).execute()
            except Exception as e:
                print(f"[PERSIST] step_history insert failed ({folder}): {e}")
    except Exception as e:
        print(f"[PERSIST] _record_step_result failed for step {step_id}: {e}")


def _record_step_costs(user_id: str, project: str, step_id: str, tracker) -> None:
    """Insert per-step cost rows into the `costs` SQL table.

    Reads the in-memory tracker's per-step summaries (so we get the cost
    of the run we just executed, even on a fresh container where the
    `total_costs.json` blob is the only long-term record). Idempotent
    enough: re-runs insert fresh rows with a new recorded_at timestamp,
    which is the desired behaviour (we want a per-run cost trace).
    """
    try:
        project_id = _resolve_project_id(user_id, project)
        if not project_id or not tracker:
            return
        sb = get_supabase()
        step_key = f"step{step_id.replace('.', '_')}" if "." in step_id else f"step{step_id}"
        summary = tracker.get_step_summary(step_key) if hasattr(tracker, "get_step_summary") else None
        if not summary:
            return
        sb.table("costs").insert({
            "project_id": project_id,
            "step_number": str(step_id),
            "cost_usd": float(summary.get("total_cost", 0) or 0),
            "tokens": int(sum((summary.get("total_tokens") or {}).values())),
        }).execute()
    except Exception as e:
        print(f"[PERSIST] _record_step_costs failed for step {step_id}: {e}")


# --- PERSISTENCE_FIX_PLAN PR-2: SQL-first read helpers -----------------

def _latest_step_result_row(user_id: str, project: str, step_id: str | None = None) -> dict | None:
    """Return the newest `step_results` row, optionally filtered to one step.

    Survives a fresh container: queries SQL instead of walking the local FS
    or recursing Supabase Storage. Returns None if the table is missing /
    empty / the project_id can't be resolved — callers must fall back to
    the existing Storage/FS paths in that case (preserving back-compat).
    """
    try:
        project_id = _resolve_project_id(user_id, project)
        if not project_id:
            return None
        sb = get_supabase()
        q = sb.table("step_results").select(
            "id,step_number,run_id,badge,duration_seconds,storage_prefix,file_manifest,payload,created_at"
        ).eq("project_id", project_id)
        if step_id is not None:
            q = q.eq("step_number", str(step_id))
        q = q.order("created_at", desc=True).limit(1)
        res = q.execute()
        data = getattr(res, "data", None) or []
        return data[0] if data else None
    except Exception as e:
        print(f"[PERSIST] _latest_step_result_row failed ({user_id}/{project}/{step_id}): {e}")
        return None


def _all_step_history_rows(user_id: str, project: str) -> list:
    """Return all `step_history` rows for a project, newest first."""
    try:
        project_id = _resolve_project_id(user_id, project)
        if not project_id:
            return []
        sb = get_supabase()
        res = (sb.table("step_history")
                 .select("step_number,run_at,badge,duration_seconds,metadata")
                 .eq("project_id", project_id)
                 .order("run_at", desc=True)
                 .execute())
        return getattr(res, "data", None) or []
    except Exception as e:
        print(f"[PERSIST] _all_step_history_rows failed ({user_id}/{project}): {e}")
        return []


def _all_cost_rows(user_id: str, project: str) -> list:
    """Return all `costs` rows for a project, newest first."""
    try:
        project_id = _resolve_project_id(user_id, project)
        if not project_id:
            return []
        sb = get_supabase()
        res = (sb.table("costs")
                 .select("step_number,cost_usd,tokens,recorded_at")
                 .eq("project_id", project_id)
                 .order("recorded_at", desc=True)
                 .execute())
        return getattr(res, "data", None) or []
    except Exception as e:
        print(f"[PERSIST] _all_cost_rows failed ({user_id}/{project}): {e}")
        return []


# --- PERSISTENCE_FIX_PLAN PR-3: byte-serving from Storage --------------

def _eager_rebuild_registry():
    """PR-4: prefetch every projects.id into the in-memory PROJECT_REGISTRY.

    Called from the startup hook so the very first /projects call after a
    container restart is a dict hit instead of a SQL round-trip per project.
    """
    try:
        from project_manager import rebuild_project_registry_from_db
        rebuild_project_registry_from_db()
    except Exception as e:
        print(f"[STARTUP] ⚠️ eager registry rebuild failed (will lazy-resolve): {e}")


# Step-folder name → step_number, mirroring STEP_FOLDER_MAP in reverse.
# Used by the backfill to label synthetic rows. We deliberately exclude
# step4/5 because they're UI-hidden auto-builds; if both folders exist
# we still emit a "3" row (their effective trigger) so list_projects
# surfaces that the project reached Step 3.
_BACKFILL_STEP_FOLDERS = [
    ("step8_matches",    "8"),
    ("step7_categories", "7"),
    ("step6_corrections", "6"),
    ("step5_json",        "5"),
    ("step4_format",      "4"),
    ("step3_metadata",    "3"),
    ("step2_qcm",         "2"),
    ("step1_extraction",  "1"),
]


def _backfill_step_results_from_storage() -> int:
    """PR-4: one-off synthetic row backfill for pre-fix projects.

    Walks every projects row, and for each step-folder visible in Supabase
    Storage under {user_id}/{project}/{folder}, inserts a `step_results`
    row with `run_id='backfill'` IF (a) the project has no step_results row
    for that step yet (skip projects that already wrote rows on a real run)
    and (b) the step_results table exists. The walk is a single flat
    list_files per folder (the artifacts themselves are already in Storage
    from the existing _upload_step_folder_to_storage on every prior run).

    Returns the number of rows inserted. Idempotent: re-running the
    startup just no-ops for (project, step) pairs that already have a
    backfill row (UNIQUE constraint project_id,step_number,run_id).
    """
    from project_manager import PROJECT_REGISTRY, lookup_project_id
    from modules.utils.result_manifest import build_file_manifest  # noqa: F401 (kept for symmetry; the backfill uses Storage listing, not local FS)
    inserted = 0
    try:
        sb = get_supabase()
        # Probe the table once — skip silently if missing (PR-1 migration not run yet).
        try:
            sb.table("step_results").select("id").limit(1).execute()
        except Exception as e:
            print(f"[BACKFILL-SR] step_results table missing — skipping backfill: {e}")
            return 0

        # Iterate the registry built eagerly by rebuild_project_registry_from_db.
        # When the eager rebuild failed (Supabase blip), PROJECT_REGISTRY is
        # empty and we skip quietly rather than re-walking Storage.
        if not PROJECT_REGISTRY:
            print("[BACKFILL-SR] PROJECT_REGISTRY empty — nothing to backfill")
            return 0

        # First, load which (project_id, step_number) rows already exist so
        # we don't upsert over rows a real run wrote (preserves run_id != backfill).
        existing: set = set()
        try:
            # Batched fetch of all rows (modest table). Add a `run_id` filter
            # so we only see backfill candidates or real-run rows; either way
            # we skip emitting a fresh backfill row when one already exists
            # for that (project_id, step_number).
            res = sb.table("step_results").select("project_id,step_number").execute()
            for r in (getattr(res, "data", None) or []):
                existing.add((r.get("project_id"), str(r.get("step_number"))))
        except Exception as e:
            print(f"[BACKFILL-SR] could not load existing rows (will still attempt): {e}")

        # For each project, probe each step folder in Storage.
        for key, meta in PROJECT_REGISTRY.items():
            storage_id = meta.get("user_id")
            pname = meta.get("name")
            pid = meta.get("project_id")
            if not (storage_id and pname and pid):
                continue
            for folder, sid in _BACKFILL_STEP_FOLDERS:
                if (pid, sid) in existing:
                    continue
                prefix = f"{storage_id}/{pname}/{folder}"
                try:
                    items = list_files(prefix)
                    # Filter to actual files (Storage returns folder placeholders
                    # with id=None; real files have an id).
                    real_files = [it for it in items if it.get("id")]
                    if not real_files:
                        continue
                except Exception as e:
                    # Quiet — most prefixes simply don't exist for steps the
                    # project hasn't reached yet.
                    continue
                # Build a minimal manifest from the Storage listing. We don't
                # download the bytes (the real download is on demand via PR-3).
                manifest = [
                    {
                        "path": it.get("name", ""),
                        "size_bytes": int((it.get("metadata") or {}).get("size", 0) or 0),
                        "sha256": "",  # unknown without downloading; left blank
                        "kind": "json" if it.get("name", "").endswith(".json") else "other",
                    }
                    for it in real_files
                    if it.get("name")
                ]
                try:
                    sb.table("step_results").upsert({
                        "project_id": pid,
                        "step_number": sid,
                        "run_id": "backfill",
                        "badge": "success",
                        "duration_seconds": 0,
                        "storage_prefix": prefix,
                        "file_manifest": manifest,
                        "payload": {"file_count": len(manifest), "backfill": True},
                    }, on_conflict="project_id,step_number,run_id").execute()
                    inserted += 1
                    existing.add((pid, sid))
                except Exception as e:
                    print(f"[BACKFILL-SR] upsert failed for {pname}/{sid}: {e}")
        print(f"[BACKFILL-SR] inserted {inserted} synthetic step_results row(s)")
        return inserted
    except Exception as e:
        print(f"[BACKFILL-SR] aborted: {e}")
        return inserted


def _stream_file_from_storage(storage_path: str, local_dest: Path) -> bytes | None:
    """Pull `storage_path` from Supabase Storage and cache it at `local_dest`.

    Returns the raw bytes on success (caller can serve them directly) or
    None if the object doesn't exist / download failed. The local file is
    written *best-effort* — if the cache write fails (e.g. read-only FS on
    a fresh container path), we still return the bytes; the next read just
    has to fetch from Storage again.

    `local_dest.parents` are created if missing so this works on a wiped
    /app/output tree after a container restart.
    """
    try:
        data = read_bytes_file(storage_path)
    except Exception as e:
        print(f"[PR3] Storage download failed for {storage_path}: {e}")
        return None
    if data is None:
        return None
    try:
        local_dest.parent.mkdir(parents=True, exist_ok=True)
        local_dest.write_bytes(data)
    except Exception as we:
        print(f"[PR3] local cache write skipped for {local_dest}: {we}")
    return data


@app.get("/projects/{name}/step-history")
def get_step_history(name: str, user: dict = Depends(get_current_user)):
    # PERSISTENCE_FIX_PLAN PR-2: SQL step_history table first (one round-trip,
    # restart-proof). Reshape into the dict-of-step→list-of-entries contract
    # that the frontend already expects from the JSON blob.
    sql_rows = _all_step_history_rows(user["id"], name)
    if sql_rows:
        history: dict = {}
        for r in sql_rows:
            sid = str(r.get("step_number"))
            meta = r.get("metadata") or {}
            entry = {
                "run_at": r.get("run_at") or meta.get("run_at") or "",
                "badge": r.get("badge", "success"),
                "duration_seconds": r.get("duration_seconds", 0),
                **{k: v for k, v in meta.items() if k not in ("run_id", "folder")},
            }
            history.setdefault(sid, []).append(entry)
        if history:
            return history

    # Fallback: legacy JSON blob in Storage (then local FS).
    storage_path = f"{user['id']}/{name}/step_history.json"
    try:
        if file_exists(storage_path):
            return json.loads(read_file(storage_path))
    except Exception:
        pass
    path = Path(f"/app/output/{user['id']}/{name}/step_history.json")
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}

# --- Step Upload Helper (Group C fix) ---

def _upload_step_folder_to_storage(user_id: str, project: str, folder_name: str, storage_prefix: str) -> tuple:
    """
    Upload all files in a local step folder to Supabase Storage.
    Runs synchronously — must be called inside run_in_executor.
    Storage path: {user_id}/{project}/{folder_name}/{relative_file_path}
    Returns: (uploaded_count, failed_count)
    """
    local_dir = Path(f"/app/output/{user_id}/{project}/{folder_name}")
    if not local_dir.exists():
        return 0, 0
    uploaded = 0
    failed = 0
    for f in local_dir.rglob("*"):
        if not f.is_file():
            continue
        rel = str(f.relative_to(local_dir)).replace("\\", "/")
        storage_path = f"{storage_prefix}/{rel}"
        try:
            write_bytes_file(storage_path, f.read_bytes())
            uploaded += 1
        except Exception as e:
            print(f"[STORAGE] upload failed {storage_path}: {e}")
            failed += 1
    summary = f"[STORAGE] uploaded {uploaded} file(s) for {storage_prefix}"
    if failed:
        summary += f", {failed} FAILED"
    print(summary)
    return uploaded, failed


# --- Step Run Endpoint + Background Task ---

# Maps each step to the prior step folder(s) its module reads as input.
# Used by _restore_step_input_from_storage() so that after a container
# restart (local FS wiped) the step finds its dependencies on disk.
STEP_INPUT_DEPENDENCIES = {
    "2":         [("step1_extraction", "accepted")],   # Step 2 reads step1 Extraction accepted
    "3":         [("step2_qcm", "accepted")],            # Step 3 reads step2 QCM accepted
    # Steps 4 & 5 are auto-run after Step 3 — they read step3_metadata/accepted
    # but we don't expose them in the UI. Their restore is handled by
    # post_step3_build.py which uses context.get_path() — same local-FS-first
    # logic. If local FS is empty, the auto-build will fail with "no QCMs"
    # which is fine because Step 3 itself wouldn't have produced anything.
    "6":         [("step5_json", None), ("step6_corrections", None)],  # Step 6 reads merged_qcms.json + its own prior corrections
    "7":         [("step6_corrections", "accepted"), ("step5_json", None)],  # Step 7 reads corrected QCMs
    "8":         [("step5_json", None), ("step7_categories", "accepted")],  # Step 8 reads merged_qcms + categorized
}


def _restore_step_input_from_storage(user_id: str, project: str, step_id: str) -> None:
    """Before running a step, ensure its input folders exist on local disk.
    If a folder is missing (container restart wiped local FS), download all
    files from Supabase Storage under {user_id}/{project}/{folder}/ recursively.
    Mirrors the existing PDF restore pattern but for step output folders.
    """
    deps = STEP_INPUT_DEPENDENCIES.get(str(step_id))
    if not deps:
        return
    for folder, subdir in deps:
        local_dir = Path(f"/app/output/{user_id}/{project}/{folder}")
        if subdir:
            local_dir = local_dir / subdir
        # Fast path: already present locally (active container session or
        # the step was already run once since last restart).
        if local_dir.exists() and any(local_dir.rglob("*")):
            continue
        # Slow path: pull from Storage. Include subdir in the storage prefix
        # so list_files_recursive() walks from the SAME path local_dir ends
        # at — otherwise rel-paths from StepX are appended to "accepted/"
        # twice and files land in accepted/accepted/file.json (unreachable
        # to the module that reads accepted/file.json).
        try:
            storage_prefix = f"{user_id}/{project}/{folder}"
            if subdir:
                storage_prefix = f"{storage_prefix}/{subdir}"
            items = list_files_recursive(storage_prefix)
            if not items:
                continue
            local_dir.mkdir(parents=True, exist_ok=True)
            restored = 0
            for it in items:
                rel = it.get("name", "")
                if not rel:
                    continue
                storage_path = f"{storage_prefix}/{rel}"
                local_path = local_dir / rel
                local_path.parent.mkdir(parents=True, exist_ok=True)
                local_path.write_bytes(read_bytes_file(storage_path))
                restored += 1
            if restored:
                print(f"[RESTORE] ✅ Restored {restored} file(s) from Supabase → {local_dir}")
        except Exception as e:
            print(f"[RESTORE] ⚠️ Could not restore {folder}/{subdir or ''} for step {step_id}: {e}")

@app.post(
    "/projects/{name}/steps/{step_id}/run",
    deprecated=False,
    summary="Run a single pipeline step. Step 2 success auto-triggers Step 3 "
            "(metadata) and the Step 4→5 auto-build in the backend (see "
            "modules/post_step2_metadata.py). Steps 3, 4 and 5 are no longer "
            "standalone steps. Manual /steps/4/run and /steps/5/run remain "
            "available for advanced/debug use.",
)
async def run_step(name: str, step_id: str, body: dict, user: dict = Depends(get_current_user)):
    # Q5→5b: Step 3 is no longer a standalone step — it now runs as an
    # invisible cascade after Step 2 succeeds (see run_post_step2_metadata).
    if str(step_id) == "3":
        raise HTTPException(status_code=410, detail="Step 3 is no longer a standalone step. It runs automatically after Step 2 succeeds. Call POST /projects/{name}/steps/2/run instead.")
    if job_manager.is_running(name, step_id):
        return {"error": "Step already running"}

    _apply_user_env(user)
    _step_start_time[f"{name}-{step_id}"] = time.time()

    # Bump last_activity_at in DB
    try:
        sb = get_supabase()
        sb.table("projects").update({"last_activity_at": datetime.utcnow().isoformat()}) \
            .eq("user_id", get_db_user_id(user)).eq("name", name).execute()
    except Exception:
        pass

    # Pass the config body to the task
    task = asyncio.ensure_future(_run_step_task(name, user["id"], step_id, body))
    job_manager.set_running(name, step_id, task)
    _job_user_ids[job_manager.key(name, step_id)] = user["id"]
    return {"job_id": f"{name}-{step_id}-001"}

async def _run_step_task(project: str, user_id: str, step_id: str, config: dict):
    ctx_data = get_or_create(project, user_id)
    context = ctx_data["context"]
    tracker = ctx_data["tracker"]

    def log_callback(line: dict):
        job_manager.append_log(project, step_id, line)

    def _run_with_capture():
        with LogCapture(log_callback):
            _call_step(step_id, tracker, context, config)

    try:
        _STEP_FOLDER_MAP = {
            "1": "step1_extraction", "1.5": "step1_extraction", "1.6": "step1_extraction",
            "2": "step2_qcm", "3": "step3_metadata", "4": "step4_format",
            "5": "step5_json", "6": "step6_corrections", "7": "step7_categories", "8": "step8_matches",
        }
        folder_name = _STEP_FOLDER_MAP.get(step_id, f"step{step_id}")
        step_dir = Path(f"/app/output/{user_id}/{project}/{folder_name}")

        # Archive previous run to _history/ (local + Supabase)
        loop = asyncio.get_event_loop()
        if step_dir.exists() and any(step_dir.iterdir()):
            archive_ts = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
            archive_local = Path(f"/app/output/{user_id}/{project}/_history/step{step_id}/{archive_ts}")
            archive_storage = f"{user_id}/{project}/_history/step{step_id}/{archive_ts}"

            def _do_archive():
                archive_local.mkdir(parents=True, exist_ok=True)
                for f in step_dir.rglob("*"):
                    if f.is_file():
                        dest = archive_local / f.relative_to(step_dir)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(f), str(dest))
                # Upload archive to Supabase
                _upload_step_folder_to_storage(user_id, project, f"_history/step{step_id}/{archive_ts}", archive_storage)

            await loop.run_in_executor(None, _do_archive)

        # Ensure source.pdf is on local disk before running any step.
        # After a container restart the local FS is wiped; download from Supabase.
        local_pdf = Path(f"/app/output/{user_id}/{project}/source.pdf")
        if not local_pdf.exists():
            storage_pdf = f"{user_id}/{project}/source.pdf"
            try:
                if file_exists(storage_pdf):
                    local_pdf.parent.mkdir(parents=True, exist_ok=True)
                    local_pdf.write_bytes(read_bytes_file(storage_pdf))
                    # Also fix project.json so pdf_path points to the local file
                    pjson_local = local_pdf.parent / "project.json"
                    pjson_local.write_text(json.dumps({"name": project, "pdf_path": str(local_pdf)}))
                    print(f"[RESTORE] ✅ PDF restored from Supabase to {local_pdf}")
                else:
                    print(f"[RESTORE] ⚠️ source.pdf not in Supabase at {storage_pdf}")
            except Exception as _e:
                print(f"[RESTORE] ❌ PDF download failed: {_e}")

        # Ensure prior-step output folders are on local disk before running.
        # After a container restart the local FS is wiped; Step 2/3/6/7/8 modules
        # read from local directories (e.g. step2_qcm/accepted/). Without this
        # restore, Step 3 would log "No extracted QCMs found in
        # /app/output/.../step2_qcm/accepted" even though the files exist in
        # Supabase Storage. _restore_step_input_from_storage() mirrors the PDF
        # pattern but for step output folders.
        try:
            _restore_step_input_from_storage(user_id, project, step_id)
        except Exception as _rie:
            print(f"[RESTORE] ⚠️ step-input restore failed for step {step_id}: {_rie}")

        # Ensure Step 8 selected reference database is downloaded locally
        if step_id == "8" and config.get("ref_db_path"):
            ref_db_val = config.get("ref_db_path")
            # If it's a simple filename, retrieve it from Supabase storage and download locally
            if ref_db_val and not (ref_db_val.startswith("/") or ":" in ref_db_val or "\\" in ref_db_val):
                local_ref_dir = Path(f"/app/output/{user_id}/ref_dbs")
                local_ref_path = local_ref_dir / ref_db_val
                
                if not local_ref_path.exists():
                    storage_path = f"{user_id}/ref_dbs/{ref_db_val}"
                    try:
                        if file_exists(storage_path):
                            local_ref_dir.mkdir(parents=True, exist_ok=True)
                            local_ref_path.write_bytes(read_bytes_file(storage_path))
                            print(f"[RESTORE] ✅ Ref DB restored from Supabase to {local_ref_path}")
                        else:
                            print(f"[RESTORE] ⚠️ Ref DB not found in Supabase Storage at {storage_path}")
                    except Exception as ex:
                        print(f"[RESTORE] ❌ Ref DB download failed: {ex}")

        # --- FIX-04: Track step success separately so _do_post_step can never
        # overwrite a successful step status with a false "error" badge. ---
        step_succeeded = False

        try:
            await loop.run_in_executor(None, _run_with_capture)

            step_succeeded = True
            # Defer set_done for Step 2 until AFTER the cascade (Step 3 + build)
            # completes. The WebSocket log stream (ws_log) closes as soon as it
            # sees status=="done" — if we set_done here, the WS would close
            # before the cascade's log lines ("⚡ Auto-enrich...") reach the
            # frontend. For Step 2, set_done is called at the end of the
            # cascade block below (in its finally). For all other steps,
            # set_done is called here as before.
            if step_id != "2":
                job_manager.set_done(project, step_id)
            log_callback({"ts": datetime.now().strftime("%H:%M:%S"), "type": "ok", "text": f"\u2705 Step {step_id} completed successfully."})

            # POST-STEP-2 AUTO-ENRICH: after Step 2 succeeds, invisibly run
            # the old Step 3 (metadata) + the Step 4/5 auto-build
            # (run_post_step3_build) as a single backend cascade. Step 3 is
            # no longer an independently-triggered step (see Q5→5b in
            # MERGE_STEP2_STEP3_REPORT.md); its trigger moved inside Step 2's
            # task. Failure here MUST NOT flip Step 2's success status — the
            # user can still re-run Step 2 to retry the whole cascade.
            auto_build_folders: list = []
            if step_id == "2":
                try:
                    from modules.post_step2_metadata import run_post_step2_metadata
                    step3_cfg = config.get("step3", config.get("step3_config", {}))
                    res = await loop.run_in_executor(
                        None,
                        lambda: run_post_step2_metadata(tracker, context, user_id, project, step3_cfg)
                    )
                    rstatus = res.get("status")
                    if rstatus == "ok":
                        total = res.get("build", {}).get("step5", {}).get("total_qcms", 0)
                        log_callback({"ts": datetime.now().strftime("%H:%M:%S"), "type": "ok", "text": f"⚡ Auto-enrich (Step 3 + build) completed: {total} QCMs merged."})
                        job_manager.set_done(project, "3")
                        job_manager.set_done(project, "4")
                        job_manager.set_done(project, "5")
                        auto_build_folders = ["step3_metadata", "step4_format", "step5_json"]
                        # Record success badges for the hidden steps so history matches reality
                        for _sid in ("3", "4", "5"):
                            try:
                                _b, _s = _compute_step_badge(project, user_id, _sid)
                                _record_step_history(project, user_id, _sid, _step_start_time.get(f"{project}-{_sid}", time.time()), _b, _s)
                            except Exception as _be:
                                print(f"[POST-STEP-2] badge record failed for {_sid}: {_be}")
                    elif rstatus == "no_qcms":
                        log_callback({"ts": datetime.now().strftime("%H:%M:%S"), "type": "warn", "text": "ℹ️ Auto-enrich skipped: no accepted QCMs after Step 2."})
                    else:
                        log_callback({"ts": datetime.now().strftime("%H:%M:%S"), "type": "warn", "text": f"⚠️ Auto-enrich (Step 3 + build) reported: {res}. You can re-run Step 2 to retry."})
                except Exception as abe:
                    import traceback
                    traceback.print_exc()
                    log_callback({"ts": datetime.now().strftime("%H:%M:%S"), "type": "warn", "text": f"⚠️ Auto-enrich (Step 3 + build) failed: {str(abe)}. You can re-run Step 2 to retry."})
                finally:
                    # Now mark Step 2 as done — the WS log stream will see
                    # "done" and close AFTER pushing all cascade log lines.
                    job_manager.set_done(project, step_id)

        except Exception as e:
            import traceback
            traceback.print_exc()
            job_manager.set_error(project, step_id)
            log_callback({"ts": datetime.now().strftime("%H:%M:%S"), "type": "error", "text": f"❌ Step {step_id} failed: {str(e)}"})

        finally:
            # Always attempt to save outputs to Supabase — even on failed steps,
            # partial outputs may exist and are worth preserving.
            # This is isolated so it can never change the step's success/error status.
            def _do_post_step():
                # FIX-06: Collect upload failures so we can warn the user in the UI
                failed_uploads: list = []

                # Save costs locally
                cost_path = f"/app/output/{user_id}/{project}/total_costs.json"
                Path(cost_path).parent.mkdir(parents=True, exist_ok=True)
                tracker.save(cost_path)
                # Upload costs to Supabase
                try:
                    write_file(f"{user_id}/{project}/total_costs.json", Path(cost_path).read_text())
                except Exception as e:
                    print(f"[STORAGE] cost upload failed: {e}")
                    failed_uploads.append(f"cost file: {e}")

                # Upload step output folder to Supabase
                step_storage_prefix = f"{user_id}/{project}/{folder_name}"
                _, folder_failed = _upload_step_folder_to_storage(user_id, project, folder_name, step_storage_prefix)
                if folder_failed > 0:
                    failed_uploads.append(f"{folder_failed} output file(s) failed to sync")

                # If the Post-Step-3 auto-build ran, also upload the produced
                # step4_format/ and step5_json/ folders so they survive restarts.
                for _extra_folder in auto_build_folders:
                    try:
                        _, extra_failed = _upload_step_folder_to_storage(
                            user_id, project, _extra_folder, f"{user_id}/{project}/{_extra_folder}"
                        )
                        if extra_failed > 0:
                            failed_uploads.append(f"{extra_failed} {_extra_folder} file(s) failed to sync")
                    except Exception as e:
                        print(f"[POST-STEP-3] upload of {_extra_folder} failed: {e}")
                        failed_uploads.append(f"{_extra_folder}: {e}")

                # Surface any failures as a visible warning in the user's terminal panel
                if failed_uploads:
                    log_callback({
                        "ts": datetime.now().strftime("%H:%M:%S"),
                        "type": "warn",
                        "text": (
                            f"⚠️ Cloud sync issue ({len(failed_uploads)} problem(s)): "
                            + "; ".join(failed_uploads)
                            + ". Results saved locally but may not persist after a container restart."
                        )
                    })

            try:
                await loop.run_in_executor(None, _do_post_step)
            except Exception as post_e:
                # Log but do NOT propagate — post-step I/O failure must not change
                # the step's status which was already set above.
                print(f"[POST-STEP] Output upload failed for step {step_id}: {post_e}")

            # Record history based on the actual step outcome (not post-step I/O outcome)
            try:
                start_ts = _step_start_time.get(f"{project}-{step_id}", time.time())
                run_id = datetime.utcfromtimestamp(start_ts).strftime("%Y-%m-%dT%H-%M-%S")
                if step_succeeded:
                    badge, stats = _compute_step_badge(project, user_id, step_id)
                    _record_step_history(project, user_id, step_id, start_ts, badge, stats)
                else:
                    badge, stats = "error", {}
                    _record_step_history(project, user_id, step_id, start_ts, badge, stats)
                # PERSISTENCE_FIX_PLAN PR-1: also record into the SQL
                # step_results / step_history / costs tables so the run
                # survives a container restart even with an empty local FS.
                try:
                    _record_step_result(
                        project, user_id, step_id, run_id, start_ts,
                        badge, stats, folder_name, auto_build_folders,
                    )
                except Exception as _sr:
                    print(f"[POST-STEP] step_results record failed for step {step_id}: {_sr}")
                try:
                    _record_step_costs(user_id, project, step_id, tracker)
                except Exception as _sc:
                    print(f"[POST-STEP] costs record failed for step {step_id}: {_sc}")
            except Exception as be:
                print(f"[POST-STEP] Badge recording failed for step {step_id}: {be}")

    except Exception as outer_e:
        # Outer except catches setup failures (archive, PDF restore, ref DB restore)
        # that happen before the step even starts.
        import traceback
        traceback.print_exc()
        job_manager.set_error(project, step_id)
        log_callback({"ts": datetime.now().strftime("%H:%M:%S"), "type": "error", "text": f"❌ Step {step_id} setup failed: {str(outer_e)}"})
        try:
            _record_step_history(project, user_id, step_id, _step_start_time.get(f"{project}-{step_id}", time.time()), "error", {})
        except Exception as be:
            print(f"[POST-STEP] Badge recording failed for step {step_id}: {be}")

def _call_step(step_id: str, tracker, context, config: dict):
    """Synchronous step dispatcher. Runs in a thread via run_in_executor."""
    
    def _auto_input(prompt=""):
        """Replace input() with automatic responses derived from UI config."""
        p = str(prompt).lower()
        print(f"[AUTO] {repr(prompt)}")
        
        # Step 1 — extraction method
        if "choice [1-2]" in p or "select method" in p:
            return "1" if config.get("method", "vision_ocr") == "vision_ocr" else "2"
        if "ocr guidance" in p or "your guidance" in p:
            return config.get("ocr_guidance", "")
        
        # Step 2 — page range
        if "your choice" in p or "page range" in p:
            return config.get("page_range", "1-1-1")
        
        # Step 2/6 — review prompts → always accept/skip
        if "[a]ccept" in p or "[r/c]" in p:
            return "a"
        if "[r]etry" in p or "[s]kip" in p or "debug" in p:
            return "s"
        
        # Step 3 — strategy choice
        if "choice:" in p:
            return ""
        
        # Step 6 — correction mode (legacy AI-knowledge S/B prompt; no longer
        # reachable from UI but kept for back-compat if source="ai_knowledge" leaks in).
        if "select mode [s/b]" in p:
            return "b" if config.get("correction_search_mode", "") == "all_pages" else "s"
        if "use these pages" in p:
            return "y"
        if "pages:" in p or "page number" in p:
            return config.get("correction_pages", "1")
        if "[u]se default" in p or "edit" in p:
            return "u"
        if "choice [1-3]" in p or "recovery" in p:
            return "1"
        if "correction" in p and "enter" in p:
            return ""
        
        # Step 8 — reference DB path prompt: return full resolved path so step8_matcher can find the file
        if prompt.strip() == ">":
            ref = config.get("ref_db_path", "")
            # If it's a plain filename, resolve to the full local container path
            if ref and not (ref.startswith("/") or ":" in ref or "\\" in ref):
                try:
                    uid = context.name.split("/")[0]
                except Exception:
                    uid = "admin"
                ref = f"/app/output/{uid}/ref_dbs/{ref}"
            return ref
        
        # Step 8 — interactive export → skip
        if "export custom xlsx" in p:
            return "n"
        if "use these settings" in p:
            return "y"
        if "select [1/2/3]" in p:
            return "1"
        if "threshold" in p:
            return ""
        if "weight" in p:
            return ""
        
        # Default — return empty (skip/use default)
        print(f"[AUTO-INPUT] Unhandled prompt, returning empty string")
        return ""

    # Install the patch
    builtins.input = _auto_input
    
    # Apply model overrides to environment before importing/running modules.
    # Only override when the UI explicitly sends a non-empty model string.
    if step_id == "1" and config.get("model"):
        os.environ["STEP1_MODEL"] = config["model"]
    if step_id == "2":
        if config.get("model_primary"):
            os.environ["STEP2_MODEL"] = config["model_primary"]
            # Sync Step 2's model to Step 3 so the metadata cascade (which
            # fires inside Step 2's run via run_post_step2_metadata) uses the
            # same model the user picked — there is now a single model
            # selector pair in the UI that applies to both QCM extraction
            # and metadata detection.
            os.environ["STEP3_MODEL"] = config["model_primary"]
        if config.get("model_fallback"):
            os.environ["STEP2_FALLBACK_MODEL"] = config["model_fallback"]
            os.environ["STEP3_FALLBACK_MODEL"] = config["model_fallback"]
    if step_id == "3":
        if config.get("model"):
            os.environ["STEP3_MODEL"] = config["model"]
        if config.get("model_fallback"):
            os.environ["STEP3_FALLBACK_MODEL"] = config["model_fallback"]
    if step_id == "6":
        if config.get("text_model"):
            os.environ["STEP6_TEXT_MODEL"] = config["text_model"]
        if config.get("all_pages_model"):
            os.environ["STEP6_ALL_PAGES_MODEL"] = config["all_pages_model"]
        if config.get("ai_model"):
            os.environ["STEP6_AI_MODEL"] = config["ai_model"]
        if config.get("vision_model"):
            os.environ["STEP6_ALL_PAGES_MODEL"] = config["vision_model"]
    
    if step_id == "8":
        if config.get("ref_db_path"):
            ref_db_val = config["ref_db_path"]
            # If it's a simple filename, resolve to the local user's folder path
            if ref_db_val and not (ref_db_val.startswith("/") or ":" in ref_db_val or "\\" in ref_db_val):
                uid = context.name.split("/")[0]
                ref_db_val = f"/app/output/{uid}/ref_dbs/{ref_db_val}"
            os.environ["REFERENCE_DB_PATH"] = ref_db_val
        if config.get("match_mode"):
            os.environ["MATCH_MODE"] = config["match_mode"]
        if config.get("threshold") is not None:
            os.environ["MATCH_THRESHOLD"] = str(config["threshold"])
        if config.get("text_weight") is not None:
            os.environ["MATCH_TEXT_WEIGHT"] = str(config["text_weight"])
        if config.get("corr_weight") is not None:
            os.environ["MATCH_CORRECTION_WEIGHT"] = str(config["corr_weight"])
        if config.get("color_green") is not None:
            os.environ["MATCH_COLOR_GREEN"] = str(config["color_green"])
        if config.get("color_yellow") is not None:
            os.environ["MATCH_COLOR_YELLOW"] = str(config["color_yellow"])
        # NEW: tag-merge phase config (auto-merge floor + self-scan flag)
        if config.get("auto_merge_floor") is not None:
            os.environ["MATCH_AUTO_MERGE_FLOOR"] = str(config["auto_merge_floor"])
        if config.get("self_scan") is not None:
            os.environ["MATCH_SELF_SCAN"] = "1" if config["self_scan"] else "0"

    # Late imports to avoid circular deps and only load what's needed
    from modules.step1_extraction import Step1Extraction
    from modules.step1_5_batch_text_fixer import Step1_5BatchTextFixer
    from modules.step1_6_intelligent_text_fixer import Step1_6IntelligentTextFixer
    from modules.step2_qcm_extract_batch import Step2QCMExtractBatch
    from modules.step4_format import Step4Format
    from modules.step5_builder import Step5Builder
    from modules.step6_corrections import Step6Corrections
    from modules.step7_categorization import Step7Categorization
    from modules.step8_matcher import Step8Matcher

    def _run_step4_auto(tracker, context, cfg):
        from modules.step4_format import Step4Format
        from modules.utils.template_library import TemplateLibrary
        name   = cfg.get("name") or "pediat"
        fields = cfg.get("fields", {})
        tmpl: dict = {}
        if fields.get("Num",          True):  tmpl["Num"]          = 0
        if fields.get("Text",         True):  tmpl["Text"]         = "Question text here..."
        if fields.get("Propositions", True):
            tmpl.update({"A":"Option A","B":"Option B","C":"Option C","D":"Option D","E":"Option E"})
        if fields.get("Correct",      True):  tmpl["Correct"]      = "ABC"
        if fields.get("Year",         True):  tmpl["Year"]         = "2024"
        if fields.get("Category",     True):  tmpl["categoryName"] = "Cardiologie"
        if fields.get("Subcategory",  False): tmpl["subcategoryName"] = "HTA"
        if fields.get("Source",       False): tmpl["Source"]       = "Alger"
        if fields.get("Tag",          True):  tmpl["Tag"]          = ["Alger", "2024"]
        if fields.get("ClinicalCase", False): tmpl["Cas"]          = "CAS CLINIQUE 1\r\nNarrative..."
        TemplateLibrary().save_template(name, tmpl)
        print(f"[STEP4] Template '{name}' saved: {list(tmpl.keys())}")
        Step4Format(tracker, context).run(auto_template=name)

    def _build_step6_config(cfg):
        source_map = {
            "page_text":    "page_text",
            "auto_detect":  "auto_detect",   # NEW per-page DeepSeek scan
            "vision_ai":    "vision",        # legacy — kept for back-compat only
            "ai_knowledge": "ai_knowledge",  # legacy — kept for back-compat (no UI)
        }
        backend_source = source_map.get(cfg.get("source","auto_detect"),"auto_detect")
        # Auto-Detect is per-page; search_mode is forced to all_pages.
        if cfg.get("source") == "auto_detect":
            search_mode = "all_pages"
        else:
            search_mode = cfg.get("correction_search_mode","all_pages")
        return {
            "source": backend_source,
            "correction_search_mode": search_mode,
            "pages": cfg.get("pages",""), "force_overwrite": cfg.get("force_overwrite",False),
            "vision": {"custom_prompt": cfg.get("vision_prompt","")},
            "page_text": {"extraction_guidance": cfg.get("page_text_guidance","")},
            "all_pages_scan": {"candidate_threshold": int(cfg.get("candidate_threshold",15)), "include_neighbors": bool(cfg.get("include_neighbors",True))},
        }

    step_map = {
        "1":   lambda: Step1Extraction(tracker, context).run(
                    # Always use the canonical local path — config.pdf_path may be
                    # stale (e.g. a Supabase storage key) after a container restart.
                    pdf_path=str(Path(f"/app/output/{context.name}/source.pdf")),
                    auto_ocr=(config.get("method", "") == "vision_ocr"),
                    ocr_guidance=config.get("ocr_guidance", ""),
                    force_overwrite=bool(config.get("force_overwrite", False)),
               ),
        "1.5": lambda: Step1_5BatchTextFixer(tracker, context).run(),
        "1.6": lambda: Step1_6IntelligentTextFixer(tracker, context).run(),
        "2":   lambda: Step2QCMExtractBatch(tracker, context).run(
                    page_range=config.get("page_range") or "1-1-1",
                    config={
                        "qcm_extraction": {
                            "extraction_guidance": config.get("extraction_guidance", ""),
                            "clinical_case_hints": config.get("clinical_case_hints", False),
                        }
                    }
               ),
        "4":   lambda: _run_step4_auto(tracker, context, config),
        "5":   lambda: Step5Builder(tracker, context).run(),
        "6":   lambda: Step6Corrections(tracker, context).run(
                    pdf_path=config.get("pdf_path",""),
                    auto_mode=True,
                    config=_build_step6_config(config),
                ),
        "7":   lambda: Step7Categorization(tracker, context).run(),
        "8":   lambda: Step8Matcher(tracker, context).run(),
    }
    
    if step_id not in step_map:
        raise ValueError(f"Unknown step identifier: {step_id}")
    
    # Execute the step
    step_map[step_id]()

# --- Status + WebSocket Endpoints ---

def _check_step_done_in_storage(user_id: str, project: str, step_id: str) -> bool:
    """
    FIX-01 (Option A): Check whether a step has outputs uploaded to Supabase Storage.
    Used as the authoritative fallback when the in-memory JobManager is empty
    (e.g. after a container restart on HuggingFace Spaces).

    Storage prefix pattern: {user_id}/{project}/{step_folder}/
    Returns True if at least one file exists under that prefix.
    """
    from project_manager import STEP_FOLDER_MAP
    folder_name = STEP_FOLDER_MAP.get(str(step_id), f"step{step_id}")
    prefix = f"{user_id}/{project}/{folder_name}"
    try:
        items = list_files(prefix)
        # Filter out placeholder/folder entries (those with no 'id' are sub-folders)
        real_files = [f for f in items if f.get("id")]
        return len(real_files) > 0
    except Exception as e:
        print(f"[STATUS] Storage check failed for {prefix}: {e}")
        return False


@app.get("/projects/{name}/steps/{step_id}/status")
def get_step_status(name: str, step_id: str, user: dict = Depends(get_current_user)):
    mem_status = job_manager.get_status(name, step_id)
    mem_output = step_output_exists(name, step_id, user["id"])

    # If the job is actively tracked in memory (running or finished this session),
    # trust the in-memory state — it's the most up-to-date.
    if mem_status in ("running", "done", "error"):
        return {"status": mem_status, "output_exists": mem_output}

    # PERSISTENCE_FIX_PLAN PR-2: SQL-first check. After a container restart
    # the in-memory JobManager is empty, but a step_results SQL row (written
    # by _record_step_result on every successful run) survives. One round-trip
    # instead of 8 recursive Storage walks per step.
    sql_row = _latest_step_result_row(user["id"], name, step_id)
    if sql_row:
        badge = sql_row.get("badge")
        if badge == "success":
            return {"status": "done", "output_exists": True}
        if badge == "error":
            return {"status": "error", "output_exists": bool(sql_row.get("file_manifest"))}

    # mem_status == "idle" and no SQL row: fall back to Supabase Storage
    # (handles pre-fix projects that have outputs in Storage but no SQL row yet).
    storage_done = _check_step_done_in_storage(user["id"], name, step_id)
    if storage_done:
        return {"status": "done", "output_exists": True}

    # Nothing in memory or storage — step has genuinely not been run yet.
    return {"status": "idle", "output_exists": False}

@app.websocket("/ws/log/{project}/{step_id}")
async def ws_log(websocket: WebSocket, project: str, step_id: str, token: str = ""):
    # FIX-09: Validate the JWT token passed as a query param.
    # Browser WS cannot set Authorization headers, so the token is passed via ?token=...
    from auth import decode_token
    payload = decode_token(token) if token else None
    if not payload:
        # Must accept before we can send a close/error frame
        await websocket.accept()
        await websocket.send_text(json.dumps({
            "ts": datetime.now().strftime("%H:%M:%S"),
            "type": "auth_error",
            "text": "Unauthorized: missing or expired token. Please refresh the page."
        }))
        await websocket.close(code=4401)
        return

    await websocket.accept()
    sent_count = 0
    try:
        while True:
            all_logs = job_manager.get_logs(project, step_id)
            # Push new lines
            while sent_count < len(all_logs):
                await websocket.send_text(json.dumps(all_logs[sent_count]))
                sent_count += 1
            
            # Exit loop if job is finished and all lines pushed
            status = job_manager.get_status(project, step_id)
            if status in ("done", "error") and sent_count >= len(all_logs):
                break
            
            await asyncio.sleep(0.3)
    except Exception:
        pass
    finally:
        try:
            await websocket.close()
        except:
            pass

# --- Cost Endpoints ---

@app.get("/projects/{name}/costs")
def get_project_costs(name: str, user: dict = Depends(get_current_user)):
    # PERSISTENCE_FIX_PLAN PR-2: SQL costs table first (one round-trip,
    # restart-proof). Reconstructs the summary shape the frontend expects
    # from total_costs.json. per_model is left empty because the SQL costs
    # table doesn't track per-model granularity (the blob does).
    sql_rows = _all_cost_rows(user["id"], name)
    if sql_rows:
        per_step: dict = {}
        total_cost = 0.0
        total_tokens = 0
        for r in sql_rows:
            sid = str(r.get("step_number"))
            cost = float(r.get("cost_usd") or 0)
            tk = int(r.get("tokens") or 0)
            slot = per_step.setdefault(sid, {
                "total_cost": 0.0, "call_count": 0,
                "total_tokens": {"prompt": 0, "completion": 0},
            })
            slot["total_cost"] += cost
            slot["call_count"] += 1
            # SQL `costs.tokens` is a single int (prompt + completion combined);
            # stash it on the completion slot so the sum shape matches the blob.
            slot["total_tokens"]["completion"] += tk
            total_cost += cost
            total_tokens += tk
        return {
            "per_model": {},
            "per_step": per_step,
            "total_cost": total_cost,
            "total_tokens": total_tokens,
        }

    # Fallback: Storage blob → local FS → in-memory tracker (existing path).
    storage_path = f"{user['id']}/{name}/total_costs.json"
    try:
        if file_exists(storage_path):
            data = json.loads(read_file(storage_path))
            return data.get("summary", data)
    except Exception:
        pass
    # Fallback to local filesystem
    cost_file = Path(f"/app/output/{user['id']}/{name}/total_costs.json")
    if cost_file.exists():
        try:
            data = json.loads(cost_file.read_text())
            return data.get("summary", data)
        except Exception:
            pass
    # Last resort: live in-memory tracker
    ctx_data = get_or_create(name, user["id"])
    return ctx_data["tracker"].get_total_summary()

@app.post("/projects/{name}/costs/save")
def save_project_costs(name: str, user: dict = Depends(get_current_user)):
    local_path = f"/app/output/{user['id']}/{name}/total_costs.json"
    Path(local_path).parent.mkdir(parents=True, exist_ok=True)
    ctx_data = get_or_create(name, user["id"])
    ctx_data["tracker"].save(local_path)
    # Also upload to Supabase Storage
    try:
        write_file(f"{user['id']}/{name}/total_costs.json", Path(local_path).read_text())
    except Exception as e:
        print(f"[STORAGE] costs/save upload failed: {e}")
    return {"saved_to": local_path}

@app.get("/costs/weekly")
def get_all_weekly_costs(user: dict = Depends(get_current_user)):
    return get_weekly_costs(user["id"])

# --- .env Endpoints ---

@app.get("/env")
def get_environment(user: dict = Depends(get_current_user)):
    env = read_env()
    result = {}
    for k, v in env.items():
        if k in EDITABLE_KEYS:
            result[k] = mask(v)
        elif any(x in k for x in ["MODEL", "ENABLE", "STEP"]):
            result[k] = v
    return result

@app.post("/env")
def update_environment(body: dict, user: dict = Depends(get_current_user)):
    updated = write_env_keys(body)
    # Update current process environment for immediate effect (hot-swap)
    env = read_env()
    for k in updated:
        os.environ[k] = env.get(k, "")
    return {"updated": updated}

@app.get("/env/raw")
def get_environment_raw(user: dict = Depends(get_current_user)):
    """Returns all env values unmasked for the settings UI."""
    env = read_env()
    result = {}
    for k, v in env.items():
        if k in EDITABLE_KEYS or any(x in k for x in ["MODEL", "ENABLE", "STEP"]):
            result[k] = v  # NO masking
    return result

ADMIN_ENV_PATH = Path("/app/admin.env")

@app.get("/admin/available-models")
def get_available_models(user: dict = Depends(get_current_user)):
    """
    Admin → return full model list from admin.env (unchanged).
    Regular user → return their allowed_models from users.json.
    If user's allowed_models is empty → fall back to admin.env global list.
    """
    # Parse admin.env (global list) — keep existing parsing logic
    global_models = {}
    if ADMIN_ENV_PATH.exists():
        for line in ADMIN_ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, val = line.partition('=')
                global_models[key.strip().lower()] = [m.strip() for m in val.split(',') if m.strip()]

    # Admin always gets global list
    if user.get("is_admin"):
        return global_models

    # Regular user: use their assigned models if set, else fall back to global
    user_models = user.get("allowed_models", {})
    if user_models:
        # Merge: use user's list where set, fall back to global for missing slots
        merged = dict(global_models)
        merged.update(user_models)
        return merged

    return global_models

@app.get("/env/step-models")
def get_step_models(user: dict = Depends(get_current_user)):
    env = read_env()
    return {
        "step1":   {"primary": env.get("STEP1_MODEL"),   "fallback": env.get("STEP1_FALLBACK_MODEL")},
        "step1_5": {"primary": env.get("STEP1_5_MODEL"), "fallback": env.get("STEP1_5_FALLBACK_MODEL")},
        "step1_6": {"primary": env.get("STEP1_6_MODEL"), "fallback": env.get("STEP1_6_FALLBACK_MODEL")},
        "step2":   {"primary": env.get("STEP2_MODEL"),   "fallback": env.get("STEP2_FALLBACK_MODEL")},
        "step3":   {"primary": env.get("STEP3_MODEL"),   "fallback": env.get("STEP3_FALLBACK_MODEL")},
        "step6":   {
            "text_model":         env.get("STEP6_TEXT_MODEL"),
            "text_fallback":      env.get("STEP6_TEXT_FALLBACK_MODEL"),
            "all_pages_model":    env.get("STEP6_ALL_PAGES_MODEL"),
            "all_pages_fallback": env.get("STEP6_ALL_PAGES_FALLBACK_MODEL"),
            "ai_model":           env.get("STEP6_AI_MODEL"),
            "ai_fallback":        env.get("STEP6_AI_FALLBACK_MODEL")
        },
        "step7":   {"primary": env.get("STEP7_MODEL"),   "fallback": env.get("STEP7_FALLBACK_MODEL")},
        "step8":   {}
    }

# --- Batch Config + Template Endpoints ---

@app.get("/config/batch")
def get_batch_config(user: dict = Depends(get_current_user)):
    cfg_path = Path("/app/batch_config.yaml")
    if cfg_path.exists():
        try:
            with open(cfg_path) as f:
                return yaml.safe_load(f)
        except:
            pass
    return {}

@app.post("/config/batch")
def post_batch_config(body: dict, user: dict = Depends(get_current_user)):
    cfg_path = Path("/app/batch_config.yaml")
    # Monaco editor sends raw YAML string in body["yaml_content"]
    content = body.get("yaml_content", "")
    cfg_path.write_text(content)
    return {"saved": True}

@app.get("/templates")
def get_template_list(user: dict = Depends(get_current_user)):
    from modules.utils.template_library import TemplateLibrary
    return TemplateLibrary().list_templates()

@app.get("/projects/{name}/steps/{step_id}/output")
def get_step_output_files(name: str, step_id: str, user: dict = Depends(get_current_user)):
    _SFMAP = {
        "1": "step1_extraction", "1.5": "step1_extraction", "1.6": "step1_extraction",
        "2": "step2_qcm", "3": "step3_metadata", "4": "step4_format",
        "5": "step5_json", "6": "step6_corrections", "7": "step7_categories", "8": "step8_matches",
    }
    folder_name = _SFMAP.get(step_id, f"step{step_id}")
    step_dir = Path(f"/app/output/{user['id']}/{name}/{folder_name}")

    # Local filesystem (during active container session)
    if step_dir.exists():
        files = []
        for f in sorted(step_dir.rglob("*")):
            if f.is_file():
                files.append({
                    "name": str(f.relative_to(step_dir)).replace("\\", "/"),
                    "size_bytes": f.stat().st_size,
                    "path": str(f).replace("\\", "/"),
                    "created_at": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                })
        if files:
            return {"files": files}

    # PERSISTENCE_FIX_PLAN PR-2: SQL-first manifest. After a container restart
    # the local FS is empty. If a step_results row exists, its file_manifest
    # lists every file with its size_bytes — no Storage recursive walk needed.
    sql_row = _latest_step_result_row(user["id"], name, step_id)
    if sql_row and sql_row.get("file_manifest"):
        storage_prefix = sql_row.get("storage_prefix") or f"{user['id']}/{name}/{folder_name}"
        created_at = (sql_row.get("created_at") or "")
        # ISO timestamp "2026-08-05T14:28:31+00:00" → "2026-08-05 14:28"
        try:
            created_at = created_at[:16].replace("T", " ")
        except Exception:
            created_at = ""
        files = [
            {
                "name": e.get("path", ""),
                "size_bytes": e.get("size_bytes", 0),
                "path": f"{storage_prefix}/{e.get('path', '')}",
                "created_at": created_at,
            }
            for e in sql_row["file_manifest"]
            if e.get("path")
        ]
        if files:
            return {"files": files}

    # Fallback: list from Supabase Storage (recursive — step outputs live in
    # sub-folders like step1_extraction/accepted/page_*.txt)
    storage_prefix = f"{user['id']}/{name}/{folder_name}"
    try:
        items = list_files_recursive(storage_prefix)
        files = [
            {"name": it["name"], "size_bytes": it.get("metadata", {}).get("size", 0),
             "path": f"{storage_prefix}/{it['name']}", "created_at": ""}
            for it in items
        ]
        return {"files": files}
    except Exception:
        return {"files": []}

@app.get("/projects/{name}/steps/{step_id}/output/{filename:path}")
def get_step_file_content(name: str, step_id: str, filename: str, user: dict = Depends(get_current_user)):
    _SFMAP = {
        "1": "step1_extraction", "1.5": "step1_extraction", "1.6": "step1_extraction",
        "2": "step2_qcm", "3": "step3_metadata", "4": "step4_format",
        "5": "step5_json", "6": "step6_corrections", "7": "step7_categories", "8": "step8_matches",
    }
    folder_name = _SFMAP.get(step_id, f"step{step_id}")
    file_path = Path(f"/app/output/{user['id']}/{name}/{folder_name}") / filename

    ext = Path(filename).suffix.lower()

    # PERSISTENCE_FIX_PLAN PR-3: local FS fast-path (active session).
    # On a wiped /app/output tree (post-restart) the FS misses → we stream
    # from Storage via _stream_file_from_storage which ALSO caches the
    # bytes locally so the next read is a hit.
    if file_path.exists() and file_path.is_file():
        if not str(file_path).startswith(f"/app/output/{user['id']}/{name}"):
            raise HTTPException(status_code=403, detail="Access denied")
        if ext in (".txt", ".json", ".yaml", ".yml", ".md"):
            return {"content": file_path.read_text(encoding="utf-8")}
        return {"binary": True, "size": file_path.stat().st_size}

    # Fallback: read from Supabase Storage (and cache locally).
    storage_path = f"{user['id']}/{name}/{folder_name}/{filename}"
    data = _stream_file_from_storage(storage_path, file_path)
    if data is None:
        raise HTTPException(status_code=404, detail="File not found")
    if ext in (".txt", ".json", ".yaml", ".yml", ".md"):
        try:
            return {"content": data.decode("utf-8")}
        except UnicodeDecodeError:
            # Binary file with a text extension — surface it as binary.
            return {"binary": True, "size": len(data)}
    return {"binary": True, "size": len(data)}


@app.get("/projects/{name}/steps/{step_id}/view/{filename:path}")
def view_step_file(name: str, step_id: str, filename: str, user: dict = Depends(get_current_user)):
    """Serve a file for inline viewing — local FS first, then Supabase signed URL.

    PERSISTENCE_FIX_PLAN PR-3: on a wiped /app/output (container restart) this
    used to silently 404 if get_signed_url raised. Now it best-effort warms
    the local cache from Storage before issuing the redirect, so the next
    caller hits the FS directly.
    """
    _SFMAP = {
        "1": "step1_extraction", "1.5": "step1_extraction", "1.6": "step1_extraction",
        "2": "step2_qcm", "3": "step3_metadata", "4": "step4_format",
        "5": "step5_json", "6": "step6_corrections", "7": "step7_categories", "8": "step8_matches",
    }
    folder_name = _SFMAP.get(step_id, f"step{step_id}")
    file_path = Path(f"/app/output/{user['id']}/{name}/{folder_name}") / filename
    if file_path.exists() and file_path.is_file():
        mime_type, _ = mimetypes.guess_type(str(file_path))
        return FileResponse(path=str(file_path), media_type=mime_type or "text/plain")
    # Storage path; warm the cache best-effort then redirect to the signed URL.
    storage_path = f"{user['id']}/{name}/{folder_name}/{filename}"
    try:
        _stream_file_from_storage(storage_path, file_path)
    except Exception:
        pass  # cache warm is best-effort; redirect below will still work
    try:
        url = get_signed_url(storage_path)
        return RedirectResponse(url)
    except Exception:
        # Last resort: if we warmed the cache during this call, serve from there.
        if file_path.exists() and file_path.is_file():
            mime_type, _ = mimetypes.guess_type(str(file_path))
            return FileResponse(path=str(file_path), media_type=mime_type or "text/plain")
        raise HTTPException(status_code=404, detail="File not found")

@app.get("/projects/{name}/steps/{step_id}/download/{filename:path}")
def download_step_file(name: str, step_id: str, filename: str, user: dict = Depends(get_current_user)):
    _SFMAP = {
        "1": "step1_extraction", "1.5": "step1_extraction", "1.6": "step1_extraction",
        "2": "step2_qcm", "3": "step3_metadata", "4": "step4_format",
        "5": "step5_json", "6": "step6_corrections", "7": "step7_categories", "8": "step8_matches",
    }
    folder_name = _SFMAP.get(step_id, f"step{step_id}")
    file_path = Path(f"/app/output/{user['id']}/{name}/{folder_name}") / filename
    if file_path.exists() and file_path.is_file():
        mime_type, _ = mimetypes.guess_type(str(file_path))
        return FileResponse(path=str(file_path), media_type=mime_type or "application/octet-stream",
                            filename=file_path.name,
                            headers={"Content-Disposition": f'attachment; filename="{file_path.name}"'})
    # Storage path; warm the cache best-effort then redirect to the signed URL.
    storage_path = f"{user['id']}/{name}/{folder_name}/{filename}"
    try:
        _stream_file_from_storage(storage_path, file_path)
    except Exception:
        pass
    try:
        url = get_signed_url(storage_path)
        return RedirectResponse(url)
    except Exception:
        if file_path.exists() and file_path.is_file():
            mime_type, _ = mimetypes.guess_type(str(file_path))
            return FileResponse(path=str(file_path), media_type=mime_type or "application/octet-stream",
                                filename=file_path.name,
                                headers={"Content-Disposition": f'attachment; filename="{file_path.name}"'})
        raise HTTPException(status_code=404, detail="File not found")

@app.get("/projects/{name}/steps/{step_id}/history")
def get_step_output_history(name: str, step_id: str, user: dict = Depends(get_current_user)):
    """List run snapshots — local FS first, then Supabase Storage."""
    _SFMAP = {
        "1": "step1_extraction", "1.5": "step1_extraction", "1.6": "step1_extraction",
        "2": "step2_qcm", "3": "step3_metadata", "4": "step4_format",
        "5": "step5_json", "6": "step6_corrections", "7": "step7_categories", "8": "step8_matches",
    }
    folder_name = _SFMAP.get(step_id, f"step{step_id}")
    current_dir = Path(f"/app/output/{user['id']}/{name}/{folder_name}")
    runs = []

    # Current output — local
    if current_dir.exists():
        current_files = []
        for f in sorted(current_dir.rglob("*")):
            if f.is_file():
                current_files.append({
                    "name": str(f.relative_to(current_dir)).replace("\\", "/"),
                    "size_bytes": f.stat().st_size,
                    "created_at": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                })
        if current_files:
            runs.append({"run_id": "current", "label": "\u25b6 Current Output", "files": current_files})
    else:
        # Fallback: Supabase Storage for current (recursive — outputs live
        # in sub-folders like accepted/page_*.txt)
        try:
            items = list_files_recursive(f"{user['id']}/{name}/{folder_name}")
            current_files = [
                {"name": it["name"], "size_bytes": it.get("metadata", {}).get("size", 0), "created_at": ""}
                for it in items
            ]
            if current_files:
                runs.append({"run_id": "current", "label": "\u25b6 Current Output", "files": current_files})
        except Exception:
            pass

    # History runs
    history_base = Path(f"/app/output/{user['id']}/{name}/_history/step{step_id}")
    if history_base.exists():
        for run_dir in sorted(history_base.iterdir(), reverse=True):
            if run_dir.is_dir():
                files = []
                for f in sorted(run_dir.rglob("*")):
                    if f.is_file():
                        files.append({
                            "name": str(f.relative_to(run_dir)).replace("\\", "/"),
                            "size_bytes": f.stat().st_size,
                            "created_at": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                        })
                runs.append({"run_id": run_dir.name, "label": run_dir.name, "files": files})
    else:
        # Fallback: Supabase Storage for history
        try:
            hist_prefix = f"{user['id']}/{name}/_history/step{step_id}"
            run_dirs = [it for it in list_files(hist_prefix) if not it.get("id")]  # folders have no id
            for rd in sorted(run_dirs, key=lambda x: x["name"], reverse=True):
                rname = rd["name"]
                items = list_files(f"{hist_prefix}/{rname}")
                files = [{"name": it["name"], "size_bytes": it.get("metadata", {}).get("size", 0), "created_at": ""}
                         for it in items if it.get("id")]
                runs.append({"run_id": rname, "label": rname, "files": files})
        except Exception:
            pass

    return {"runs": runs}

@app.get("/projects/{name}/steps/{step_id}/history/{run_id}/{filename:path}")
def get_history_file(name: str, step_id: str, run_id: str, filename: str, user: dict = Depends(get_current_user)):
    """Serve a history file — local FS first, then Supabase signed URL.

    PERSISTENCE_FIX_PLAN PR-3: warms the local cache from Storage on a miss
    so subsequent reads of the same history file are local.
    """
    _SFMAP = {
        "1": "step1_extraction", "1.5": "step1_extraction", "1.6": "step1_extraction",
        "2": "step2_qcm", "3": "step3_metadata", "4": "step4_format",
        "5": "step5_json", "6": "step6_corrections", "7": "step7_categories", "8": "step8_matches",
    }
    folder_name = _SFMAP.get(step_id, f"step{step_id}")
    if run_id == "current":
        local_path = Path(f"/app/output/{user['id']}/{name}/{folder_name}") / filename
        storage_path = f"{user['id']}/{name}/{folder_name}/{filename}"
    else:
        local_path = Path(f"/app/output/{user['id']}/{name}/_history/step{step_id}/{run_id}") / filename
        storage_path = f"{user['id']}/{name}/_history/step{step_id}/{run_id}/{filename}"
    if local_path.exists():
        mime_type, _ = mimetypes.guess_type(str(local_path))
        return FileResponse(str(local_path), media_type=mime_type or "application/octet-stream")
    # Warm cache best-effort before redirecting to the signed URL.
    try:
        _stream_file_from_storage(storage_path, local_path)
    except Exception:
        pass
    try:
        url = get_signed_url(storage_path)
        return RedirectResponse(url)
    except Exception:
        if local_path.exists():
            mime_type, _ = mimetypes.guess_type(str(local_path))
            return FileResponse(str(local_path), media_type=mime_type or "application/octet-stream")
        raise HTTPException(status_code=404, detail="File not found")

@app.post("/projects/{name}/steps/{step_id}/open-sheets")
def open_in_google_sheets(name: str, step_id: str, body: dict, user: dict = Depends(get_current_user)):
    """Upload XLSX to Google Sheets — resolves file from local FS or Supabase Storage."""
    filename = body.get("filename", "")
    print(f"[SHEETS] Request: project={name}, step={step_id}, file={filename}, user={user['id']}")
    _SFMAP = {
        "1": "step1_extraction", "1.5": "step1_extraction", "1.6": "step1_extraction",
        "2": "step2_qcm", "3": "step3_metadata", "4": "step4_format",
        "5": "step5_json", "6": "step6_corrections", "7": "step7_categories", "8": "step8_matches",
    }
    folder = _SFMAP.get(step_id, f"step{step_id}")
    file_path = Path(f"/app/output/{user['id']}/{name}/{folder}") / filename

    # If not local, download from Supabase to a temp file
    if not file_path.exists():
        print(f"[SHEETS] File not local, downloading from Supabase...")
        import tempfile
        # Use raw path segments (supabase-py handles any required escaping internally)
        storage_path = f"{user['id']}/{name}/{folder}/{filename}"
        print(f"[SHEETS] Supabase path: {storage_path}")
        try:
            data = read_bytes_file(storage_path)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
            tmp.write(data)
            tmp.close()
            file_path = Path(tmp.name)
            print(f"[SHEETS] Downloaded {len(data)} bytes to {file_path}")
        except Exception as e:
            print(f"[SHEETS] File not found in Supabase either: {e}")
            raise HTTPException(status_code=404, detail="File not found")

    else:
        print(f"[SHEETS] File found locally: {file_path} ({file_path.stat().st_size} bytes)")

    # Check Google client secret exists
    if not Path(GOOGLE_CLIENT_SECRET_PATH).exists():
        print(f"[SHEETS] ERROR: Google client secret not found at {GOOGLE_CLIENT_SECRET_PATH}")
        raise HTTPException(status_code=500, detail="Google client secret not configured on server")

    user_db_id = get_db_user_id(user)
    creds = _get_google_creds(user_db_id)
    if not creds:
        print(f"[SHEETS] No Google creds for user {user['id']} (db_id={user_db_id}) — returning 401 NOT_AUTHORIZED")
        raise HTTPException(status_code=401, detail="NOT_AUTHORIZED")
    try:
        from googleapiclient.http import MediaFileUpload
        print(f"[SHEETS] Uploading to Google Drive...")
        drive_service = build("drive", "v3", credentials=creds)
        file_metadata = {"name": file_path.stem, "mimeType": "application/vnd.google-apps.spreadsheet"}
        media = MediaFileUpload(str(file_path),
                                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                resumable=True)
        uploaded = drive_service.files().create(body=file_metadata, media_body=media,
                                                fields="id,webViewLink").execute()
        sheets_url = uploaded.get("webViewLink")
        print(f"[SHEETS] Success! URL={sheets_url}")
        return {"url": sheets_url, "id": uploaded.get("id")}
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[SHEETS] Upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"Google Sheets upload failed: {str(e)}")

@app.post("/projects/{name}/step8/export-existing")
async def export_matches_only(name: str, body: dict, user: dict = Depends(get_current_user)):
    _apply_user_env(user)
    task = asyncio.ensure_future(_export_step8_task(name, user["id"], body))
    job_manager.set_running(name, "8-export", task)
    _job_user_ids[job_manager.key(name, "8-export")] = user["id"]
    return {"job_id": f"{name}-8-export-001"}

async def _export_step8_task(project: str, email: str, body: dict):
    ctx_data = get_or_create(project, email)
    context = ctx_data["context"]
    tracker = ctx_data["tracker"]
    def log_callback(line: dict):
        job_manager.append_log(project, "8-export", line)
    def _run():
        with LogCapture(log_callback):
            from modules.step8_matcher import Step8Matcher
            matcher = Step8Matcher(tracker, context)
            # Override config from body
            if body.get("color_green"): matcher.color_green = float(body["color_green"])
            if body.get("color_yellow"): matcher.color_yellow = float(body["color_yellow"])
            # Patch input for the export prompts
            def _export_auto(prompt=""):
                p = str(prompt).lower()
                if "export custom xlsx" in p: return "y"
                if "select [1/2]" in p: return "1"  # range mode
                if "from %" in p: return str(int(float(body.get("export_from", 0)) * 100))
                if "to   %" in p or "to %" in p: return str(int(float(body.get("export_to", 0.6)) * 100))
                if "output filename" in p: return body.get("export_filename", "custom_export")
                return ""
            import builtins
            builtins.input = _export_auto
            matcher.export_from_existing()
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _run)
        job_manager.set_done(project, "8-export")
        log_callback({"ts": datetime.now().strftime("%H:%M:%S"), "type": "ok", "text": "✅ Custom export complete."})
    except Exception as e:
        job_manager.set_error(project, "8-export")
        log_callback({"ts": datetime.now().strftime("%H:%M:%S"), "type": "error", "text": f"❌ Export failed: {str(e)}"})

# --- Step 8 merge-outputs manifest (PR-S8-2) ---

@app.get("/projects/{name}/step8/merge-outputs")
async def step8_merge_outputs(name: str, user: dict = Depends(get_current_user)):
    """Return a manifest of the 4 merge-phase artifacts produced by Step 8:
    `<ref>_UPDATED.xlsx`, `merge_report.json`, `unmerged_qcms.xlsx`, and the
    summary. Files themselves are served by the generic per-step file route:
    /projects/{name}/steps/8/download/<filename>.

    If Step 8 has not produced any merge outputs yet, returns an empty
    manifest with HTTP 200 (the frontend treats this as "not yet run").

    PERSISTENCE_FIX_PLAN PR-3: when the local FS is wiped after a container
    restart, falls back to (a) the step_results row's file_manifest to surface
    the artifact filenames and (b) reading step8_summary.json from Supabase
    Storage. The per-file download URLs still resolve via the generic
    /download route, which itself now streams from Storage.
    """
    _apply_user_env(user)
    ctx_data = get_or_create(name, user["id"])
    context = ctx_data["context"]
    out_dir = context.base_path / "step8_matches"
    storage_prefix = f"{user['id']}/{name}/step8_matches"

    def _info(filename: str):
        p = out_dir / filename
        if p.exists():
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            return {"filename": filename, "size_bytes": size,
                    "url": f"/projects/{name}/steps/8/download/{filename}"}
        # PERSIST PR-3: look the file up in the SQL manifest or Storage.
        sql_row = _latest_step_result_row(user["id"], name, "8")
        if sql_row:
            for e in (sql_row.get("file_manifest") or []):
                if e.get("path") == filename:
                    return {"filename": filename, "size_bytes": int(e.get("size_bytes") or 0),
                            "url": f"/projects/{name}/steps/8/download/{filename}"}
        # Last resort: probe Storage directly.
        try:
            if file_exists(f"{storage_prefix}/{filename}"):
                return {"filename": filename, "size_bytes": 0,
                        "url": f"/projects/{name}/steps/8/download/{filename}"}
        except Exception:
            pass
        return None

    manifest: dict = {"files": {}}

    # Always try the summary - it tells the UI whether a merge happened.
    summary_path = out_dir / "step8_summary.json"
    summary_info = _info("step8_summary.json")
    summary = None
    if summary_info:
        manifest["files"]["summary"] = summary_info
        try:
            if summary_path.exists():
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            else:
                # Pull from Storage and decode (don't cache large summary locally;
                # it's tiny so decoding in-memory is fine).
                summary_text = read_file(f"{storage_prefix}/step8_summary.json")
                summary = json.loads(summary_text)
        except Exception as e:
            print(f"[STEP8-MANIFEST] Could not parse summary: {e}")
        if summary is None:
            # Last-ditch fallback: the step_results.payload JSONB stores the
            # same fields when the folder was empty.
            try:
                sql_row = _latest_step_result_row(user["id"], name, "8")
                if sql_row and sql_row.get("payload"):
                    summary = sql_row["payload"]
            except Exception:
                pass
        if summary is not None:
            manifest["summary"] = summary
            merge_block = summary.get("merge", {}) if isinstance(summary, dict) else {}
            if merge_block:
                # Find the ref_UPDATED filename from the merge block (ref_db_name-based)
                ref_updated_name = merge_block.get("ref_updated_filename")
                merge_report_name = merge_block.get("merge_report_filename")
                unmerged_name = merge_block.get("unmerged_filename")
                if ref_updated_name:
                    info = _info(ref_updated_name)
                    if info: manifest["files"]["ref_updated"] = info
                if merge_report_name:
                    info = _info(merge_report_name)
                    if info: manifest["files"]["merge_report"] = info
                if unmerged_name:
                    info = _info(unmerged_name)
                    if info: manifest["files"]["unmerged"] = info

    return manifest


# --- Auto Run Logic ---

@app.post("/projects/{name}/autorun")
async def start_autorun_sequence(name: str, body: dict, user: dict = Depends(get_current_user)):
    _apply_user_env(user)
    # Sequential execution of multiple steps
    asyncio.ensure_future(_autorun_task(name, user["id"], body))
    return {"job_id": f"{name}-autorun-001"}

async def _autorun_task(project: str, email: str, body: dict):
    start = str(body.get("start_step", "1"))
    end   = str(body.get("end_step",   "7"))
    run_config = body.get("run_config", {})
    
    # Valid step sequence. Steps 3, 4 and 5 are no longer in the visible
    # sequence: Step 3 now fires inside Step 2's task via
    # run_post_step2_metadata (see _run_step_task), and Steps 4/5 fire inside
    # that same cascade via run_post_step3_build. If run_config.step3/step4/
    # step5 are sent by a legacy client they are silently ignored.
    sequence = ["1", "1.5", "1.6", "2", "6", "7", "8"]
    
    # Filter sequence by start/end constraints
    try:
        start_idx = sequence.index(str(start))
        end_idx = sequence.index(str(end))
        active_sequence = sequence[start_idx:end_idx+1]
    except ValueError:
        return # Silent fail for bad range

    for step_id in active_sequence:
        cfg = run_config.get(f"step{step_id}", {})
        # Re-use the step task runner logic
        await _run_step_task(project, email, step_id, cfg)
        
        # Stop sequence if any step fails
        if job_manager.get_status(project, step_id) == "error":
            break
