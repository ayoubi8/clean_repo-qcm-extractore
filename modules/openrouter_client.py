import os
from modules.utils import run_env  # per-run config overlay (see run_env.py)
import asyncio
import base64
import hashlib
import io
import random
import threading
import time
import json
from typing import List, Dict, Any, Optional, Tuple
import httpx
from PIL import Image
from dotenv import load_dotenv

from modules.utils.call_logger import log_ai_call_start, log_ai_call_finish

# Load environment variables
load_dotenv()

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


# ═══════════════════════════════════════════════════════════════════════════
# Typed errors — callers decide by TYPE, not by parsing strings.
#
#   OpenRouterFatalError      key/billing problem: every further call with the
#     ├ OpenRouterAuthError     same key fails too → abort the step, tell the user.
#     └ OpenRouterCreditsError
#   OpenRouterBadRequestError  this request/model combination is wrong → do NOT
#     └ OpenRouterContextTooLong  retry the same call; a fallback model may work.
#   OpenRouterRateLimited      429 → retried here with Retry-After.
#   OpenRouterTransientError   5xx / timeout / network / empty body → retried here.
#
# All subclass RuntimeError, so existing `except Exception` / `except
# RuntimeError` call sites keep working unchanged.
# ═══════════════════════════════════════════════════════════════════════════

class OpenRouterError(RuntimeError):
    retryable = False

    def __init__(self, message: str, status: Optional[int] = None, model: Optional[str] = None):
        super().__init__(message)
        self.status = status
        self.model = model


class OpenRouterFatalError(OpenRouterError):
    """The API key cannot make ANY call right now — stop the step."""


class OpenRouterAuthError(OpenRouterFatalError):
    pass


class OpenRouterCreditsError(OpenRouterFatalError):
    pass


class OpenRouterBadRequestError(OpenRouterError):
    pass


class OpenRouterContextTooLong(OpenRouterBadRequestError):
    pass


class OpenRouterRateLimited(OpenRouterError):
    retryable = True

    def __init__(self, message: str, status: Optional[int] = 429, model: Optional[str] = None,
                 retry_after: Optional[float] = None):
        super().__init__(message, status, model)
        self.retry_after = retry_after


class OpenRouterTransientError(OpenRouterError):
    retryable = True


_CONTEXT_MARKERS = ("context length", "context_length", "maximum context", "too many tokens",
                    "prompt is too long", "input is too long", "reduce the length")


def _classify(status: int, message: str, model: str, retry_after: Optional[float] = None) -> OpenRouterError:
    msg = f"HTTP {status} from OpenRouter for {model}: {message}"
    low = (message or "").lower()
    if status == 401:
        return OpenRouterAuthError(
            f"OpenRouter rejected the API key (401). Check the key in Settings. Details: {message}",
            status, model)
    if status == 402:
        return OpenRouterCreditsError(
            f"OpenRouter account has insufficient credits (402). Add credits or use another key. Details: {message}",
            status, model)
    if status == 429:
        return OpenRouterRateLimited(msg, status, model, retry_after)
    if status in (408, 425) or status >= 500:
        return OpenRouterTransientError(msg, status, model)
    if any(m in low for m in _CONTEXT_MARKERS):
        return OpenRouterContextTooLong(msg, status, model)
    # 400 bad params, 403 moderation, 404 no endpoint for model, 413, 422 …
    return OpenRouterBadRequestError(msg, status, model)


def _retry_after_seconds(response: httpx.Response) -> Optional[float]:
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


# ── Fatal-key circuit breaker ───────────────────────────────────────────────
# Many pipeline loops catch Exception per page and carry on. Without this, a
# dead key / empty balance makes a 60-page run send 60+ doomed requests. Once a
# key gets 401/402, further calls with it fail instantly for a short window.
_FATAL_TTL_S = 120.0
_fatal_keys: Dict[str, Tuple[OpenRouterFatalError, float]] = {}
_fatal_lock = threading.Lock()


def _key_id(api_key: str) -> str:
    return hashlib.sha256((api_key or "").encode()).hexdigest()[:16]


def _check_fatal(api_key: str) -> None:
    with _fatal_lock:
        hit = _fatal_keys.get(_key_id(api_key))
        if hit and hit[1] > time.time():
            raise hit[0].__class__(str(hit[0]), hit[0].status, hit[0].model)


def _mark_fatal(api_key: str, err: OpenRouterFatalError) -> None:
    with _fatal_lock:
        _fatal_keys[_key_id(api_key)] = (err, time.time() + _FATAL_TTL_S)


# ── Shared HTTP client (connection reuse; one TLS handshake per host) ───────
_sync_client: Optional[httpx.Client] = None
_sync_client_lock = threading.Lock()


def _timeout() -> httpx.Timeout:
    # Non-streaming completions send nothing until the model finishes, so the
    # READ timeout must cover the whole generation (reasoning models + 20k
    # output tokens regularly exceed the old flat 60s).
    read = float(run_env.getenv("OPENROUTER_READ_TIMEOUT", "180") or 180)
    return httpx.Timeout(connect=15.0, read=read, write=60.0, pool=60.0)


def _http2_available() -> bool:
    try:
        import h2  # noqa: F401
        return True
    except ImportError:
        return False


def _get_sync_client() -> httpx.Client:
    global _sync_client
    if _sync_client is None:
        with _sync_client_lock:
            if _sync_client is None:
                _sync_client = httpx.Client(
                    timeout=_timeout(),
                    http2=_http2_available(),
                    limits=httpx.Limits(max_connections=64, max_keepalive_connections=32),
                )
    return _sync_client


# ── Model limits (context window / max output) from OpenRouter /models ──────
_MODEL_LIMITS: Dict[str, Dict[str, Optional[int]]] = {}
_model_limits_fetched_at = 0.0
_model_limits_lock = threading.Lock()
_MODEL_LIMITS_TTL_S = 6 * 3600
_MODEL_LIMITS_RETRY_S = 600


def _model_limits(model: str) -> Dict[str, Optional[int]]:
    """{'context': int|None, 'max_output': int|None}; empty when unknown.
    Fetched once per 6h (public endpoint, no key). Never raises."""
    global _model_limits_fetched_at
    if str(run_env.getenv("OPENROUTER_PREFLIGHT", "1")).strip() in ("0", "false", "no"):
        return {}
    now = time.time()
    with _model_limits_lock:
        stale = (now - _model_limits_fetched_at) > (_MODEL_LIMITS_TTL_S if _MODEL_LIMITS else _MODEL_LIMITS_RETRY_S)
        if stale:
            _model_limits_fetched_at = now
            try:
                r = _get_sync_client().get(OPENROUTER_MODELS_URL, timeout=8.0)
                r.raise_for_status()
                fresh = {}
                for m in r.json().get("data", []):
                    tp = m.get("top_provider") or {}
                    fresh[m.get("id")] = {
                        "context": tp.get("context_length") or m.get("context_length"),
                        "max_output": tp.get("max_completion_tokens"),
                    }
                if fresh:
                    _MODEL_LIMITS.clear()
                    _MODEL_LIMITS.update(fresh)
            except Exception as e:
                print(f"[OpenRouter] model-limits fetch failed (pre-flight skipped): {e}")
        return dict(_MODEL_LIMITS.get(model) or {})


_CHARS_PER_TOKEN = 3.2      # conservative for French medical text (over-estimates tokens)
_TOKENS_PER_IMAGE = 1300    # conservative across Gemini / Qwen-VL at ≤1024px


def estimate_prompt_tokens(prompt: str, n_images: int = 0, system: Optional[str] = None) -> int:
    chars = len(prompt or "") + len(system or "")
    return int(chars / _CHARS_PER_TOKEN) + n_images * _TOKENS_PER_IMAGE + 32


def _preflight(model: str, prompt: str, n_images: int, max_tokens: int,
               system: Optional[str] = None) -> int:
    """Context control: refuse prompts that cannot fit, clamp max_tokens to what
    the model can actually emit (a too-large max_tokens is a 400 that used to be
    retried 3×). Returns the max_tokens to send."""
    lim = _model_limits(model)
    ctx, max_out = lim.get("context"), lim.get("max_output")
    if not ctx:
        return max_tokens
    est = estimate_prompt_tokens(prompt, n_images, system)
    if est >= ctx:
        raise OpenRouterContextTooLong(
            f"Prompt (~{est:,} tokens est.) does not fit {model}'s {ctx:,}-token context window — "
            f"split the input or pick a larger-context model.", None, model)
    allowed = ctx - est - 256
    if max_out:
        allowed = min(allowed, int(max_out))
    if allowed < max_tokens:
        new = max(256, int(allowed))
        print(f"[CTX] {model}: max_tokens {max_tokens:,} → {new:,} "
              f"(context {ctx:,}, prompt ~{est:,}, max output {max_out or 'n/a'})")
        return new
    return max_tokens


def _payload_to_text(payload: dict, prompt: str) -> str:
    """Debug-friendly request representation WITHOUT base64 image blobs."""
    return prompt


def _usage_to_dict(usage) -> dict:
    return usage if isinstance(usage, dict) else {}


def _backoff(attempt: int) -> float:
    return min(20.0, 2.0 * (2 ** attempt)) * (0.75 + random.random() * 0.5)


class OpenRouterClient:
    def __init__(self, cache_enabled: bool = False, api_key: Optional[str] = None):
        """
        Initialize the OpenRouter client.
        Args:
            cache_enabled (bool): kept for backwards compatibility (unused).
            api_key: explicit key; default = the active run's key (run_env
                     overlay → user's own key) or the server key from .env.
        """
        self.api_key = api_key or run_env.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            # Try to load from default location if not set
            try:
                load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))
                self.api_key = run_env.getenv("OPENROUTER_API_KEY")
            except Exception:
                pass

        self.model = run_env.getenv("STEP1_MODEL") or run_env.getenv("OCR_MODEL", "qwen/qwen3-vl-30b-a3b-instruct")
        self.fallback_model = run_env.getenv("STEP1_FALLBACK_MODEL", "qwen/qwen-2.5-vl-7b-instruct:free")
        self.site_url = run_env.getenv("SITE_URL", "https://local.dev")
        self.site_name = run_env.getenv("SITE_NAME", "QCM Extractor")
        self.max_attempts = max(1, int(run_env.getenv("OPENROUTER_MAX_ATTEMPTS", "3") or 3))

        # Masked key log for debugging
        masked_key = "None"
        if self.api_key:
            if len(self.api_key) <= 8:
                masked_key = "****"
            else:
                masked_key = self.api_key[:8] + "****" + self.api_key[-4:]
        print(f"[OpenRouterClient] Loaded API Key: {masked_key}")

        # Headers required by OpenRouter
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": self.site_url,
            "X-Title": self.site_name,
            "Content-Type": "application/json"
        }

    def _encode_image(self, image: Image.Image, format: str = "JPEG") -> str:
        """
        Encodes a PIL Image to a base64 string.
        Resizes image if too large (max 1024px) to optimize token usage.
        Compresses with quality=65 to reduce payload size while maintaining readability.
        """
        img_copy = image.copy()
        max_size = 1024
        if max(img_copy.size) > max_size:
            img_copy.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

        buffered = io.BytesIO()
        if img_copy.mode in ('RGBA', 'LA'):
            background = Image.new(img_copy.mode[:-1], img_copy.size, (255, 255, 255))
            background.paste(img_copy, img_copy.split()[-1])
            img_copy = background

        img_copy.convert('RGB').save(buffered, format=format, quality=65, optimize=True)
        return base64.b64encode(buffered.getvalue()).decode('utf-8')

    def _compose_messages(self, prompt: str, images: List[Image.Image] = None,
                          system: Optional[str] = None) -> List[Dict]:
        """Build the chat messages payload shared by the sync and async paths.

        Prompt caching: only the STATIC part may carry a cache breakpoint. When
        a caller passes `system` (fixed instructions), it goes first and is
        marked cacheable; the per-page `prompt` is never marked (marking a
        unique prompt only pays cache-write cost with zero cache hits).
        """
        messages: List[Dict] = []
        if system:
            messages.append({
                "role": "system",
                "content": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            })
        user_content: List[Dict] = [{"type": "text", "text": prompt}]
        for img in (images or []):
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{self._encode_image(img)}"},
            })
        messages.append({"role": "user", "content": user_content})
        return messages

    def _build_payload(self, prompt, images, max_tokens, target_model, temperature,
                       system=None, reasoning=None, response_format=None, provider=None) -> Dict[str, Any]:
        max_tokens = _preflight(target_model, prompt, len(images or []), max_tokens, system)
        payload: Dict[str, Any] = {
            "model": target_model,
            "messages": self._compose_messages(prompt, images, system),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "usage": {"include": True},   # real cost in the response
        }
        if reasoning:
            payload["reasoning"] = reasoning
        if response_format:
            payload["response_format"] = response_format
        prov = dict(provider or {})
        sort = (run_env.getenv("OPENROUTER_PROVIDER_SORT", "") or "").strip()
        if sort and "sort" not in prov:
            prov["sort"] = sort           # e.g. "throughput" / "latency" / "price"
        if response_format and "require_parameters" not in prov:
            prov["require_parameters"] = True
        if prov:
            payload["provider"] = prov
        return payload

    @staticmethod
    def _parse_response(response: httpx.Response, target_model: str) -> Dict[str, Any]:
        """HTTP response → result dict, or a typed OpenRouterError."""
        if response.status_code != 200:
            try:
                body = response.json()
                detail = (body.get("error") or {}).get("message") or response.text
            except Exception:
                detail = response.text
            raise _classify(response.status_code, str(detail)[:600], target_model,
                            _retry_after_seconds(response))
        try:
            result = response.json()
        except Exception as e:
            raise OpenRouterTransientError(f"Unparseable body from OpenRouter: {e}", 200, target_model)

        if result.get("error"):
            err = result["error"] if isinstance(result["error"], dict) else {"message": str(result["error"])}
            code = err.get("code")
            status = int(code) if str(code or "").isdigit() else 502
            raise _classify(status, str(err.get("message"))[:600], target_model)

        choices = result.get("choices") or []
        if not choices:
            raise OpenRouterTransientError("Empty response from API (no choices)", 200, target_model)
        choice = choices[0]
        if isinstance(choice.get("error"), dict):
            err = choice["error"]
            code = err.get("code")
            raise _classify(int(code) if str(code or "").isdigit() else 502,
                            str(err.get("message"))[:600], target_model)

        usage = _usage_to_dict(result.get("usage", {}))
        content = (choice.get("message") or {}).get("content")
        finish = choice.get("finish_reason")
        if finish == "length":
            print(f"[OpenRouter] ⚠️ {target_model} stopped at max_tokens (finish_reason=length) — "
                  f"output is TRUNCATED{' and EMPTY (reasoning used the whole budget)' if not content else ''}.")
        return {
            "content": content or "",
            "usage": usage,
            "cost": usage.get("cost", 0.0),       # Real cost from OpenRouter API
            "finish_reason": finish,
            "native_finish_reason": choice.get("native_finish_reason"),
            "model": result.get("model") or target_model,
        }

    def generate_completion(self, prompt: str, images: List[Image.Image] = None, max_tokens: int = 4000,
                            model: str = None, temperature: float = 0.1, *, system: Optional[str] = None,
                            reasoning: Optional[dict] = None, response_format: Optional[dict] = None,
                            provider: Optional[dict] = None) -> Dict[str, Any]:
        """
        Call OpenRouter. Returns {content, usage, cost, finish_reason, model}.

        Retry policy (the ONLY retry layer for transport problems): transient
        errors (5xx/timeout/network/empty) and 429 (honouring Retry-After) are
        retried up to OPENROUTER_MAX_ATTEMPTS; everything else raises a typed
        OpenRouterError immediately. finish_reason == "length" means the
        output is truncated — callers must not treat salvaged JSON as complete.
        """
        target_model = model if model else self.model
        if not self.api_key:
            raise OpenRouterAuthError("OPENROUTER_API_KEY is not set. Please check your .env file / Settings.")
        _check_fatal(self.api_key)

        _t0 = time.time()
        _row = log_ai_call_start(user_id=None, project_name=None, step_number=None,
                                 model=target_model, request_payload=prompt)
        _status, _response_payload, _usage, _cost, _err = "error", None, None, None, None
        _answered_model = target_model
        try:
            payload = self._build_payload(prompt, images, max_tokens, target_model, temperature,
                                          system, reasoning, response_format, provider)
            client = _get_sync_client()
            for attempt in range(self.max_attempts):
                try:
                    try:
                        response = client.post(OPENROUTER_URL, headers=self.headers, json=payload)
                    except httpx.HTTPError as e:   # timeout / connect / read errors
                        raise OpenRouterTransientError(f"{type(e).__name__}: {e}", None, target_model)
                    out = self._parse_response(response, target_model)
                    _status, _response_payload = "success", out["content"]
                    _usage, _cost, _answered_model = out["usage"], out["cost"], out["model"]
                    return out
                except OpenRouterError as e:
                    _err = str(e)
                    print(f"Error calling OpenRouter (attempt {attempt + 1}/{self.max_attempts}, "
                          f"{type(e).__name__}): {e}")
                    if isinstance(e, OpenRouterFatalError):
                        _mark_fatal(self.api_key, e)
                    if not e.retryable or attempt == self.max_attempts - 1:
                        raise
                    wait = _backoff(attempt)
                    if isinstance(e, OpenRouterRateLimited) and e.retry_after is not None:
                        wait = min(30.0, max(wait, e.retry_after))
                    time.sleep(wait)
            raise OpenRouterTransientError("unreachable", None, target_model)
        except Exception as e:
            _status = "error"
            _err = _err or str(e)
            raise
        finally:
            log_ai_call_finish(_row, status=_status, model=_answered_model,
                               response_payload=_response_payload, usage=_usage, cost=_cost,
                               error=_err, started_ts=_t0)

    async def generate_completion_async(self, prompt: str, images: List[Image.Image] = None, max_tokens: int = 4000,
                                        model: str = None, temperature: float = 0.1, *,
                                        system: Optional[str] = None, reasoning: Optional[dict] = None,
                                        response_format: Optional[dict] = None,
                                        provider: Optional[dict] = None) -> Dict[str, Any]:
        """Async mirror of generate_completion — same payload, typed errors and
        retry policy (used by the parallel CC checker). Uses a per-call
        AsyncClient because callers run each batch on a fresh event loop
        (asyncio.run), and an AsyncClient cannot be shared across loops."""
        target_model = model if model else self.model
        if not self.api_key:
            raise OpenRouterAuthError("OPENROUTER_API_KEY is not set. Please check your .env file / Settings.")
        _check_fatal(self.api_key)

        _t0 = time.time()
        _row = await asyncio.to_thread(log_ai_call_start, None, None, None, target_model, prompt)
        _status, _response_payload, _usage, _cost, _err = "error", None, None, None, None
        _answered_model = target_model
        try:
            payload = await asyncio.to_thread(self._build_payload, prompt, images, max_tokens, target_model,
                                              temperature, system, reasoning, response_format, provider)
            async with httpx.AsyncClient(timeout=_timeout()) as client:
                for attempt in range(self.max_attempts):
                    try:
                        try:
                            response = await client.post(OPENROUTER_URL, headers=self.headers, json=payload)
                        except httpx.HTTPError as e:
                            raise OpenRouterTransientError(f"{type(e).__name__}: {e}", None, target_model)
                        out = self._parse_response(response, target_model)
                        _status, _response_payload = "success", out["content"]
                        _usage, _cost, _answered_model = out["usage"], out["cost"], out["model"]
                        return out
                    except OpenRouterError as e:
                        _err = str(e)
                        print(f"Error calling OpenRouter (attempt {attempt + 1}/{self.max_attempts}, "
                              f"{type(e).__name__}): {e}")
                        if isinstance(e, OpenRouterFatalError):
                            _mark_fatal(self.api_key, e)
                        if not e.retryable or attempt == self.max_attempts - 1:
                            raise
                        wait = _backoff(attempt)
                        if isinstance(e, OpenRouterRateLimited) and e.retry_after is not None:
                            wait = min(30.0, max(wait, e.retry_after))
                        await asyncio.sleep(wait)
            raise OpenRouterTransientError("unreachable", None, target_model)
        except Exception as e:
            _status = "error"
            _err = _err or str(e)
            raise
        finally:
            await asyncio.to_thread(log_ai_call_finish, _row, _status, _answered_model, _response_payload,
                                    _usage, _cost, _err, _t0)

    @staticmethod
    def get_cost(response: Dict) -> float:
        """
        Get the REAL cost from the API response.
        Falls back to estimate_cost() if the API didn't return a cost.
        """
        api_cost = response.get('cost', 0.0)
        if api_cost and float(api_cost) > 0:
            return float(api_cost)
        return OpenRouterClient.estimate_cost('unknown', response.get('usage', {}))

    @staticmethod
    def estimate_cost(model: str, usage: Dict[str, int]) -> float:
        """
        FALLBACK: Estimate cost based on usage and model.
        Prefer get_cost() which reads the real cost from the API.
        """
        rates = {
            "qwen/qwen-2-vl-72b-instruct": {"prompt": 0.4, "completion": 0.4},
            "qwen/qwen-2-vl-7b-instruct": {"prompt": 0.1, "completion": 0.1},
            "qwen/qwen-2.5-vl-7b-instruct:free": {"prompt": 0.0, "completion": 0.0},
            "nvidia/nemotron-3-nano-30b-a3b:free": {"prompt": 0.0, "completion": 0.0},
            "google/gemini-2.0-flash-exp:free": {"prompt": 0.0, "completion": 0.0},
            "google/gemma-3-27b-it:free": {"prompt": 0.0, "completion": 0.0},
            "google/gemini-2.0-flash-lite-001": {"prompt": 0.1, "completion": 0.3},
            "deepseek/deepseek-r1-distill-llama-70b": {"prompt": 0.23, "completion": 0.69},
        }
        rate = rates.get(model, {"prompt": 0.1, "completion": 0.1})
        p_tokens = (usage or {}).get('prompt_tokens', 0)
        c_tokens = (usage or {}).get('completion_tokens', 0)
        return (p_tokens / 1_000_000 * rate['prompt']) + (c_tokens / 1_000_000 * rate['completion'])

    def analyze_structure(self, pages: List[Image.Image]) -> Dict[str, Any]:
        """
        Analyzes the document structure using sample pages.
        Returns a dictionary containing the detected structure and metadata.
        """
        print("Sending sample pages for structure analysis...")

        prompt = """
        You are a medical QCM extraction specialist. Analyze these sample pages and identify:

        1. **QCM Structure**:
           - Question format pattern
           - Proposition markers (A, B, C, D, E or 1, 2, 3...)
           - Answer key format (Correct: AB, Correct: A, etc.)

        2. **Metadata Detection**:
           - Source information (university name, exam name)
           - Year/date if present
           - Category/Module names
           - Page headers/footers

        3. **Correction Format**:
           - Inline corrections (next to questions)
           - Separate correction page (corrigé-type)
           - Answer key location pattern

        4. **Layout Characteristics**:
           - Single/multi-column
           - Questions per page estimate
           - Special markers or separators

        Return JSON format:
        {
            "structure": {
                "qcm_pattern": "detected pattern description",
                "proposition_markers": ["A", "B", "C", "D", "E"],
                "answer_format": "format description"
            },
            "metadata": {
                "source_detected": "string or null",
                "year_detected": "number or null",
                "categories_found": ["category1", "category2"]
            },
            "correction_type": "inline | separate_page | mixed",
            "estimated_qcm_count": number
        }
        """

        try:
            response = self.generate_completion(prompt, pages)
            cleaned_text = response['content'].replace("```json", "").replace("```", "").strip()
            start_idx = cleaned_text.find('{')
            end_idx = cleaned_text.rfind('}')
            if start_idx != -1 and end_idx != -1:
                return json.loads(cleaned_text[start_idx:end_idx + 1])
            raise ValueError("No JSON object found in response")
        except OpenRouterFatalError:
            raise
        except Exception as e:
            print(f"Error parsing structure analysis response: {e}")
            return {
                "structure": {
                    "qcm_pattern": "unknown",
                    "proposition_markers": ["A", "B", "C", "D", "E"],
                    "answer_format": "unknown"
                },
                "metadata": {
                    "source_detected": None,
                    "year_detected": None,
                    "categories_found": []
                },
                "correction_type": "inline",
                "estimated_qcm_count": 0
            }
