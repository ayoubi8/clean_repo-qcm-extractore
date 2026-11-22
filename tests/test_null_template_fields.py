"""Regression: since the exam-papers template fix (f9a8a8e) Step 4/5 writes
every template column, None when empty ("Correct": null before Step 6).
Step 6 crashed with "'NoneType' object has no attribute 'strip'" on every PDF
(Auto Run 2026-11-22); Step 7 would crash the same way on tagSuggere: null."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules.post_step3_build import DEFAULT_TEMPLATE_XLSX  # noqa: E402
from modules.step5_builder import Step5Builder  # noqa: E402
from modules.utils.cost_tracker import CostTracker  # noqa: E402


def _step5_qcms():
    b = Step5Builder(CostTracker())
    return [b._map_to_template({"number": n, "text": f"Question {n}?", "propositions": {"A": "a", "B": "b"}},
                               dict(DEFAULT_TEMPLATE_XLSX)) for n in (1, 2)]


def test_step5_output_really_has_null_correct():
    q = _step5_qcms()[0]
    assert "Correct" in q and q["Correct"] is None
    assert q.get("tagSuggere") is None


def test_step6_runs_on_null_correct(tmp_path, monkeypatch):
    from modules.step6_corrections import Step6Corrections
    from modules.utils.project_context import ProjectContext
    monkeypatch.chdir(tmp_path)
    ctx = ProjectContext("u1/p")
    if ctx.base_path.is_absolute():          # /app exists → not this machine's layout
        ctx.base_path = tmp_path / "output" / "u1" / "p"
    (ctx.get_path("step5_json") / "merged_qcms.json").write_text(json.dumps(_step5_qcms()), encoding="utf-8")

    step = Step6Corrections(CostTracker(), ctx)
    # Correction source with nothing to find: the run must get past the
    # status count (where it crashed) and finish without raising.
    # (no correction page exists: the real code finds nothing)
    step.run(pdf_path="", auto_mode=True,
             config={"source": "page_text", "correction_search_mode": "specific_pages", "pages": "1",
                     "force_overwrite": False})
    out = ctx.get_path("step6_corrections")
    assert (out / "corrected_qcms.json").exists()


def test_step6_coverage_split_on_null_correct():
    from modules.step6_corrections import Step6Corrections
    step = Step6Corrections(CostTracker(), None)
    qs = [{"Num": 1, "Correct": None}, {"Num": 2, "Correct": "AB"}, {"Num": 3}]
    fn = next(getattr(step, n) for n in dir(step)
              if callable(getattr(step, n)) and getattr(getattr(step, n), "__doc__", "")
              and "Returns (corrected: List[Dict], uncorrected: List[Dict])" in getattr(step, n).__doc__)
    corrected, uncorrected = fn(qs)
    assert [q["Num"] for q in corrected] == [2] and [q["Num"] for q in uncorrected] == [1, 3]


def test_step7_domain_on_null_tag():
    from modules.step7_categorization import Step7Categorization
    s = Step7Categorization.__new__(Step7Categorization)
    assert s._normalize_domain(None) == "medecine"
    assert s._normalize_domain("Biologie") == "biologie"
