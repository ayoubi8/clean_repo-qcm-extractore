import contextvars
import io
import sys
from datetime import datetime

# The active run's log sink. Held in a ContextVar (not by swapping
# sys.stdout per run) so concurrent runs — 5-PDF batches, two users — each
# get only their own print() lines. Worker threads inherit the sink when the
# callable is wrapped with modules.utils.run_env.bind().
_sink: contextvars.ContextVar = contextvars.ContextVar("log_capture_sink", default=None)


def _classify(text: str) -> str:
    # Basic color/type heuristic based on emojis or keywords
    return ("error" if "❌" in text or "ERROR" in text else
            "ok"    if "✅" in text or "[OK]" in text else
            "warn"  if "⚠️" in text or "[WARN]" in text else "info")


class _StdoutRouter(io.TextIOBase):
    """Installed once as sys.stdout. Lines go to the current context's sink,
    or to the real stdout when no run is capturing in this context."""

    def __init__(self, wrapped):
        self._wrapped = wrapped

    def write(self, text: str):
        sink = _sink.get()
        if sink is None:
            return self._wrapped.write(text)
        if text.strip():
            sink({
                "ts": datetime.now().strftime("%H:%M:%S"),
                "type": _classify(text),
                "text": text.rstrip(),
            })
        return len(text)

    def flush(self):
        try:
            self._wrapped.flush()
        except Exception:
            pass

    @property
    def encoding(self):
        return getattr(self._wrapped, "encoding", "utf-8")


def _install_router() -> None:
    if not isinstance(sys.stdout, _StdoutRouter):
        sys.stdout = _StdoutRouter(sys.stdout)


class LogCapture:
    """Route print() calls made in this context (and in workers bound with
    run_env.bind) to `callback`. Safe to use from many runs at once."""

    def __init__(self, callback):
        self.callback = callback  # fn(line: dict) -> None
        self._token = None

    def __enter__(self):
        _install_router()
        self._token = _sink.set(self.callback)
        return self

    def __exit__(self, *args):
        if self._token is not None:
            _sink.reset(self._token)
            self._token = None
