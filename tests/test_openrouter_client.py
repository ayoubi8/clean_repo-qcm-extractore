"""OpenRouter client: typed errors, single retry layer, Retry-After,
fatal-key circuit breaker, finish_reason, context pre-flight — and Step 2's
truncation guard. No network: httpx.MockTransport."""
import json
import os
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import modules.openrouter_client as orc  # noqa: E402
from modules.openrouter_client import (  # noqa: E402
    OpenRouterClient, OpenRouterAuthError, OpenRouterCreditsError,
    OpenRouterBadRequestError, OpenRouterContextTooLong, OpenRouterTransientError,
)


def _ok(content="[]", finish="stop"):
    return httpx.Response(200, json={
        "model": "m/answered",
        "choices": [{"message": {"content": content}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001},
    })


@pytest.fixture
def client(monkeypatch):
    """Client wired to a scripted transport; sleeps and telemetry stubbed."""
    calls = []
    script = []

    def handler(request):
        calls.append(json.loads(request.content) if request.content else None)
        item = script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(orc, "_sync_client", httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(orc.time, "sleep", lambda s: calls.append(("sleep", s)))
    monkeypatch.setattr(orc, "log_ai_call_start", lambda *a, **k: None)
    monkeypatch.setattr(orc, "log_ai_call_finish", lambda *a, **k: None)
    monkeypatch.setattr(orc, "_model_limits", lambda model: {})
    orc._fatal_keys.clear()
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-123456789")
    c = OpenRouterClient()
    c._script, c._calls = script, calls
    return c


def _http_calls(c):
    return [x for x in c._calls if not (isinstance(x, tuple) and x[0] == "sleep")]


def test_success_returns_finish_reason_and_model(client):
    client._script.append(_ok("[1]", "stop"))
    out = client.generate_completion("p", model="m/x")
    assert out["content"] == "[1]" and out["finish_reason"] == "stop"
    assert out["model"] == "m/answered" and out["cost"] == 0.001
    payload = _http_calls(client)[0]
    assert payload["usage"] == {"include": True}
    # Dynamic prompt is never marked cacheable (no system part given).
    assert "cache_control" not in payload["messages"][0]["content"][0]


def test_system_prompt_goes_first_and_is_the_only_cached_part(client):
    client._script.append(_ok())
    client.generate_completion("page text", model="m/x", system="static rules")
    msgs = _http_calls(client)[0]["messages"]
    assert msgs[0]["role"] == "system" and msgs[0]["content"][0]["cache_control"]
    assert msgs[1]["role"] == "user" and "cache_control" not in msgs[1]["content"][0]


def test_transient_errors_are_retried_then_succeed(client):
    client._script += [httpx.Response(503, json={"error": {"message": "overloaded"}}),
                       httpx.ReadTimeout("slow"), _ok("ok")]
    assert client.generate_completion("p", model="m/x")["content"] == "ok"
    assert len(_http_calls(client)) == 3


def test_retry_after_is_honoured_on_429(client):
    client._script += [httpx.Response(429, headers={"retry-after": "7"}, json={"error": {"message": "slow down"}}),
                       _ok("ok")]
    client.generate_completion("p", model="m/x")
    sleeps = [x[1] for x in client._calls if isinstance(x, tuple)]
    assert sleeps and sleeps[0] >= 7


@pytest.mark.parametrize("status,exc", [(400, OpenRouterBadRequestError), (404, OpenRouterBadRequestError),
                                        (401, OpenRouterAuthError), (402, OpenRouterCreditsError)])
def test_non_retryable_errors_raise_after_one_call(client, status, exc):
    client._script.append(httpx.Response(status, json={"error": {"message": "nope"}}))
    with pytest.raises(exc):
        client.generate_completion("p", model="m/x")
    assert len(_http_calls(client)) == 1


def test_context_length_400_is_typed(client):
    client._script.append(httpx.Response(400, json={"error": {"message": "This endpoint's maximum context length is 8192 tokens"}}))
    with pytest.raises(OpenRouterContextTooLong):
        client.generate_completion("p", model="m/x")


def test_fatal_key_circuit_breaker_skips_http(client):
    client._script.append(httpx.Response(402, json={"error": {"message": "Insufficient credits"}}))
    with pytest.raises(OpenRouterCreditsError):
        client.generate_completion("p", model="m/x")
    with pytest.raises(OpenRouterCreditsError):          # no script left: must not hit HTTP
        client.generate_completion("p2", model="m/y")
    assert len(_http_calls(client)) == 1


def test_error_inside_200_body_is_typed(client):
    client._script.append(httpx.Response(200, json={"error": {"code": 502, "message": "provider down"}}))
    client._script.append(_ok("ok"))
    assert client.generate_completion("p", model="m/x")["content"] == "ok"


def test_exhausted_transient_retries_raise_typed(client):
    client._script += [httpx.Response(500, text="x")] * 3
    with pytest.raises(OpenRouterTransientError):
        client.generate_completion("p", model="m/x")


def test_preflight_clamps_max_tokens_and_rejects_oversized(monkeypatch):
    monkeypatch.setattr(orc, "_model_limits", lambda m: {"context": 10_000, "max_output": 4_000})
    assert orc._preflight("m", "x" * 320, 0, 64_000) == 4_000           # output cap
    assert orc._preflight("m", "x" * 25_000, 0, 9_000) < 9_000          # context cap
    with pytest.raises(OpenRouterContextTooLong):
        orc._preflight("m", "x" * 40_000, 0, 1_000)


# ── Step 2: truncated output is retried, not silently accepted ─────────────

class _Tracker:
    def log_api_call(self, *a, **k):
        pass


class _TruncatingClient:
    def __init__(self):
        self.max_tokens_seen = []

    def generate_completion(self, prompt, model, max_tokens):
        self.max_tokens_seen.append(max_tokens)
        if len(self.max_tokens_seen) == 1:   # first answer cut mid-array
            return {"content": '[{"number": 1, "text": "Q1", "propositions": {"a": "x"}}, {"number": 2, "te',
                    "usage": {}, "cost": 0.0, "finish_reason": "length"}
        return {"content": '[{"number": 1, "text": "Q1", "propositions": {"a": "x"}},'
                           ' {"number": 2, "text": "Q2", "propositions": {"a": "y"}}]',
                "usage": {}, "cost": 0.0, "finish_reason": "stop"}

    @staticmethod
    def estimate_cost(model, usage):
        return 0.0


def test_step2_retries_truncated_output_instead_of_keeping_salvage(monkeypatch):
    from modules.step2_qcm_extract_batch import Step2QCMExtractBatch
    monkeypatch.setenv("STEP2_MODEL", "p/model")
    monkeypatch.setenv("STEP2_FALLBACK_MODEL", "f/model")
    monkeypatch.setenv("STEP2_MAX_TOKENS", "1000")
    monkeypatch.setenv("STEP2_MAX_RETRIES", "3")
    ex = Step2QCMExtractBatch.__new__(Step2QCMExtractBatch)
    ex.client, ex.cost_tracker = _TruncatingClient(), _Tracker()
    ex.context = None
    qcms = ex._extract_all_qcms_batch("=== PAGE 1 ===\ntext", 1, 1, {})
    assert [q["number"] for q in qcms] == [1, 2]          # salvage of 1 QCM was NOT accepted
    assert ex.client.max_tokens_seen == [1000, 2000]       # retried with a larger budget


def test_step2_aborts_on_fatal_key_error(monkeypatch):
    from modules.step2_qcm_extract_batch import Step2QCMExtractBatch

    class _Dead:
        calls = 0

        def generate_completion(self, prompt, model, max_tokens):
            _Dead.calls += 1
            raise OpenRouterCreditsError("no credits", 402, model)

    monkeypatch.setenv("STEP2_MAX_RETRIES", "3")
    ex = Step2QCMExtractBatch.__new__(Step2QCMExtractBatch)
    ex.client, ex.cost_tracker, ex.context = _Dead(), _Tracker(), None
    with pytest.raises(OpenRouterCreditsError):
        ex._extract_all_qcms_batch("text", 1, 1, {})
    assert _Dead.calls == 1
