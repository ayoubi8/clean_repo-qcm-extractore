import os
import sys
import json
from pathlib import Path

# Force UTF-8 execution for Windows
sys.stdout.reconfigure(encoding='utf-8')

# Make the project root importable so `from modules.*` works from any cwd.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()

from modules.utils.project_context import ProjectContext
from modules.utils.cost_tracker import CostTracker
from modules.post_step3_build import (
    run_post_step3_build,
    DEFAULT_TEMPLATE_XLSX,
    DEFAULT_TEMPLATE_NAME,
)


def _seed_accepted_qcms(context, qcms):
    """Write the given list of qcm dicts to step3_metadata/accepted/qcms_1.json."""
    accepted = context.get_path("step3_metadata", "accepted")
    accepted.mkdir(parents=True, exist_ok=True)
    with open(accepted / "qcms_1.json", "w", encoding="utf-8") as f:
        json.dump(qcms, f, ensure_ascii=False)


def test_no_qcms_returns_no_qcms_status():
    """When Step 3 produced no accepted QCMs, the auto-build must NOT crash Step 3."""
    ctx = ProjectContext("test-post-step3-empty")
    tracker = CostTracker()
    # Ensure the accepted dir is empty / missing
    accepted = ctx.get_path("step3_metadata", "accepted")
    if accepted.exists():
        for p in accepted.glob("*.json"):
            p.unlink()

    res = run_post_step3_build(tracker, ctx)
    assert res.get("status") == "no_qcms", f"Expected no_qcms, got: {res}"
    print("✅ no_qcms guard works as expected.")


def test_auto_build_produces_merged_qcms_with_template_xlsx_schema():
    """Happy path: produces merged_qcms.json containing all Template.xlsx keys."""
    ctx = ProjectContext("test-post-step3-happy")
    tracker = CostTracker()

    qcms_in = [
        {
            "number": 1,
            "text": "Sample question?",
            "propositions": {"A": "alpha", "B": "beta", "C": "gamma", "D": "delta", "E": "epsilon"},
            "correction": "AB",
            "module": "Cardiologie",
            "year": 2024,
            "source": "Externat",
            "tag": ["Externat", "2024"],
            "cas": "Cas clinique 1 ...",
            "module_detected": "Cardiologie",
            "domain": "Semiologie",
        },
        {
            "number": 2,
            "text": "Second question?",
            "propositions": {"A": "a2", "B": "b2", "C": "c2"},
            "correction": "C",
            "module": "Neuro",
        },
    ]
    _seed_accepted_qcms(ctx, qcms_in)

    res = run_post_step3_build(tracker, ctx)
    assert res.get("status") == "ok", f"Expected ok, got: {res}"
    assert res["step5"]["total_qcms"] == 2, res

    # Verify merged_qcms.json exists
    merged = ctx.get_path("step5_json", "merged_qcms.json")
    assert merged.exists(), f"Missing merged_qcms.json at {merged}"
    with open(merged, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 2

    # Verify the skeleton used matches Template.xlsx (all fields)
    saved_tmpl_path = ctx.get_path("step4_format", "current_template.json")
    assert saved_tmpl_path.exists(), f"Missing current_template.json at {saved_tmpl_path}"
    with open(saved_tmpl_path, "r", encoding="utf-8") as f:
        saved_tmpl = json.load(f)
    expected_keys = set(DEFAULT_TEMPLATE_XLSX.keys())
    assert set(saved_tmpl.keys()) == expected_keys, f"Template keys mismatch: {set(saved_tmpl.keys())} != {expected_keys}"
    # Critical: the extra Template.xlsx-only keys must be present
    for must_have in ("Exp", "tagSuggere", "Type"):
        assert must_have in saved_tmpl, f"Missing Template.xlsx key: {must_have}"

    # Verify the default name was registered in template library
    lib_tmpl_path = Path("output/step4_format/templates") / f"{DEFAULT_TEMPLATE_NAME}.json"
    assert lib_tmpl_path.exists(), f"Default template not registered at {lib_tmpl_path}"

    print(f"✅ Auto-build produced {len(data)} QCMs with full Template.xlsx schema.")


def test_idempotent_on_rerun():
    """Re-running overwrites the same template file and produces a fresh merged output."""
    ctx = ProjectContext("test-post-step3-idem")
    tracker = CostTracker()
    _seed_accepted_qcms(ctx, [{"number": 1, "text": "Q1"}])

    r1 = run_post_step3_build(tracker, ctx)
    assert r1.get("status") == "ok"
    r2 = run_post_step3_build(tracker, ctx)
    assert r2.get("status") == "ok"

    # Template name must be stable
    assert r1["step4"]["name"] == r2["step4"]["name"] == DEFAULT_TEMPLATE_NAME

    # merged_qcms.json should still exist and have 1 item
    merged = ctx.get_path("step5_json", "merged_qcms.json")
    assert merged.exists()
    with open(merged, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 1

    print("✅ Idempotent re-run verified.")


def main():
    test_no_qcms_returns_no_qcms_status()
    test_auto_build_produces_merged_qcms_with_template_xlsx_schema()
    test_idempotent_on_rerun()
    print("\nAll post_step3_build tests passed.")


if __name__ == "__main__":
    main()