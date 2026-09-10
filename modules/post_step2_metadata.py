"""Post-Step-2 Auto-Enrich + Build.

Merges the old Step 3 (metadata detection) + the already-shipped Step 4/5
auto-build (`modules/post_step3_build.py`) into a single invisible backend
operation fired right after Step 2 succeeds.

After the Step 2+3 frontend merge, "Step 2" is the only visible extract+enrich
step. This module runs Step 3 (metadata) then chains the Step 4+5 build, so
the whole extraction → enrichment → build pipeline fires as one cascade
inside the Step 2 background task.

Idempotent / fast-path (Q8): Step 3 is skipped ONLY when accepted metadata
already exists AND it covers the same uid-set as the current Step 2
`all_qcms.json`. If Step 2 has grown (e.g. a re-run added new QCMs), Step 3
re-runs so the new QCMs get enriched. To force full re-enrichment, delete the
`step3_metadata/accepted/` folder before re-running Step 2.
"""
import json
from pathlib import Path
from typing import Any, Dict, Optional

from modules.step3_metadata import Step3Metadata
from modules.post_step3_build import run_post_step3_build
from modules.clinical_case_checker import run_clinical_case_checker
from modules.hint_detector import run_hint_detection
from modules.cas_text_split import run_cas_text_split


# Default Step 3 config used when the /steps/2/run caller does not send one.
# Mirrors the frontend `step3Config` default in
# frontend/src/store/pipelineStore.ts:64-75 so the cascade behaves like the
# old manual /steps/3/run with the default store config.
DEFAULT_STEP3_CONFIG: Dict[str, Any] = {
    "fields": {
        "year":          {"strategy": "per_qcm",  "value": None},
        "source":        {"strategy": "skip",      "value": "Externat"},
        "category":      {"strategy": "global",    "value": None},
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


def _step2_uid_set(context) -> set:
    """Return the set of uids in the current Step 2 all_qcms.json (empty if missing)."""
    try:
        s2_file = Path(context.get_path("step2_qcm", "accepted")) / "all_qcms.json"
    except Exception:
        return set()
    if not s2_file.exists():
        return set()
    try:
        with open(s2_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {q.get("uid") for q in data if q.get("uid") is not None}
    except Exception:
        return set()


def _step3_uid_set(context) -> set:
    """Return the union of uids across all step3_metadata/accepted/*.json
    files (excluding merged_* files mirrored back by the auto-build)."""
    try:
        d = Path(context.get_path("step3_metadata", "accepted"))
    except Exception:
        return set()
    if not d.exists():
        return set()
    uids: set = set()
    for q_file in d.glob("*.json"):
        if q_file.name.startswith("merged_"):
            continue
        try:
            with open(q_file, "r", encoding="utf-8") as f:
                for q in json.load(f):
                    if q.get("uid") is not None:
                        uids.add(q.get("uid"))
        except Exception:
            continue
    return uids


def _step3_covers_current_step2(context) -> bool:
    """Q8 fast-path guard: True only when Step 3 already produced accepted
    metadata AND that metadata covers every uid currently in Step 2's
    all_qcms.json (and vice-versa). If the sets differ (Step 2 grew, or Step 3
    was for a different extraction), Step 3 must re-run.
    """
    try:
        d = Path(context.get_path("step3_metadata", "accepted"))
    except Exception:
        return False
    if not d.exists() or not any(d.glob("*.json")):
        return False
    s2_uids = _step2_uid_set(context)
    s3_uids = _step3_uid_set(context)
    if not s2_uids:
        return False
    return s2_uids == s3_uids


def _clinical_case_enabled(step3_config: Optional[Dict]) -> bool:
    """True when the clinical-case cascade ("per_group") is toggled on.

    Accepts both config shapes that reach this cascade:
      - UI shape:        {"fields": {"clinical_case": {"strategy": "per_group"}}}
      - Autorun shape:   {"config": {"ClinicalCase": "CC"}}
    A missing/None config falls back to the DEFAULT_STEP3_CONFIG (per_group).
    """
    cfg = step3_config or DEFAULT_STEP3_CONFIG
    try:
        cc = (cfg.get("fields", {}) or {}).get("clinical_case")
        if isinstance(cc, dict) and cc.get("strategy"):
            return cc.get("strategy") == "per_group"
        code = (cfg.get("config", {}) or {}).get("ClinicalCase")
        if code:
            return code == "CC"
        return True  # no explicit setting → default (DEFAULT_STEP3_CONFIG = per_group)
    except Exception:
        return True


def run_post_step2_metadata(tracker, context, user_id: str, project: str,
                            step3_config: Optional[Dict] = None) -> Dict:
    """Run Step 3 (metadata) then chain the Step 4+5 auto-build.

    Must be called from a background thread (it runs LLM calls). The caller
    owns `job_manager.set_done` bookkeeping for steps 3/4/5 — this function
    only performs the work and reports the result.

    Returns:
        {"status": "ok",        "step3": "done|skipped", "hint": {...}, "cas_split": {...}, "cc_check": {...}, "build": {...}}
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

    # 1.5 Phase 3 — Hint detection (always-on, no toggle, no strategy gate):
    #     parse trailing A(1+2)-style hint blocks out of Step 2 propositions
    #     into `hint` arrays and scrub the raw lines — BEFORE Step 3, the
    #     Phase-1 checker, and the Step 4/5 build, so every downstream stage
    #     sees clean propositions. Pure Python (no LLM). Soft-fail: a hint
    #     error never blocks the cascade.
    hint_result: Dict = {"status": "not_run"}
    try:
        hint_result = run_hint_detection(context)
    except Exception as e:
        import traceback
        traceback.print_exc()
        hint_result = {"status": "error", "detail": str(e)}
        print(f"[HINT] ⚠️ ERROR: Hint detection failed: {e} — continuing without hints.")

    # 1.6 Phase 4 — Cas column split: remove the clinical-case narrative from
    #     question text (it stays in `cas`/Cas only — never merged into Text).
    #     Unconditional (keyed on data presence: QCMs without `cas` are
    #     skipped), idempotent, soft-fail: never blocks the cascade.
    cas_split_result: Dict = {"status": "not_run"}
    try:
        cas_split_result = run_cas_text_split(context)
    except Exception as e:
        import traceback
        traceback.print_exc()
        cas_split_result = {"status": "error", "detail": str(e)}
        print(f"[CAS-SPLIT] ⚠️ ERROR: Cas split failed: {e} — continuing with unscrubbed text.")

    # 2. Step 3 (metadata) — skip only if Step 3 already enriched the SAME
    #    uid-set as the current all_qcms.json (Q8 fast-path). If Step 2 grew
    #    (e.g. re-run added new QCMs), Step 3 re-runs so the new QCMs get
    #    enriched — otherwise they'd silently bypass metadata and the merge.
    if _step3_covers_current_step2(context):
        print("[AUTO-ENRICH] Step 3 accepted metadata already covers the current "
              "Step 2 QCM set — skipping Step 3 (Q8 fast-path). To force "
              "re-enrichment, delete step3_metadata/accepted/ before re-running "
              "Step 2.")
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
            return {"status": "error", "stage": "step3", "detail": str(e),
                    "hint": hint_result, "cas_split": cas_split_result}

    # 2.5 Phase 1 — Clinical Case Checker: verify every cascaded Cas Clinique
    #     link with a cheap/fast model, one question per QCM, BEFORE the
    #     Step 4/5 build consumes the `cas` fields. Runs only when the
    #     clinical_case strategy is "per_group" (the togglable cascade).
    #     Soft-fail: a checker error never blocks the build — the unverified
    #     cascade data is kept and the [CC-CHECK] ⚠️ ERROR marker line below
    #     raises a persistent alert in the frontend (dismissed only by click).
    cc_check: Dict = {"status": "not_enabled"}
    if _clinical_case_enabled(step3_config):
        print("[AUTO-ENRICH] Clinical Case Checker (per_group) — verification pass...")
        try:
            cc_check = run_clinical_case_checker(tracker, context)
        except Exception as e:
            import traceback
            traceback.print_exc()
            cc_check = {"status": "error", "detail": str(e)}
            print(f"[CC-CHECK] ⚠️ ERROR: Clinical Case Checker failed: {e} — case links "
                  "were NOT verified. The build continues with unverified data. Fix the "
                  "CC Checker model (Settings) and re-run Step 2.")

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

        # Surface the final merged artifacts into step2_qcm/accepted/ so the
        # Step 2 OutputViewer (which lists step2_qcm/ files) shows the xlsx +
        # merged JSON alongside the raw extraction output. Without this, the
        # user sees extraction results but not the metadata-enriched final
        # output (merged_qcms.xlsx) because the OutputViewer endpoint maps
        # step "2" → step2_qcm/ only.
        try:
            import shutil
            step2_accepted = context.get_path("step2_qcm", "accepted")
            step5_dir = context.get_path("step5_json")
            merged_src = Path(step5_dir) / "merged_qcms.json"
            merged_dst = Path(step2_accepted) / "merged_qcms.json"
            if merged_src.exists():
                shutil.copy2(merged_src, merged_dst)
                print(f"[AUTO-ENRICH] ✅ Copied merged_qcms.json → step2_qcm/accepted/")
            xlsx_src_str = build.get("step5", {}).get("xlsx_file", "")
            if xlsx_src_str and Path(xlsx_src_str).exists():
                xlsx_dst = Path(step2_accepted) / Path(xlsx_src_str).name
                shutil.copy2(xlsx_src_str, xlsx_dst)
                print(f"[AUTO-ENRICH] ✅ Copied {xlsx_dst.name} → step2_qcm/accepted/")
        except Exception as copy_e:
            print(f"[AUTO-ENRICH] ⚠️ Failed to surface merged result into step2 output: {copy_e}")
    elif status == "no_qcms":
        print("[AUTO-ENRICH] Step 4+5 build skipped (no accepted metadata).")
    else:
        print(f"[AUTO-ENRICH] Step 4+5 build reported status={status}")

    return {"status": status, "step3": step3_status, "hint": hint_result,
            "cas_split": cas_split_result, "cc_check": cc_check, "build": build}
