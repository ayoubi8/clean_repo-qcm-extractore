from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json
from datetime import datetime

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

MOCK_PROJECTS = [
    {"name": "Le_Carabin_UroNephro", "last_step": 6, "last_modified": "2026-04-22T18:30:00Z", "total_tokens": 45201},
    {"name": "Cardio_Clinical_Base",  "last_step": 8, "last_modified": "2026-04-21T10:00:00Z", "total_tokens": 12880},
]

MOCK_COSTS = {
  "per_model": {
    "vision_ocr":  {"cost": 0.0042, "tokens": {"prompt": 8200,  "completion": 4200}},
    "deepseek_r1": {"cost": 0.0081, "tokens": {"prompt": 22000, "completion": 13200}},
    "llama_3.3":   {"cost": 0.0012, "tokens": {"prompt": 3100,  "completion": 1000}},
  },
  "per_step": {
    "step1": {"total_cost": 0.0042, "call_count": 142, "total_tokens": {"prompt": 8200,  "completion": 4200}},
    "step2": {"total_cost": 0.0061, "call_count": 142, "total_tokens": {"prompt": 18000, "completion": 8000}},
    "step6": {"total_cost": 0.0032, "call_count": 50,  "total_tokens": {"prompt": 7100,  "completion": 2200}},
  },
  "total_cost": 0.0135,
  "total_tokens": 52700
}

@app.get("/projects")
def list_projects():
    return {"projects": MOCK_PROJECTS}

@app.post("/projects")
def create_project(body: dict):
    return {"name": body.get("name"), "last_step": 0, "status": "created"}

@app.post("/projects/{name}/steps/{step_id}/run")
def run_step(name: str, step_id: str, body: dict):
    return {"job_id": f"{name}-{step_id}-001"}

@app.get("/projects/{name}/steps/{step_id}/status")
def step_status(name: str, step_id: str):
    # Simulate output existing for Step 1 for demonstration
    exists = (step_id == "1")
    return {"status": "done", "output_exists": exists}

@app.get("/projects/{name}/costs")
def get_costs(name: str):
    return MOCK_COSTS

@app.post("/projects/{name}/costs/save")
def save_costs(name: str):
    return {"saved_to": f"output/{name}/total_costs.json"}

@app.post("/projects/{name}/step8/export-existing")
def export_existing(name: str):
    return {"success": True, "file_path": f"output/{name}/step8_export.xlsx", "record_count": 87}

@app.get("/env")
def get_env():
    return {"OPENROUTER_API_KEY": "sk-or-v1-****...****", "ENABLE_CACHING": "true"}

@app.post("/env")
def save_env(body: dict):
    return {"updated": list(body.keys())}

@app.get("/templates")
def get_templates():
    return ["pediat", "med-gen", "neuro", "cardio", "pneumo"]

@app.get("/config/batch")
def get_batch_config():
    return {
        "batch_mode": {
            "enabled": True,
            "start_step": 1,
            "end_step": 7,
            "pause_for_verification": False
        },
        "extraction": {
            "method": "vision_ocr",
            "ocr_guidance": "Two-column layout. PRESERVE ALL TABLES...",
            "model": "google/gemini-2.0-flash-lite-001"
        },
        "qcm_extraction": {
            "page_range": "all",
            "model_primary": "google/gemini-2.5-flash-lite-preview-09-2025",
            "model_fallback": "google/gemini-2.0-flash-lite-001"
        },
        "metadata": { "fields": {}, "global_pages": [1] },
        "template": { "auto_select": True, "name": "pediat" },
        "corrections": {
            "source": "page_text",
            "correction_search_mode": "all_pages",
            "ai_mode": "batch"
        },
        "folder_batch": {
            "enabled": False,
            "input_folder": "C:/Users/ayoub/.../pdf_splits/QUIZZY Endo",
            "file_pattern": "*.pdf",
            "output_base": "output/batch_results",
            "parallel_processing": False
        }
    }

@app.post("/config/batch")
def save_batch_config(body: dict):
    return {"saved": True}

@app.post("/projects/{name}/autorun")
def start_autorun(name: str, body: dict):
    return {"job_id": f"{name}-autorun-001"}

@app.websocket("/ws/log/{project}/{step_id}")
async def websocket_endpoint(websocket: WebSocket, project: str, step_id: str):
    await websocket.accept()
    
    # Send 3 fake log lines
    logs = [
        {"type": "info", "text": f"Initializing Step {step_id} for {project}..."},
        {"type": "info", "text": "Loading configuration and dependencies..."},
        {"type": "ok", "text": f"Step {step_id} completed successfully."}
    ]
    
    for log in logs:
        await asyncio.sleep(1)
        log["ts"] = datetime.now().strftime("%H:%M:%S")
        await websocket.send_text(json.dumps(log))
        
    await asyncio.sleep(0.5)
    await websocket.close()

@app.get("/costs/weekly")
def get_weekly_costs():
    return {
        "2026-W14": {"cost": 0.0045, "projects": ["Cardio_Clinical_Base"]},
        "2026-W15": {"cost": 0.0082, "projects": ["Le_Carabin_UroNephro"]},
        "2026-W16": {"cost": 0.0031, "projects": ["Le_Carabin_UroNephro", "Cardio_Clinical_Base"]},
        "2026-W17": {"cost": 0.0135, "projects": ["Le_Carabin_UroNephro"]},
    }
