"""
step_call_logs — write-on-start / update-on-finish telemetry.

One row per unit of work (a step/sub-step execution OR a single AI call).
The "started" row is inserted IMMEDIATELY before the work begins, so a hang
is visible as a `running` row with an old started_at — never batched at the
end of a whole step (the pattern this replaces).

All SQL writes are best-effort: a Supabase blip must never break a pipeline
run. After 10 consecutive failures the logger silences itself for the rest
of the container's life and only prints a one-time notice.

Thread-safety / onde é chamado: mark_started/mark_finished run inside the
executor worker thread (or the event loop for the async client). Call
context is carried per-thread with a ContextVar — set it in the SAME thread
that performs the call (pipeline code does this via with_sub_step()).
"""
import contextvars
import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import contextlib

_MAX_INLINE = 20_000          # chars kept in SQL before offloading to Storage
_STUCK_MARK_THRESHOLD = 7200  # seconds after which new runs reap stale 'running' rows

_call_ctx: contextvars.ContextVar = contextvars.ContextVar("call_ctx", default=None)

_fail_lock = threading.Lock()
_fail_count = 0
_silenced = False


# ---------------------------------------------------------------------------
# Context plumbing
# ---------------------------------------------------------------------------

class CallContext:
    __slots__ = ("user_id", "project_name", "run_id", "step_number", "sub_step")

    def __init__(self, user_id: str, project_name: str, run_id: str,
                 step_number: str, sub_step: Optional[str] = None):
        self.user_id = user_id
        self.project_name = project_name
        self.run_id = run_id
        self.step_number = step_number
        self.sub_step = sub_step

    @classmethod
    def from_current(cls) -> "Optional[CallContext]":
        return _call_ctx.get()


def set_call_context(user_id: str, project_name: str, run_id: str,
                     step_number: str, sub_step: Optional[str] = None):
    """Set base context for the current thread. Returns a contextvars token."""
    return _call_ctx.set(
        CallContext(user_id, project_name, run_id, step_number, sub_step)
    )


def reset_call_context(token):
    _call_ctx.reset(token)


@contextmanager
def sub_step_scope(sub_step: str, item_ref: Optional[str] = None):
    """Temporarily switch sub_step (and optionally launch item_ref) for the
    current thread. Nested scopes inherit the base step context."""
    base = _call_ctx.get()
    if not base:
        yield
        return
    token = _call_ctx.set(base.__class__(
        base.user_id, base.project_name, base.run_id, base.step_number, sub_step
    ))
    item_token = _item_ref.set(item_ref) if item_ref else None
    try:
        yield
    finally:
        if item_token is not None:
            _item_ref.reset(item_token)
        _call_ctx.reset(token)


@contextmanager
def item_scope(item_ref: Optional[str]):
    """Temporarily tag every AI call in this block with an item reference
    (e.g. which page/chunk/batch is being processed)."""
    item_token = _item_ref.set(item_ref)
    try:
        yield
    finally:
        _item_ref.reset(item_token)


def set_item_ref(item_ref: Optional[str]):
    """Set/clear a long-lived item_ref (multi-call blocks). Returns a token
    for reset_item_ref()."""
    return _item_ref.set(item_ref)


def reset_item_ref(token):
    _item_ref.reset(token)


def current_sub_step() -> Optional[str]:
    ctx = _call_ctx.get()
    return ctx.sub_step if ctx else None


_item_ref: contextvars.ContextVar = contextvars.ContextVar("call_item_ref", default=None)


# ---------------------------------------------------------------------------
# Internal plumbing
# ---------------------------------------------------------------------------

def _fail(msg: str):
    global _fail_count, _silenced
    with _fail_lock:
        _fail_count += 1
        if _fail_count == 10:
            _silenced = True
            msg = "[TELEMETRY] silencing step_call_logs after repeated failures: " + msg
        else:
            msg = "[TELEMETRY] write failed: " + msg
    if not _silenced:
        for line in (msg,):
            try:
                print(line)
            except UnicodeEncodeError:
                print(line.encode("ascii", "replace").decode())


def _sb():
    try:
        from api.supabase_client import get_supabase
    except ImportError:
        # The Space adds `api/` itself to sys.path — import directly there.
        from supabase_client import get_supabase
    return get_supabase()


def _is_uuid(value: str) -> bool:
    import uuid as _uuid
    try:
        _uuid.UUID(str(value))
        return True
    except Exception:
        return False


def _project_id(user_id: str, project_name: str) -> Optional[str]:
    try:
        from project_manager import lookup_project_id
        uid = user_id
        # Normalize the auth-level user id to the SQL users row id, same way
        # real_api._resolve_project_id does (auth id ≠ SQL id sometimes).
        if not _is_uuid(user_id):
            try:
                try:
                    from auth import get_db_user_id
                except ImportError:
                    from api.auth import get_db_user_id
                uid = get_db_user_id({"id": user_id})
            except Exception:
                pass
        return lookup_project_id(uid, project_name)
    except Exception:
        return None


def _trim_safely(text: Optional[str]):
    """Return (inline_text_or_None, storage_ref_or_None). Offloads the full
    payload to Supabase Storage and stores a pointer when oversized."""
    if text is None:
        return None, None
    text = str(text)
    if len(text) <= _MAX_INLINE:
        return text, None
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")
    task_id = uuid_hex()
    ctx = _call_ctx.get()
    prefix = "telemetry"
    if ctx:
        prefix = f"{ctx.user_id}/{ctx.project_name}/telemetry/{ctx.run_id}/{ctx.step_number}"
    storage_path = f"{prefix}/{task_id}.txt"
    try:
        try:
            from api.storage_client import write_file
        except ImportError:
            from storage_client import write_file
        write_file(storage_path, text)
        return text[:_MAX_INLINE], storage_path
    except Exception as e:
        print(f"[TELEMETRY] offload failed: {e}")
        return text[:_MAX_INLINE], None


def uuid_hex() -> str:
    import uuid
    return uuid.uuid4().hex[:12]


def _reap_stale_running_rows(project_name: str, ctx: CallContext):
    """Self-healing stuck detection: whenever a NEW step_run starts, any
    'running' rows for the same project older than _STUCK_MARK_THRESHOLD are
    flipped to 'timeout' — they would otherwise stay 'running' forever after
    a container restart killed the mid-flight work. Only rows older than the
    threshold are touched so a concurrent in-flight step is never mis-flagged."""
    try:
        cutoff = (datetime.utcnow() - timedelta(seconds=_STUCK_MARK_THRESHOLD)).isoformat()
        _sb().table("step_call_logs").update({
            "status": "timeout",
            "completed_at": datetime.utcnow().isoformat(),
            "error_message": "container restart or abandoned run — row was still 'running'",
        }).eq("project_name", project_name).eq("status", "running").lt("started_at", cutoff).execute()
    except Exception as e:
        _fail(f"reap failed: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_step_run(user_id: str, project_name: str, step_id: str, run_id: str,
                  sub_step: Optional[str] = None) -> Optional[int]:
    """Insert a step_run row (kind='step_run', status='running') immediately
    before the step starts. Returns the row id (or None on failure)."""
    if _silenced:
        return None
    try:
        ctx = CallContext(user_id, project_name, run_id, str(step_id), sub_step)
        _reap_stale_running_rows(project_name, ctx)
        row = {
            "project_id": _project_id(user_id, project_name),
            "user_id": user_id,
            "project_name": project_name,
            "run_id": run_id,
            "step_number": str(step_id),
            "sub_step": sub_step,
            "kind": "step_run",
            "status": "running",
        }
        res = _sb().table("step_call_logs").insert(row).execute()
        data = getattr(res, "data", None) or []
        return data[0]["id"] if data else None
    except Exception as e:
        _fail(f"start_step_run {step_id}: {type(e).__name__}: {e}")
        return None


def finish_step_run(row_id: Optional[int], status: str, model: str = None,
                    duration_seconds: float = None, sub_step: str = None,
                    error_message: str = None):
    """Update a step_run row with the outcome. Accepts `timeout`/`cancelled`.
    Safe to call even when start returned None."""
    _finish(row_id, status=status, kind="step_run", model=model,
            duration_seconds=duration_seconds, sub_step=sub_step,
            error_message=error_message)


def log_ai_call_start(user_id: str = None, project_name: str = None,
                      step_number: str = None,
                      sub_step: Optional[str] = None, item_ref: Optional[str] = None,
                      run_id: str = None, model: str = None,
                      request_payload: Optional[str] = None) -> Optional[int]:
    """Insert a 'running' ai_call row immediately BEFORE the request.
    Context falls back to the thread CallContext when ids are omitted."""
    if _silenced:
        return None
    try:
        ctx = _call_ctx.get()
        user_id = user_id or (ctx.user_id if ctx else "unknown")
        project_name = project_name or (ctx.project_name if ctx else "unknown")
        run_id = run_id or (ctx.run_id if ctx else "unknown")
        step_number = str(step_number if step_number is not None else (ctx.step_number if ctx else "unknown"))
        sub_step = sub_step or (ctx.sub_step if ctx else None)
        item_ref = item_ref or _item_ref.get()
        req_inline, storage_ref = _trim_safely(request_payload)
        row = {
            "project_id": _project_id(user_id, project_name),
            "user_id": user_id,
            "project_name": project_name,
            "run_id": run_id,
            "step_number": step_number,
            "sub_step": sub_step,
            "item_ref": item_ref,
            "kind": "ai_call",
            "model": model,
            "request_payload": req_inline,
            "storage_ref": storage_ref,
            "status": "running",
        }
        res = _sb().table("step_call_logs").insert(row).execute()
        data = getattr(res, "data", None) or []
        return data[0]["id"] if data else None
    except Exception as e:
        _fail(f"ai_call_start: {type(e).__name__}: {e}")
        return None


def log_ai_call_finish(row_id: Optional[int], status: str = "success",
                       model: str = None, response_payload: Optional[str] = None,
                       usage: Optional[Dict] = None, cost: Optional[float] = None,
                       error: Optional[str] = None, started_ts: Optional[float] = None,
                       run_id: str = None):
    """UPDATE the ai_call row with outcome + tokens + duration. Preserves the
    in-flight started_at so duration reflects the call as a whole."""
    if not row_id:
        return
    _finish(
        row_id,
        status=status,
        kind="ai_call",
        model=model,
        response_payload=response_payload,
        usage=usage,
        cost=cost,
        error_message=error,
        duration_seconds=(time.time() - started_ts) if started_ts else None,
    )


def _finish(row_id: int, status: str, kind: str, model: str = None,
            response_payload: Optional[str] = None, usage: Optional[Dict] = None,
            cost: Optional[float] = None, error_message: Optional[str] = None,
            duration_seconds: Optional[float] = None, sub_step: Optional[str] = None):
    if _silenced:
        return
    try:
        update: Dict[str, Any] = {
            "status": status,
            "completed_at": datetime.utcnow().isoformat(),
        }
        if duration_seconds is not None:
            update["duration_seconds"] = round(float(duration_seconds), 2)
        if model:
            update["model"] = model
        if sub_step:
            update["sub_step"] = sub_step
        if error_message:
            update["error_message"] = str(error_message)[:_MAX_INLINE]
        if kind == "ai_call":
            resp_inline, storage_ref = _trim_safely(response_payload)
            if resp_inline is not None:
                update["response_payload"] = resp_inline
            if storage_ref:
                update["storage_ref"] = storage_ref
            if usage:
                update["prompt_tokens"] = _to_int(usage.get("prompt_tokens") or usage.get("prompt"))
                update["completion_tokens"] = _to_int(usage.get("completion_tokens") or usage.get("completion"))
            if cost is not None:
                update["cost_usd"] = round(float(cost), 6)
        _sb().table("step_call_logs").update(update).eq("id", row_id).execute()
    except Exception as e:
        _fail(f"finish {kind}: {type(e).__name__}: {e}")


def _to_int(value) -> Optional[int]:
    try:
        value = int(value)
        return value or None
    except (TypeError, ValueError):
        return None
