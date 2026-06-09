# QCM Extractor — Handover & Summary Report

This document serves as a complete record of the features, bug fixes, deployment setups, and environment credentials configured during this pair programming session. Use this file as context in your next conversation to resume work instantly.

---

## 🚀 Deployment & Environments

### 1. Backend (Hugging Face Spaces)
*   **Space URL:** `https://huggingface.co/spaces/ayoubi8/qcm-extractor`
*   **Live API URL:** `https://ayoubi8-qcm-extractor.hf.space`
*   **Git Remote Name:** `space`
*   **Git Push Target:** `git push space main`
*   **Access Token (HF Space):** `hf_CXyQ...` (configured as basic auth URL in the git remote)

### 2. Frontend (Vercel)
*   **Vercel Live URL:** `https://qcm-extractor-frontend.vercel.app`
*   **Repository:** Deployed from frontend directory, synced with frontend updates.

### 3. Database & File Storage (Supabase)
*   **Supabase Project URL:** `https://zwdobdongxrsroglhsuq.supabase.co`
*   **Bucket Name:** `qcm-projects` (private)
*   **Note:** Ephemeral storage on Hugging Face is bypassed. All files, PDFs, step results, and configuration settings are synced with and stored in Supabase.

---

## 🛠️ Summary of Features & Fixes Added

### 1. Google Sheets Integration & OAuth Flow
*   **OAuth Redirect Hijack Fix:** Resolved an issue where the Google Sheets OAuth process would hijack the main application tab instead of utilizing the pre-opened blank tab.
*   **Automatic Redirect:** Added logic so that once the Google OAuth callback executes successfully, the blank redirect page automatically closes or redirects the user straight back to their newly created Google Sheet.

### 2. Ephemeral Storage PDF Restore
*   **PDF File-not-Found Fix:** Because Hugging Face Spaces filesystem is ephemeral, restarting the space wiped local PDFs. We updated the backend to save the absolute local path to Supabase `project.json` and added a pre-step restore task (`_run_step_task`).
*   **Behavior:** On every pipeline step start, if the local `source.pdf` is missing, the backend automatically downloads it from Supabase storage and places it back into the local workspace folder before execution.

### 3. Settings & Model Config Persistence
*   **The Issue:** When you pushed a new Git version, Hugging Face rebuilt the container, wiping `/app/.env` and resetting step model settings and API keys to empty/defaults.
*   **The Fix:** 
    *   **Supabase Backup:** Updated `write_env_keys` to upload the active `.env` config file to Supabase storage at `config/.env` whenever saved.
    *   **Startup Restore:** Added an automatic check on container startup to download `config/.env` from Supabase storage, write it back to the local folder, and hot-reload it into python's `os.environ` with `override=True`.
    *   **Dynamic Paths:** Made paths for `.env` files dynamic in `env_manager.py` and `real_api.py` so they map correctly on both local development environments (Windows) and HF production containers.

### 4. OpenRouter Authentication Safeguards & Diagnostics
*   **API Key Masking Overwrite Fix:** Added a safeguard inside `write_env_keys` to filter out values containing `*` or equal to `****`. This prevents the UI from accidentally overwriting raw keys on disk with the masked visual strings shown in inputs.
*   **Admin DB Profile Lookup:** Modified `get_current_user` to search the database first for the admin profile to load your custom DB-saved API Key, while forcing the account `"id"` to remain `"admin"` to preserve project folder mapping consistency (preventing empty folder bugs).
*   **Key Mapping:** Updated the environment exporter `_apply_user_env` to set `os.environ["OPENROUTER_API_KEY"]` equal to the user's profile API key during execution runs.
*   **Diagnostics:** Added a masked key diagnostic print in `OpenRouterClient`'s constructor. It now prints the loaded key (masked) to the step output console, making it easy to see if a key is correctly configured, empty, or corrupted.

---

## 📋 Diagnostics for OpenRouter 401
If you ever encounter `401: Missing Authentication header` again:
1.  **Check Key Value in Logs:** Look at the step execution log and inspect the printed `Loaded API Key: sk-or-v1...`.
2.  **Verify Prefix:** Ensure it begins with `sk-or-v1-`. A key starting with any other prefix (like `sk-traTw...`) is NOT an OpenRouter key (likely a DeepSeek or other provider key) and will be rejected at the gateway.
3.  **No Whitespaces:** Verify you did not copy-paste trailing newlines or carriage returns with your key.
