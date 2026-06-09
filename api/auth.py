import os
import json
import hashlib
import secrets
import uuid
import threading
import time
import bcrypt
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List
from jose import JWTError, jwt
from fastapi import Header, HTTPException, Depends, status
from supabase_client import get_supabase

# --- Rate Limiting ---
_rate_lock = threading.Lock()
_rate_store: dict = defaultdict(list)

LOGIN_LIMIT    = 5   # max login attempts per window
REGISTER_LIMIT = 3   # max register attempts per window
WINDOW_SECONDS = 60  # sliding window in seconds

def check_rate_limit(ip: str, action: str) -> None:
    """
    Sliding window rate limiter. Raises HTTP 429 if the IP has exceeded
    the allowed attempts for the given action in the past WINDOW_SECONDS.
    """
    now   = time.time()
    key   = f"{action}:{ip}"
    limit = LOGIN_LIMIT if action == "login" else REGISTER_LIMIT

    with _rate_lock:
        # Remove timestamps older than the window
        _rate_store[key] = [t for t in _rate_store[key] if now - t < WINDOW_SECONDS]

        if len(_rate_store[key]) >= limit:
            oldest      = _rate_store[key][0]
            retry_after = int(WINDOW_SECONDS - (now - oldest)) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Too many {action} attempts. Try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)}
            )

        _rate_store[key].append(now)

# --- Configuration ---
SECRET    = os.environ.get("JWT_SECRET", "changeme-dev-secret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120

ADMIN_EMAIL    = os.environ.get("ADMIN_EMAIL",    "ayoubdjelti02@gmail.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "AyouB987")

# ---------------------------------------------------------------------------
# Password Hashing (bcrypt + legacy support)
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def is_legacy_hash(hashed: str) -> bool:
    """Old format was 'salt:sha256hex' — contains a colon and no $2b$ prefix."""
    return not hashed.startswith("$2b$") and ":" in hashed


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a stored hash (supports legacy SHA-256 and bcrypt)."""
    if is_legacy_hash(hashed_password):
        # Verify old SHA-256 format
        try:
            salt, pw_hash = hashed_password.split(":", 1)
            expected = hashlib.sha256((salt + plain_password).encode()).hexdigest()
            return secrets.compare_digest(expected, pw_hash)
        except Exception:
            return False

    # Verify bcrypt
    try:
        return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())
    except Exception:
        return False


def rehash_if_legacy(plain_password: str, stored_hash: str) -> Optional[str]:
    """Returns a new bcrypt hash if stored_hash is legacy, else None."""
    if is_legacy_hash(stored_hash):
        return hash_password(plain_password)
    return None


# ---------------------------------------------------------------------------
# User CRUD helpers (Supabase)
# ---------------------------------------------------------------------------

def load_users() -> List[dict]:
    """Fetch all users from Supabase."""
    sb = get_supabase()
    res = sb.table("users").select("*").order("created_at").execute()
    return res.data or []


def find_user_by_email(email: str) -> Optional[dict]:
    """Find a user by email in Supabase."""
    sb = get_supabase()
    res = sb.table("users").select("*").eq("email", email).limit(1).execute()
    return res.data[0] if res.data else None


def find_user_by_id(user_id: str) -> Optional[dict]:
    """Find a user by ID in Supabase."""
    sb = get_supabase()
    res = sb.table("users").select("*").eq("id", user_id).limit(1).execute()
    return res.data[0] if res.data else None


def add_user(user_dict: dict):
    """Insert a new user row into Supabase."""
    sb = get_supabase()
    res = sb.table("users").insert(user_dict).execute()
    return res.data[0]


def update_user_field(uid: str, field: str, value):
    """Update a specific field for a user in Supabase."""
    sb = get_supabase()
    sb.table("users").update({field: value}).eq("id", uid).execute()


def delete_user(uid: str):
    """Delete a user from Supabase."""
    sb = get_supabase()
    sb.table("users").delete().eq("id", uid).execute()


def ensure_admin_exists() -> None:
    """
    Seed the admin user into Supabase on startup if not already present.
    Safe to call on every restart (idempotent).
    """
    try:
        existing = find_user_by_email(ADMIN_EMAIL)
        if existing:
            # Make sure the admin flag is set correctly
            if not existing.get("is_admin"):
                update_user_field(existing["id"], "is_admin", True)
                update_user_field(existing["id"], "is_approved", True)
            print(f"[AUTH] Admin user already exists: {ADMIN_EMAIL}")
            return

        # Create admin user with bcrypt-hashed password
        admin_user = {
            "id":             str(uuid.uuid4()),
            "email":          ADMIN_EMAIL,
            "password_hash":  hash_password(ADMIN_PASSWORD),
            "is_approved":    True,
            "is_admin":       True,
            "api_key":        None,
            "allowed_models": [],
            "created_at":     datetime.utcnow().isoformat(),
        }
        add_user(admin_user)
        print(f"[AUTH] Admin user created: {ADMIN_EMAIL}")
    except Exception as e:
        print(f"[AUTH] Warning: could not seed admin user: {e}")


# ---------------------------------------------------------------------------
# JWT Helpers
# ---------------------------------------------------------------------------

def create_access_token(user_id: str, email: str, is_admin: bool) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {
        "sub":      user_id,
        "email":    email,
        "is_admin": is_admin,
        "type":     "access",
        "exp":      expire
    }
    return jwt.encode(to_encode, SECRET, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


# ---------------------------------------------------------------------------
# Refresh Token Helpers (Supabase)
# ---------------------------------------------------------------------------

def create_refresh_token(user_id: str) -> str:
    """Generate a secure random refresh token, store its hash in Supabase."""
    raw_token  = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = (datetime.utcnow() + timedelta(days=30)).isoformat()

    sb = get_supabase()
    sb.table("refresh_tokens").insert({
        "token_hash": token_hash,
        "user_id": user_id,
        "expires_at": expires_at,
        "revoked": False
    }).execute()
    
    return raw_token


def verify_and_rotate_refresh_token(raw_token: str) -> tuple:
    """
    Validate a refresh token from Supabase. If valid, revoke it
    and issue a new access_token + refresh_token.
    """
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    sb = get_supabase()
    res = sb.table("refresh_tokens").select("*").eq("token_hash", token_hash).limit(1).execute()

    if not res.data:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    row = res.data[0]
    # Handle ISO format with 'Z' or offset if present
    expires_at_str = row["expires_at"].replace('Z', '+00:00')
    expires_at = datetime.fromisoformat(expires_at_str)
    
    if row["revoked"] or datetime.utcnow() > expires_at.replace(tzinfo=None):
        raise HTTPException(status_code=401, detail="Refresh token expired or revoked")

    # Revoke old token
    sb.table("refresh_tokens").update({"revoked": True}).eq("token_hash", token_hash).execute()

    user = find_user_by_id(row["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists")

    new_access  = create_access_token(user["id"], user["email"], user.get("is_admin", False))
    new_refresh = create_refresh_token(user["id"])
    return new_access, new_refresh


def revoke_all_refresh_tokens(user_id: str):
    """Revoke all refresh tokens for a user in Supabase."""
    sb = get_supabase()
    sb.table("refresh_tokens").update({"revoked": True}).eq("user_id", user_id).execute()


# ---------------------------------------------------------------------------
# FastAPI Dependencies
# ---------------------------------------------------------------------------

async def get_current_user(authorization: str = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
        )

    token   = authorization.split(" ")[1]
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    email = payload.get("email")
    if email == ADMIN_EMAIL:
        user = find_user_by_email(ADMIN_EMAIL)
        if user:
            user_copy = dict(user)
            user_copy["id"] = "admin"
            return user_copy
        return {
            "email":       ADMIN_EMAIL,
            "is_admin":    True,
            "is_approved": True,
            "id":          "admin"
        }

    user_id = payload.get("sub")
    user    = find_user_by_id(user_id)
    if not user or not user.get("is_approved"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or not approved",
        )

    return user


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user
