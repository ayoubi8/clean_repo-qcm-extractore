"""Tests for the Step 2 fallback promotion streak
(modules/step2_qcm_extract_batch.py).

One flaky chunk must NOT pin the fallback for the rest of the run. Each
_extract_all_qcms_batch call (one chunk) starts on primary unless the
primary failed 2+ consecutive chunks; any primary success resets the streak.
"""
import os
import sys
import json
from unittest.mock import patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')

from modules.step2_qcm_extract_batch import Step2QCMExtractBatch
from modules.utils.cost_tracker import CostTracker

PRIMARY = "primary-model"
FALLBACK = "fallback-model"
_QCM_JSON = json.dumps([{"page": 2, "number": 7, "text": "Q7?",
                         "propositions": {"a": "1", "b": "2", "c": "3",
                                          "d": "4", "e": "5"}}])
_CONFIG = {"qcm_extraction": {"clinical_case_hints": False}}


class _ScriptedClient:
    """Fake OpenRouterClient: strict script of (model, outcome) per call.
    Any unexpected extra call fails the test."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def generate_completion(self, prompt, model=None, max_tokens=None, **kw):
        self.calls.append(model)
        assert self.script, \
            f"unexpected extra LLM call #{len(self.calls)} (model={model})"
        exp_model, outcome = self.script.pop(0)
        assert model == exp_model, \
            f"call #{len(self.calls)}: expected {exp_model}, got {model}"
        if outcome == "raise":
            raise RuntimeError("primary down")
        return {"content": _QCM_JSON, "usage": {}, "cost": 0.0}

    @staticmethod
    def estimate_cost(model, usage):
        return 0.0


def _make_batch(script):
    batch = Step2QCMExtractBatch(CostTracker())
    batch.client = _ScriptedClient(script)
    batch._step2_primary_fail_streak = 0
    return batch


def _chunk(batch, **kw):
    with patch.dict(os.environ, {"STEP2_MODEL": PRIMARY,
                                 "STEP2_FALLBACK_MODEL": FALLBACK,
                                 "STEP2_MAX_RETRIES": "1"}):
        return batch._extract_all_qcms_batch("PAGES", 2, 2, dict(_CONFIG, **kw))


def _test_single_bad_chunk_does_not_stick():
    print("\n--- Test 1: one bad chunk -> next chunk starts on primary ---")
    batch = _make_batch([("primary-model", "raise"),
                         ("fallback-model", "ok"),
                         ("primary-model", "ok")])
    r1 = _chunk(batch)
    assert len(r1) == 1 and r1[0]["number"] == 7
    assert batch._step2_primary_fail_streak == 1, batch._step2_primary_fail_streak
    r2 = _chunk(batch)
    assert len(r2) == 1
    assert batch._step2_primary_fail_streak == 0, "primary success resets streak"
    assert batch.client.calls == ["primary-model", "fallback-model",
                                  "primary-model"], batch.client.calls
    print("✅ chunk 2 retried primary first; streak reset on success.")


def _test_two_consecutive_failures_promote():
    print("\n--- Test 2: two consecutive primary failures -> chunk 3 starts on fallback ---")
    batch = _make_batch([("primary-model", "raise"),
                         ("fallback-model", "ok"),
                         ("primary-model", "raise"),
                         ("fallback-model", "ok"),
                         ("fallback-model", "ok")])
    _chunk(batch)
    assert batch._step2_primary_fail_streak == 1
    _chunk(batch)
    assert batch._step2_primary_fail_streak == 2, batch._step2_primary_fail_streak
    r3 = _chunk(batch)
    assert len(r3) == 1
    assert batch.client.calls[-1] == "fallback-model", batch.client.calls
    print("✅ promoted after 2 consecutive failures; chunk 3 opened on fallback.")


def _test_non_consecutive_never_promotes():
    print("\n--- Test 3: fail, ok, fail -> chunk 4 still starts on primary ---")
    batch = _make_batch([("primary-model", "raise"),
                         ("fallback-model", "ok"),
                         ("primary-model", "ok"),
                         ("primary-model", "raise"),
                         ("fallback-model", "ok"),
                         ("primary-model", "ok")])
    _chunk(batch)   # streak 1
    _chunk(batch)   # primary ok -> streak 0
    assert batch._step2_primary_fail_streak == 0
    _chunk(batch)   # streak 1 again
    assert batch._step2_primary_fail_streak == 1
    _chunk(batch)   # must open on primary, not fallback
    assert batch.client.calls[-1] == "primary-model", batch.client.calls
    print("✅ non-consecutive failures never promote.")


def _run_all():
    _test_single_bad_chunk_does_not_stick()
    _test_two_consecutive_failures_promote()
    _test_non_consecutive_never_promotes()

    print("\n" + "=" * 60)
    print("ALL step2_promotion_streak TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()
