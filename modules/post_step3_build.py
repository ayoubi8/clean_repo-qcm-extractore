"""Post-Step-3 Auto-Build — merges old Step 4 (Format/Template) + Step 5 (JSON Build).

Single invisible backend operation fired right after Step 3 succeeds.
Uses the Template.xlsx default schema (all fields included), so the output
matches what a user would get today if they selected "all Fields to Include".
"""
import json
from pathlib import Path
from typing import Any, Dict

from modules.utils.template_library import TemplateLibrary
from modules.step4_format import Step4Format
from modules.step5_builder import Step5Builder

# Default skeleton mirroring the columns of the repo's Template.xlsx file.
# Includes ALL fields (= "all Fields to Include" preset from the old Step 4 UI).
DEFAULT_TEMPLATE_XLSX: Dict[str, Any] = {
    "Num": 0,
    "Cas": None,
    "Text": "Question text here...",
    "A": "Option A",
    "B": "Option B",
    "C": "Option C",
    "D": "Option D",
    "E": "Option E",
    "Correct": "ABC",
    "Exp": "",
    "categoryName": "Cardiologie",
    "tagSuggere": "Semiologie",
    "subcategoryName": "HTA",
    "Year": 2024,
    "Tag": ["Externat", "2024"],
    "Type": "QCS",
}

DEFAULT_TEMPLATE_NAME = "Default-Template-xlsx"


def _has_accepted_qcms(context) -> bool:
    """Return True if Step 3 produced at least one accepted QCM JSON file."""
    try:
        accepted_dir = context.get_path("step3_metadata", "accepted")
    except Exception:
        return False
    if not Path(accepted_dir).exists():
        return False
    return any(Path(accepted_dir).glob("*.json"))


def run_post_step3_build(tracker, context, output_user_id: str = None,
                         output_project: str = None) -> Dict:
    """Build the template (old Step 4) then run the merger (old Step 5).

    Idempotent: re-running overwrites the same Default-Template-xlsx
    and the same current_template.json, then produces a fresh merged_qcms.json.

    Returns a dict:
        {"status": "ok", "step4": {...}, "step5": {...}}
        {"status": "no_qcms"}  # Step 3 produced nothing; do not fail Step 3.
    """
    print("\n" + "=" * 60)
    print("POST-STEP-3 AUTO-BUILD  (Step 4 + Step 5 merged)")
    print("=" * 60)

    # 1. Guard: nothing to do if Step 3 produced no accepted QCMs.
    if not _has_accepted_qcms(context):
        print("[AUTO-BUILD] No accepted QCMs found after Step 3 — skipping.")
        return {"status": "no_qcms"}

    # 2. Register the default Template.xlsx skeleton and select it as current.
    library = TemplateLibrary()
    library.save_template(DEFAULT_TEMPLATE_NAME, DEFAULT_TEMPLATE_XLSX)
    print(f"[AUTO-BUILD] Template '{DEFAULT_TEMPLATE_NAME}' saved with keys: "
          f"{list(DEFAULT_TEMPLATE_XLSX.keys())}")

    # Step4Format.run(auto_template=...) loads the named template and writes
    # it to {step4_format}/current_template.json — exactly what Step 5 reads.
    s4_result = Step4Format(tracker, context).run(auto_template=DEFAULT_TEMPLATE_NAME)
    if not s4_result:
        print("[AUTO-BUILD] Step 4 sub-step failed — aborting auto-build.")
        return {"status": "error", "stage": "step4"}

    # 3. Run the merger (old Step 5). It reads current_template.json + the
    # accepted QCMs and writes step5_json/merged_qcms.json + a timestamped xlsx.
    s5_result = Step5Builder(tracker, context).run()
    if not s5_result:
        print("[AUTO-BUILD] Step 5 sub-step failed — merged_qcms.json not produced.")
        return {"status": "error", "stage": "step5"}

    total = s5_result.get("total_qcms", 0)
    print(f"[AUTO-BUILD] ✅ Auto-build done: {total} QCMs merged.")
    return {
        "status": "ok",
        "step4": {"template": DEFAULT_TEMPLATE_XLSX, "name": DEFAULT_TEMPLATE_NAME},
        "step5": s5_result,
    }