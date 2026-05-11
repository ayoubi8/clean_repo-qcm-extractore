from pathlib import Path
import os

ENV_PATH = Path("/app/.env")
EDITABLE_KEYS = {
    "OPENROUTER_API_KEY", "ENABLE_CACHING",
    "STEP1_MODEL", "STEP1_FALLBACK_MODEL",
    "STEP1_5_MODEL", "STEP1_5_FALLBACK_MODEL",
    "STEP1_6_MODEL", "STEP1_6_FALLBACK_MODEL",
    "STEP2_MODEL", "STEP2_FALLBACK_MODEL",
    "STEP3_MODEL", "STEP3_FALLBACK_MODEL",
    "STEP6_TEXT_MODEL", "STEP6_TEXT_FALLBACK_MODEL",
    "STEP6_ALL_PAGES_MODEL", "STEP6_ALL_PAGES_FALLBACK_MODEL",
    "STEP6_AI_MODEL", "STEP6_AI_FALLBACK_MODEL",
    "STEP7_MODEL", "STEP7_FALLBACK_MODEL"
}

def read_env() -> dict:
    result = {}
    if not ENV_PATH.exists():
        return result
    try:
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                result[key.strip()] = val.strip().strip('"').strip("'")
    except:
        pass
    return result

def read_env_raw() -> dict:
    """Returns all env values unmasked — for settings UI only."""
    return read_env()  # read_env already returns raw values; masking happens in real_api.py

def mask(val: str) -> str:
    if len(val) <= 8:
        return "****"
    return val[:8] + "****" + val[-4:]

def write_env_keys(updates: dict):
    """Only updates EDITABLE_KEYS, preserves all other lines."""
    if not ENV_PATH.exists():
        ENV_PATH.touch()
        
    lines = ENV_PATH.read_text().splitlines()
    updated_keys = set()
    new_lines = []
    
    # Track which keys we already updated from the file
    processed_keys = set()
    
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates and key in EDITABLE_KEYS:
                new_lines.append(f"{key}={updates[key]}")
                updated_keys.add(key)
                processed_keys.add(key)
                continue
        new_lines.append(line)
        
    # Append any keys that weren't in the file yet
    for key, val in updates.items():
        if key in EDITABLE_KEYS and key not in processed_keys:
            new_lines.append(f"{key}={val}")
            updated_keys.add(key)
            
    ENV_PATH.write_text("\n".join(new_lines) + "\n")
    return list(updated_keys)
