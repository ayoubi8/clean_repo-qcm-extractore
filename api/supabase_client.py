import os
from supabase import create_client, Client

# SUPABASE_URL and SUPABASE_KEY should be set in the environment
# For local dev, you can add them to your .env file
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    # If not in environment, we check if we're in a dev environment or if we should fail
    # For now, we raise a clear error to ensure the developer sets them
    print("[SUPABASE] ERROR: SUPABASE_URL or SUPABASE_KEY not found in environment.")
    # In production (Hugging Face / Vercel), these MUST be set as secrets.
    # For local testing, you can temporarily hardcode them or use load_dotenv.

# Initialize singleton
_supabase: Client = None

def get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
             raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in environment variables.")
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase

def check_supabase_connection() -> None:
    try:
        sb = get_supabase()
        # Simple test query
        sb.table("users").select("count", count="exact").limit(1).execute()
        print("[SUPABASE] Connection OK")
    except Exception as e:
        print(f"[SUPABASE] Connection FAILED: {e}")
        # We don't necessarily want to crash the whole app on startup if Supabase is down, 
        # but we should definitely log it.
