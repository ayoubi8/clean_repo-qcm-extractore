import sys
import io
from datetime import datetime

class LogCapture(io.TextIOBase):
    """
    Replace sys.stdout so all print() calls in pipeline modules
    get captured and forwarded to a callback.
    """
    def __init__(self, callback):
        self.callback = callback  # fn(line: dict) -> None
        self._original = sys.stdout

    def write(self, text: str):
        # Filter out empty or just newline writes
        if text.strip():
            # Basic color/type heuristic based on emojis or keywords
            line_type = "error" if "❌" in text or "ERROR" in text else \
                        "ok"    if "✅" in text or "[OK]" in text else \
                        "warn"  if "⚠️" in text or "[WARN]" in text else "info"
            
            self.callback({
                "ts": datetime.now().strftime("%H:%M:%S"),
                "type": line_type,
                "text": text.rstrip()
            })
        return len(text)

    def flush(self):
        # Required for TextIOBase
        pass

    def __enter__(self):
        sys.stdout = self
        return self

    def __exit__(self, *args):
        sys.stdout = self._original
