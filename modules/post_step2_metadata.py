"""Post-Step-2 Auto-Enrich + Build.

Merges the old Step 3 (metadata detection) + the already-shipped Step 4/5
auto-build (`modules/post_step3_build.py`) into a single invisible backend
operation fired right after Step 2 succeeds.

After the Step 2+3 frontend merge, "Step 2" is the only visible extract+enrich
step. This module runs Step 3 (metadata) then chains the Step 4+5 build, so
the whole extraction → enrichment → build pipeline fires as one cascade
inside the Step 2 background task.

Idempotent / fast-path (Q8): if `step3_metadata/accepted/*.json` already
exists, Step 3 is skipped — re-running Step 2 only re-extracts QCMs and lets
the previously-detected metadata stand. To force re-enrichment, delete the
`step3_metadata/accepted/` folder before re-running Step 2.
"""
from pathlib import Path
from typing import Any, Dict, Optional

from modules.step3_metadata import Step3Metadata
from modules.post_step3_build import run_post_step3_build


# Default Step 3 config used when the /steps/2/run caller does not send one.
# Mirrors the frontend `step3Config` default in
# frontend/src/store/pipelineStore.ts:64-75 so the cascade behaves like the
# old manual /steps/3/run with the default store config.
DEFAULT_STEP3_CONFIG: Dict[str, Any] = {
    "fields": {
        "year":          {"strategy": "per_qcm",  "value": None},
        "source":        {"strategy": "skip",      "value": "Externat"},
        "category":      {"strategy": "global",    "value": None},
        "subcategory":   {"strategy": "per_qcm",  "value": None},
        "clinical_case": {"strategy": "per_group", "value": None},
    },
    "global_pages": "1",
}


def _accepted_qcms_exist(context) -> bool:
    """True if Step 2 produced at least one accepted QCM JSON file."""
    try:
        d = context.get_path("step2_qcm", "accepted")
    except Exception:
        return False
    if not Path(d).exists():
        return False
    return any(Path(d).glob("*.json"))


def _metadata_already_done(context) -> bool:
    """Q8 fast-path: True if Step 3 already produced accepted metadata."""
    try:
        d = context.get_path("step3_metadata", "accepted")
    except Exception:
        return False
    if not Path(d).exists():
        return False
    return any(Path(d).glob("*.json"))


def run_post_step2_metadata(tracker, context, user_id: str, project: str,
                            step3_config: Optional[Dict] = None) -> Dict:
    """Run Step 3 (metadata) then chain the Step 4+5 auto-build.

    Must be called from a background thread (it runs LLM calls). The caller
    owns `job_manager.set_done` bookkeeping for steps 3/4/5 — this function
    only performs the work and reports the result.

    Returns:
        {"status": "ok",        "step3": "done|skipped", "build": {...}}
        {"status": "no_qcms",   "step3": "skipped"}        # Step 2 empty
        {"status": "error",     "stage": "step3|build", "detail": str}
    """
    print("\n" + "=" * 60)
    print("POST-STEP-2 AUTO-ENRICH  (Step 3 metadata + Step 4-5 build)")
    print("=" * 60)

    # 1. Guard: nothing to do if Step 2 produced no accepted QCMs.
    if not _accepted_qcms_exist(context):
        print("[AUTO-ENRICH] No accepted QCMs found after Step 2 — skipping cascade.")
        return {"status": "no_qcms", "step3": "skipped"}

    # 2. Step 3 (metadata) — skip if already done (Q8 fast-path).
    if _metadata_already_done(context):
        print("[AUTO-ENRICH] Step 3 accepted metadata already present — "
              "skipping Step 3 (Q8 fast-path). To force re-enrichment, delete "
              "step3_metadata/accepted/ before re-running Step 2.")
        step3_status = "skipped"
    else:
        cfg = step3_config or DEFAULT_STEP3_CONFIG
        fields = cfg.get("fields", {})
        global_pages_raw = cfg.get("global_pages", "1")
        # Normalize global_pages → list[int] (mirrors real_api.py step_map["3"]).
        gp_list = [int(p.strip())
                    for p in str(global_pages_raw).split(",")
                    if p.strip().isdigit()]
        print(f"[AUTO-ENRICH] Running Step 3 (metadata) — "
              f"fields={list(fields.keys())}, global_pages={gp_list}")
        try:
            Step3Metadata(tracker, context).run(
                auto_mode=True,
                config=fields,
                global_pages=gp_list,
            )
            step3_status = "done"
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[AUTO-ENRICH] ⚠️ Step 3 failed: {e}")
            return {"status": "error", "stage": "step3", "detail": str(e)}

    # 3. Chain the already-shipped Step 4+5 auto-build. run_post_step3_build
    # internally checks for accepted Step3 QCMs and returns {"status":"no_qcms"}
    # when absent — we propagate that.
    print("[AUTO-ENRICH] Chaining Step 4+5 auto-build (run_post_step3_build)...")
    try:
        build = run_post_step3_build(tracker, context, user_id, project)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[AUTO-ENRICH] ⚠️ Step 4+5 build failed: {e}")
        return {"status": "error", "stage": "build", "detail": str(e),
                "step3": step3_status}

    status = build.get("status", "ok")
    if status == "ok":
        total = build.get("step5", {}).get("total_qcms", 0)
        print(f"[AUTO-ENRICH] ✅ Cascade complete. step5 total_qcms={total}")
    elif status == "no_qcms":
        print("[AUTO-ENRICH] Step 4+5 build skipped (no accepted metadata).")
    else:
        print(f"[AUTO-ENRICH] Step 4+5 build reported status={status}")

    return {"status": status, "step3": step3_status, "build": build}