import sys
import json
import uuid
import os
from datetime import datetime
from supabase import create_client, Client

# PURPOSE: One-time import of existing users.json into Supabase.
# Safe to run multiple times (upsert, not insert).

def migrate():
    """
    Standalone migration script.
    Usage: python migrate_users.py [path_to_users.json]
    """
    # 1. Read /app/auth/users.json (or accept path as CLI arg)
    json_path = sys.argv[1] if len(sys.argv) > 1 else "/app/auth/users.json"
    
    if not os.path.exists(json_path):
        print(f"Error: File not found at {json_path}")
        print("Usage: python migrate_users.py [path_to_users.json]")
        return

    # 2. Connect to Supabase using env vars
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    
    if not url or not key:
        print("Error: SUPABASE_URL and SUPABASE_KEY environment variables must be set.")
        return

    sb: Client = create_client(url, key)

    try:
        with open(json_path, "r") as f:
            users = json.load(f)
    except Exception as e:
        print(f"Error reading JSON: {e}")
        return

    print(f"Starting migration of {len(users)} users...")

    success_count = 0
    for u in users:
        email = u.get("email", "unknown")
        try:
            # 3. Map fields and set legacy_hash = True
            record = {
                "id": u.get("id", str(uuid.uuid4())),
                "email": email,
                "password_hash": u.get("password_hash"),
                "is_approved": bool(u.get("is_approved", False)),
                "is_admin": bool(u.get("is_admin", False)),
                "api_key": u.get("api_key", ""),
                "allowed_models": u.get("allowed_models", {}),
                "legacy_hash": True, # All existing users use the old SHA-256 format
                "created_at": u.get("created_at", datetime.utcnow().isoformat())
            }
            
            # Upsert into "users" table
            sb.table("users").upsert(record).execute()
            print(f"[OK] imported {email}")
            success_count += 1
        except Exception as e:
            print(f"[FAIL] {email}: {e}")

    # 4. Print final summary
    print(f"\nImported: {success_count}/{len(users)} users")

if __name__ == "__main__":
    migrate()
