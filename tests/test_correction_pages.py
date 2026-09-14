"""Correction-page detection tests (Step 2 → Step 6 passthrough).

A correction page contains ONLY answer markings (answer key / annexe) and no
QCMs. Step 2 must return {"page": X, "correction_page": true} marker objects
for such pages, route them INTO correction_pages.json, and never count them
as extraction failures (no retry escalation / no fail streak).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.step2_qcm_extract_batch import Step2QCMExtractBatch  # noqa: E402


def _mk(project_context=None):
    from types import SimpleNamespace
    tracker = SimpleNamespace(log_api_call=lambda *a, **k: None)
    return Step2QCMExtractBatch(cost_tracker=tracker, project_context=project_context)


def test_is_correction_marker():
    assert Step2QCMExtractBatch.is_correction_marker({"page": 7, "correction_page": True})
    # Row with actual question content is NOT a marker (safety rail)
    assert not Step2QCMExtractBatch.is_correction_marker({
        "page": 7, "correction_page": True, "text": "Question?", "propositions": {}
    })
    assert not Step2QCMExtractBatch.is_correction_marker({
        "page": 7, "correction_page": True, "Text": "Question?"
    })
    # Normal QCM / non-dict input
    assert not Step2QCMExtractBatch.is_correction_marker({"page": 7, "number": 2})
    assert not Step2QCMExtractBatch.is_correction_marker("x")
    assert not Step2QCMExtractBatch.is_correction_marker(None)


def test_split_markers_drops_out_of_range_and_dedups():
    ex = _mk()
    rows = [
        {"page": 7, "correction_page": True},
        {"page": 7, "correction_page": True},      # duplicate
        {"page": 99, "correction_page": True},     # outside range → dropped
        {"page": 1, "number": 2, "text": "Q", "propositions": {"a": "x"}},
        {"page": 7, "correction_page": True, "text": "Q?"},  # mixed → normal row
    ]
    markers, rest = ex._split_correction_markers(rows, 5, 10)
    assert markers == [7]
    assert len(rest) == 2


def test_save_correction_pages_merges(tmp_path):
    ex = _mk()

    class FakeCtx:
        def get_path(self, folder, sub=None):
            p = tmp_path / folder
            if sub:
                p = p / sub
            p.mkdir(parents=True, exist_ok=True)
            return p

    ex.context = FakeCtx()
    ex._save_correction_pages([7, 9])
    path = ex._correction_pages_path()
    assert json.loads(path.read_text(encoding="utf-8")) == {"correction_pages": [7, 9]}
    ex._save_correction_pages([8, 7])   # merge, no dupes
    assert json.loads(path.read_text(encoding="utf-8")) == {"correction_pages": [7, 8, 9]}


def test_correction_only_response_short_circuits_retries(tmp_path, monkeypatch):
    """A correction-only LLM response must NOT trigger the 3-attempt
    escalation nor the fail-streak increment."""
    ex = _mk()
    ex.context = type("C", (), {})()

    def get_path(self, folder, sub=None):
        return tmp_path / folder

    monkeypatch.setattr(type(ex.context), "get_path", get_path, raising=False)

    ex._step2_primary_fail_streak = 1   # pretend primary failed twice already
    ex._step2_promoted_to_fallback = True

    calls = {"n": 0}

    def fake_generate(prompt, images=None, max_tokens=4000, model=None, temperature=0.1):
        calls["n"] += 1
        return {"content": json.dumps([{"page": 8, "correction_page": True}]),
                "usage": {}, "cost": 0.0}

    ex.client = type("C", (), {
        "generate_completion": staticmethod(fake_generate),
        "estimate_cost": staticmethod(lambda m, u: 0.0),
    })()

    result = ex._extract_all_qcms_batch("TEXT", 8, 8, {})
    assert calls["n"] == 1                      # no retry escalation
    assert result == []                         # no QCMs, not an error
    assert ex._step2_primary_fail_streak == 1   # unchanged (no false increment)
    sidecar = ex._correction_pages_path()
    assert json.loads(sidecar.read_text(encoding="utf-8")) == {"correction_pages": [8]}
