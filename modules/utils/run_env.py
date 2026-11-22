"""Per-run configuration overlay — replaces process-global os.environ writes.

Why: the API used to write each user's API key and each run's model choices
into os.environ. With several runs in one process (5-PDF batches, two users)
one run silently used another run's key/models. Now every run gets its own
overlay dict held in a ContextVar; pipeline modules read config through
`getenv()`, which checks the active run's overlay first and falls back to the
real process environment (.env / Settings).

The same ContextVar mechanism carries the per-run stdout sink (LogCapture)
and the per-run `input()` auto-responder, so concurrent runs never see each
other's logs or answers.

Propagation rules:
  * asyncio tasks copy the context at creation (automatic).
  * asyncio.to_thread copies the context (automatic).
  * loop.run_in_executor / ThreadPoolExecutor.submit / threading.Thread do
    NOT — wrap the callable with `bind(fn)` at submit time.
"""
import builtins
import contextlib
import contextvars
import os
import sys
from typing import Callable, Optional

_overlay: contextvars.ContextVar = contextvars.ContextVar("run_env_overlay", default=None)
_input_handler: contextvars.ContextVar = contextvars.ContextVar("run_env_input", default=None)


# ── Config overlay ────────────────────────────────────────────────────────

def getenv(key: str, default=None):
    """os.getenv, but the active run's overlay wins over the process env."""
    ov = _overlay.get()
    if ov is not None and key in ov and ov[key] is not None:
        return ov[key]
    return os.environ.get(key, default)


def setenv(key: str, value: str) -> None:
    """Set a config value for the active run only.

    Outside a run scope (CLI main.py, scripts, tests) this keeps the legacy
    behaviour and writes the process environment.
    """
    ov = _overlay.get()
    if ov is None:
        os.environ[key] = value
    else:
        ov[key] = value


def current_overlay() -> Optional[dict]:
    """The active run's overlay (None outside a run) — handed to a child
    process so it runs with the same key / model settings."""
    return _overlay.get()


def in_run_scope() -> bool:
    return _overlay.get() is not None


@contextlib.contextmanager
def run_scope(initial: Optional[dict] = None):
    """Enter a fresh overlay for one run (values set here never leak out)."""
    token = _overlay.set({k: v for k, v in (initial or {}).items() if v})
    try:
        yield
    finally:
        _overlay.reset(token)


def enter_run(initial: Optional[dict] = None) -> None:
    """Start a fresh overlay in the CURRENT context without a reset token.

    Only for code that runs in its own asyncio Task (each Task owns a copy of
    the context, so the overlay dies with the task and never leaks)."""
    _overlay.set({k: v for k, v in (initial or {}).items() if v})


def bind(fn: Callable) -> Callable:
    """Return `fn` bound to a COPY of the caller's context (overlay, log sink,
    input handler, call-logger context). Call at submit time — one copy per
    submitted call, so concurrent workers never share a Context object."""
    ctx = contextvars.copy_context()

    def _bound(*args, **kwargs):
        return ctx.run(fn, *args, **kwargs)

    return _bound


# ── Per-run input() responder ─────────────────────────────────────────────

_original_input = builtins.input


def _routed_input(prompt=""):
    handler = _input_handler.get()
    if handler is not None:
        return handler(prompt)
    return _original_input(prompt)


def install_input_router() -> None:
    """Install once: builtins.input dispatches to the active run's handler."""
    if builtins.input is not _routed_input:
        builtins.input = _routed_input


@contextlib.contextmanager
def input_scope(handler: Callable[[str], str]):
    install_input_router()
    token = _input_handler.set(handler)
    try:
        yield
    finally:
        _input_handler.reset(token)


def set_input_handler(handler: Callable[[str], str]) -> None:
    """Non-scoped variant for code that already runs inside its own context
    (a worker bound with `bind`) — the value dies with that context."""
    install_input_router()
    _input_handler.set(handler)
