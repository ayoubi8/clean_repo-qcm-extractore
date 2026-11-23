"""Regression: since the exam-papers template fix (f9a8a8e) Step 4/5 writes
every template column, None when empty ("Correct": null before Step 6).
Step 6 crashed with "'NoneType' object has no attribute 'strip'" on every PDF
(Auto Run 2026-11-22); Step 7 would crash the same way on tagSuggere: null."""
import json
import sys
from pathlib import Path

import pytest

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
    ctx.base_path = tmp_path / "output" / "u1" / "p"   # never the shared /app output
    (ctx.get_path("step5_json") / "merged_qcms.json").write_text(json.dumps(_step5_qcms()), encoding="utf-8")

    (ctx.get_path("step1_extraction", "accepted") / "page_1.txt").write_text("Texte sans corrigé.", encoding="utf-8")

    step = Step6Corrections(CostTracker(), ctx)
    monkeypatch.setattr(step, "_extract_single_page_corrections", lambda *a, **k: {})
    # Correction source with nothing to find: the run must get past the status
    # count (where it crashed), keep its output, and report the failure.
    with pytest.raises(RuntimeError, match="No corrections found"):
        step.run(pdf_path="", auto_mode=True,
                 config={"source": "page_text", "correction_search_mode": "specific_pages", "pages": "1",
                         "force_overwrite": False})
    out = ctx.get_path("step6_corrections")
    assert (out / "corrected_qcms.json").exists()


def test_step6_fails_clearly_when_step1_pages_are_missing(tmp_path, monkeypatch):
    from modules.step6_corrections import Step6Corrections
    from modules.utils.project_context import ProjectContext
    monkeypatch.chdir(tmp_path)
    ctx = ProjectContext("u1/p")
    ctx.base_path = tmp_path / "output" / "u1" / "p"   # never the shared /app output
    (ctx.get_path("step5_json") / "merged_qcms.json").write_text(json.dumps(_step5_qcms()), encoding="utf-8")
    with pytest.raises(RuntimeError, match="Step 1 page text is missing"):
        Step6Corrections(CostTracker(), ctx).run(
            pdf_path="", auto_mode=True,
            config={"source": "page_text", "correction_search_mode": "specific_pages", "pages": "1"})
    assert not (ctx.get_path("step6_corrections") / "corrected_qcms.json").exists()


def test_step6_scans_likely_pages_and_stops_when_all_answered(tmp_path, monkeypatch):
    from modules.step6_corrections import Step6Corrections
    from modules.utils.project_context import ProjectContext
    monkeypatch.chdir(tmp_path)
    ctx = ProjectContext("u1/p")
    ctx.base_path = tmp_path / "output" / "u1" / "p"   # never the shared /app output
    pages = ctx.get_path("step1_extraction", "accepted")
    for n in range(1, 7):
        (pages / f"page_{n}.txt").write_text("KEY" if n == 6 else "question", encoding="utf-8")

    step = Step6Corrections(CostTracker(), ctx)
    seen = []
    monkeypatch.setattr(step, "_score_correction_page", lambda t: 50 if t == "KEY" else 0)

    def det(text, pn, deterministic_only=False):
        seen.append(pn)
        return {"1": "A", "2": "B"} if text == "KEY" else {}
    monkeypatch.setattr(step, "_extract_single_page_corrections", det)
    monkeypatch.setattr(step.openrouter, "generate_completion",
                        lambda *a, **k: {"content": "{}", "usage": {}, "cost": 0.0})
    qcms = [{"Num": 1, "Text": "q1"}, {"Num": 2, "Text": "q2"}]
    out = step._scan_all_pages_per_page_ai(qcms, {})
    assert seen == [5, 6], seen               # the key page + its neighbour only
    assert [q["Correct"] for q in out] == ["A", "B"]


@pytest.mark.parametrize("value,expected", [
    (None, False), ("", False), ("  ", False), ("None", False), ("null", False), ("AB", True), ("e", True)])
def test_has_answer(value, expected):
    from modules.utils.qcm_merge import has_answer
    assert has_answer(value) is expected


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
