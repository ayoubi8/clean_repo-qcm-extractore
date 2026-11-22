"""Event-loop lag probe (Phase 5 step 5.0).

An asyncio task sleeps 100 ms in a loop and records how late it wakes up.
Lag = time the event loop could not run — exactly what makes every request
slow while a step hogs the process. p50/p95/p99 over the last minute are
served by GET /debug/loop-lag; p99 above LOOP_LAG_WARN_MS (200) is logged.
"""
from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from typing import Deque, Dict, Optional, Tuple

INTERVAL = 0.1
WINDOW_S = 60.0

_samples: Deque[Tuple[float, float]] = deque()   # (monotonic time, lag ms)
_task: Optional[asyncio.Task] = None


def _pct(values, p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return round(s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))], 1)


def stats() -> Dict:
    now = time.monotonic()
    vals = [lag for t, lag in _samples if now - t <= WINDOW_S]
    return {"window_s": WINDOW_S, "samples": len(vals), "p50_ms": _pct(vals, 50),
            "p95_ms": _pct(vals, 95), "p99_ms": _pct(vals, 99),
            "max_ms": round(max(vals), 1) if vals else 0.0}


async def _probe() -> None:
    warn_ms = float(os.environ.get("LOOP_LAG_WARN_MS", "200"))
    last_warn = 0.0
    while True:
        start = time.monotonic()
        await asyncio.sleep(INTERVAL)
        now = time.monotonic()
        lag = max(0.0, (now - start - INTERVAL) * 1000)
        _samples.append((now, lag))
        while _samples and now - _samples[0][0] > WINDOW_S:
            _samples.popleft()
        if lag > warn_ms and now - last_warn > 30:
            last_warn = now
            s = stats()
            print(f"[LOOP-LAG] {lag:.0f} ms stall — last minute p95={s['p95_ms']} ms p99={s['p99_ms']} ms")


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.ensure_future(_probe())
