"""Tests for Step 2 chunk retry logic (PR — STEP2_MAX_RETRIES).

Covers the contract added to _extract_all_qcms_batch:
- Empty qcms after parse triggers a retry (up to STEP2_MAX_RETRIES, default 3)
- max_tokens escalates on each retry (base * attempt, clamped to ceiling)
- Returns QCMs as soon as a successful attempt happens
- Returns [] only after all retries are exhausted
- API hard failure mid-retry chain is handled
"""
import os
import sys
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))


class FakeTracker:
    def log_api_call(self, *a, **k):
        pass


class FakeContext:
    def __init__(self, base: Path):
        self.base_path = base
        self.name = "testproj"

    def get_path(self, step: str, sub: str = "") -> Path:
        p = self.base_path / step
        if sub:
            p = p / sub
        p.mkdir(parents=True, exist_ok=True)
        return p


def _make_step2(base: Path):
    from modules.step2_qcm_extract_batch import Step2QCMExtractBatch
    st = Step2QCMExtractBatch.__new__(Step2QCMExtractBatch)
    st.context = FakeContext(base)
    st.cost_tracker = FakeTracker()
    st.client = MagicMock()
    st.client.estimate_cost.return_value = 0.0
    return st


def _test_retries_on_empty_and_recovers():
    """1. First attempt yields empty, 2nd yields recoverable QCMs.
       Token budget must escalate: base*1, base*2."""
    print("\n--- Test 1: recovers on 2nd retry with token escalation ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        st = _make_step2(tmp)
        old = os.environ.get("STEP2_MAX_TOKENS")
        os.environ["STEP2_MAX_TOKENS"] = "1000"
        calls = []
        def fake_generate(prompt, model=None, max_tokens=None):
            calls.append(max_tokens)
            if len(calls) == 1:
                # Truly unsalvageable — not even one complete object
                return {"content": "```json\n[", "usage": {}, "cost": 0}
            return {
                "content": '```json\n[{"page":5,"number":23,"text":"Q23","propositions":{"a":"x"}}]',
                "usage": {},
                "cost": 0,
            }
        st.client.generate_completion.side_effect = fake_generate

        qcms = st._extract_all_qcms_batch("TEXT", 5, 5, config={})
        assert len(qcms) == 1, qcms
        assert calls == [1000, 2000], f"token escalation failed: {calls}"
        print(f"✅ recovered on 2nd attempt, tokens escalated: {calls}")
        if old is None:
            del os.environ["STEP2_MAX_TOKENS"]
        else:
            os.environ["STEP2_MAX_TOKENS"] = old
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_retry_limited_to_env():
    """2. STEP2_MAX_RETRIES=1 → exactly one API call, no escalation."""
    print("\n--- Test 2: STEP2_MAX_RETRIES=1 → single attempt ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        st = _make_step2(tmp)
        old_retries = os.environ.get("STEP2_MAX_RETRIES")
        os.environ["STEP2_MAX_RETRIES"] = "1"
        calls = []
        st.client.generate_completion.side_effect = lambda prompt, model=None, max_tokens=None: (
            calls.append(max_tokens) or {"content": "not json at all", "usage": {}, "cost": 0}
        )
        qcms = st._extract_all_qcms_batch("TEXT", 5, 5, config={})
        assert qcms == [], qcms
        assert len(calls) == 1, f"expected 1 call, got {len(calls)}"
        print(f"✅ single attempt as configured: {calls}")
        if old_retries is None:
            del os.environ["STEP2_MAX_RETRIES"]
        else:
            os.environ["STEP2_MAX_RETRIES"] = old_retries
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_api_failure_then_recovery():
    """3. API call fails (both models) on attempt 1, succeeds on attempt 2."""
    print("\n--- Test 3: API hard failure then recovery ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        st = _make_step2(tmp)
        calls = []
        def fake_generate(prompt, model=None, max_tokens=None):
            calls.append((model, max_tokens))
            if len(calls) == 1:
                raise RuntimeError("network down")
            return {"content": '```json\n[{"page":5,"number":23,"text":"Q23"}]', "usage": {}, "cost": 0}
        st.client.generate_completion.side_effect = fake_generate

        qcms = st._extract_all_qcms_batch("TEXT", 5, 5, config={})
        assert len(qcms) == 1, qcms
        assert len(calls) >= 2, f"expected retry after API failure, calls={calls}"
        print(f"✅ recovered after API failure: {calls}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_all_attempts_fail_returns_empty():
    """4. All 3 attempts unparseable → returns [] after 3 calls."""
    print("\n--- Test 4: all attempts fail → [] ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        st = _make_step2(tmp)
        calls = []
        def fake_generate(prompt, model=None, max_tokens=None):
            calls.append(max_tokens)
            return {"content": "[broken", "usage": {}, "cost": 0}
        st.client.generate_completion.side_effect = fake_generate

        qcms = st._extract_all_qcms_batch("TEXT", 5, 5, config={})
        assert qcms == [], qcms
        assert len(calls) == 3, f"expected 3 calls, got {len(calls)}"
        print(f"✅ returned [] after 3 attempts: {calls}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_token_ceiling_clamped():
    """5. max_tokens never exceeds STEP2_MAX_TOKENS_CEILING."""
    print("\n--- Test 5: token ceiling clamp ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        st = _make_step2(tmp)
        os.environ["STEP2_MAX_TOKENS"] = "30000"
        os.environ["STEP2_MAX_TOKENS_CEILING"] = "50000"
        calls = []
        def fake_generate(prompt, model=None, max_tokens=None):
            calls.append(max_tokens)
            return {"content": "[broken", "usage": {}, "cost": 0}
        st.client.generate_completion.side_effect = fake_generate
        st._extract_all_qcms_batch("TEXT", 5, 5, config={})
        assert max(calls) <= 50000, f"ceiling exceeded: {calls}"
        assert calls == [30000, 50000, 50000], f"unexpected escalation: {calls}"
        print(f"✅ ceiling clamped correctly: {calls}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_all():
    _test_retries_on_empty_and_recovers()
    _test_retry_limited_to_env()
    _test_api_failure_then_recovery()
    _test_all_attempts_fail_returns_empty()
    _test_token_ceiling_clamped()
    print("\n" + "=" * 60)
    print("ALL Step 2 retry tests PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()