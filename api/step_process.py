"""Step runner — Phase 5 (docs/plans/phase5-step-runner-process-plan.md).

Runs the CPU-heavy middle of a step run (`_call_step` + Step 2's metadata
cascade) either:
  * `thread`  — in the API's thread pool (the behaviour before Phase 5), or
  * `process` — in a fresh child process (spawn), so the step's Python work
    no longer competes with the website for the API process's GIL, Cancel can
    really end it, and a crash can't take the API down.

Both modes run the SAME `core_sequence` and report through the same events,
so `_run_step_task` handles one protocol:

  {"type": "log", "line": {...}}           a captured print() line
  {"type": "error", "error": str}          the step raised
  {"type": "stopped"}                      cooperative stop honoured
  {"type": "step_ok"}                      _call_step finished
  {"type": "cascade", "result": {...}}     Step 2 cascade finished
  {"type": "cascade_error", "error": str}  Step 2 cascade raised
  {"type": "costs", "calls": [...]}        process mode: AI calls made in the child
  {"type": "finished"}                     the core ended normally

Mode: env STEP_RUNNER=thread|process (default thread).
Import rule: no module-level import of real_api (it imports this module).
"""
from __future__ import annotations

import asyncio
import importlib
import json
import multiprocessing as mp
import os
import threading
import traceback
from typing import Callable, Dict, Optional

TERMINAL = {"error", "stopped", "finished"}


def runner_mode() -> str:
    m = str(os.environ.get("STEP_RUNNER", "thread")).strip().lower()
    return "process" if m == "process" else "thread"


def max_processes() -> int:
    try:
        raw = os.environ.get("MAX_STEP_PROCESSES") or os.environ.get("AUTORUN_BATCH_CONCURRENCY") or "5"
        return max(1, int(raw))
    except ValueError:
        return 5


def cancel_grace_s() -> float:
    try:
        return max(0.0, float(os.environ.get("STEP_CANCEL_GRACE_S", "10")))
    except ValueError:
        return 10.0


def _jsonable(obj):
    try:
        return json.loads(json.dumps(obj, default=str))
    except Exception:
        return {"status": "unknown", "repr": str(obj)[:500]}


# ── The core (runs in a worker thread OR in the child process) ──────────────

def core_sequence(spec: Dict, tracker, context, cancel_check: Callable[[], bool],
                  emit: Callable[[Dict], None]) -> None:
    """_call_step, then (Step 2) the metadata cascade. Never raises."""
    from log_capture import LogCapture
    from real_api import _call_step, _cascade_with_telemetry

    step_id = str(spec["step_id"])
    user_id, project = spec["user_id"], spec["project"]
    config = spec.get("config") or {}
    run_id = spec.get("run_id") or ""

    def log(line):
        emit({"type": "log", "line": line})

    try:
        from modules.utils.call_logger import set_call_context
        set_call_context(user_id, project, run_id, step_id)
    except Exception:
        pass

    try:
        with LogCapture(log):
            _call_step(step_id, tracker, context, config, cancel_check=cancel_check)
    except Exception as e:
        traceback.print_exc()
        emit({"type": "error", "error": f"{type(e).__name__}: {e}", "trace": _trace_tail()})
        return

    if cancel_check():
        emit({"type": "stopped"})
        return
    emit({"type": "step_ok"})

    if step_id == "2":
        with LogCapture(log):
            try:
                step3_cfg = config.get("step3", config.get("step3_config", {}))
                res = _cascade_with_telemetry(tracker, context, user_id, project,
                                              step3_cfg, cancel_check, step_id, run_id)
                emit({"type": "cascade", "result": _jsonable(res or {})})
            except Exception as e:
                traceback.print_exc()
                emit({"type": "cascade_error", "error": str(e)})


def _trace_tail(frames: int = 3) -> str:
    """Last frames of the current exception, compact (for the UI log)."""
    tb = traceback.format_exc().strip().splitlines()
    keep = [l.strip() for l in tb if l.strip().startswith("File ")][-frames:]
    return " ← ".join(reversed(keep))[:600]


def _resolve(path: Optional[str]) -> Callable:
    """'module:function' -> callable (tests swap the core)."""
    if not path:
        return core_sequence
    mod, _, fn = path.partition(":")
    return getattr(importlib.import_module(mod), fn)


# ── Child process entry ─────────────────────────────────────────────────────

def _child_entry(spec: Dict, conn, stop_evt) -> None:
    def send(msg):
        try:
            conn.send(msg)
        except Exception:
            pass

    try:
        try:
            mp.current_process()._config["daemon"] = False
        except Exception:
            pass
        overlay = spec.get("overlay") or {}
        # This process serves ONE run: its config can live in os.environ too
        # (modules that read os.environ directly see the user's key/models).
        for k, v in overlay.items():
            if isinstance(v, str) and v:
                os.environ[k] = v
        from modules.utils import run_env
        run_env.enter_run(overlay)

        core = _resolve(spec.get("core"))
        tracker, context = _child_project(spec)
        snap = tracker.snapshot() if hasattr(tracker, "snapshot") else {}
        try:
            core(spec, tracker, context, stop_evt.is_set, send)
        finally:
            if hasattr(tracker, "calls_since"):
                send({"type": "costs", "calls": tracker.calls_since(snap)})
        send({"type": "finished"})
    except Exception as e:
        traceback.print_exc()
        send({"type": "error", "error": f"step runner: {e}"})
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _child_project(spec: Dict):
    if spec.get("core"):          # test cores don't need a real project
        from modules.utils.cost_tracker import CostTracker
        return CostTracker(), None
    from project_manager import get_or_create
    d = get_or_create(spec["project"], spec["user_id"])
    return d["tracker"], d["context"]


# ── API side ────────────────────────────────────────────────────────────────

_sem: Optional[asyncio.Semaphore] = None
_running = 0


def _semaphore() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(max_processes())
    return _sem


def running_processes() -> int:
    return _running


async def run_core(spec: Dict, *, tracker, context, should_stop: Callable[[], bool],
                   on_log: Callable[[Dict], None], on_event: Callable[[Dict], None],
                   mode: Optional[str] = None) -> None:
    """Run the core and deliver its events. Returns when it has ended."""
    if (mode or runner_mode()) == "process":
        await _run_in_process(spec, should_stop, on_log, on_event)
    else:
        await _run_in_thread(spec, tracker, context, should_stop, on_log, on_event)


async def _pump(q: asyncio.Queue, on_event, tick=None) -> None:
    while True:
        if tick is None:
            ev = await q.get()
        else:
            try:
                ev = await asyncio.wait_for(q.get(), 0.5)
            except asyncio.TimeoutError:
                tick()
                continue
            tick()
        if ev.get("type") == "_end":
            return
        on_event(ev)


async def _run_in_thread(spec, tracker, context, should_stop, on_log, on_event) -> None:
    from modules.utils import run_env
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    def emit(ev):
        if ev.get("type") == "log":
            on_log(ev["line"])          # straight to job_manager, as before
        else:
            loop.call_soon_threadsafe(q.put_nowait, ev)

    def work():
        try:
            _resolve(spec.get("core"))(spec, tracker, context, should_stop, emit)
            emit({"type": "finished"})
        except Exception as e:           # core_sequence never raises; test cores might
            traceback.print_exc()
            emit({"type": "error", "error": str(e)})
        finally:
            loop.call_soon_threadsafe(q.put_nowait, {"type": "_end"})

    fut = loop.run_in_executor(None, run_env.bind(work))
    await _pump(q, on_event)
    await fut


def _reap(proc, grace: float) -> None:
    """Give the child `grace` seconds to honour the stop flag, then kill it."""
    proc.join(grace)
    if proc.is_alive():
        print(f"[STEP-PROCESS] {proc.name} still running after {grace:.0f}s — terminating")
        proc.terminate()
        proc.join(5)
        if proc.is_alive():
            proc.kill()
            proc.join(2)


async def _run_in_process(spec, should_stop, on_log, on_event) -> None:
    global _running
    loop = asyncio.get_running_loop()
    sem = _semaphore()
    if sem.locked():
        on_log({"ts": _now(), "type": "info",
                "text": f"⏳ Waiting for a free step runner ({_running} running)…"})
    async with sem:
        ctx = mp.get_context("spawn")
        parent_conn, child_conn = ctx.Pipe(duplex=False)
        stop_evt = ctx.Event()
        proc = ctx.Process(target=_child_entry, args=(spec, child_conn, stop_evt), daemon=True,
                           name=f"step-{spec.get('step_id')}-{spec.get('project', '')[:24]}")
        await loop.run_in_executor(None, proc.start)
        child_conn.close()
        _running += 1
        q: asyncio.Queue = asyncio.Queue()

        def reader():
            try:
                while True:
                    msg = parent_conn.recv()
                    if msg.get("type") == "log":
                        on_log(msg["line"])
                    else:
                        loop.call_soon_threadsafe(q.put_nowait, msg)
            except (EOFError, OSError):
                pass
            finally:
                loop.call_soon_threadsafe(q.put_nowait, {"type": "_end"})

        threading.Thread(target=reader, daemon=True, name=f"{proc.name}-reader").start()
        seen = set()
        dead_since = [0.0]

        def tick():
            if not stop_evt.is_set() and should_stop():
                stop_evt.set()
            # Don't rely on pipe EOF alone: a child that dies before it even
            # loads (e.g. during spawn's module preparation) may leave the
            # pipe open on some platforms. Dead for 2 s -> end the wait.
            if not proc.is_alive():
                now = loop.time()
                if not dead_since[0]:
                    dead_since[0] = now
                elif now - dead_since[0] > 2.0:
                    q.put_nowait({"type": "_end"})

        def handle(ev):
            seen.add(ev.get("type"))
            on_event(ev)

        try:
            await _pump(q, handle, tick)
            await loop.run_in_executor(None, proc.join, 10)
            if "finished" not in seen and "error" not in seen:
                code = proc.exitcode
                on_event({"type": "error",
                          "error": f"Step process exited unexpectedly (exit code {code})"})
        except asyncio.CancelledError:
            # Cancel: ask nicely, then kill after the grace period (in the
            # background — the cancelled task must return right away).
            stop_evt.set()
            threading.Thread(target=_reap, args=(proc, cancel_grace_s()), daemon=True).start()
            raise
        finally:
            _running -= 1
            try:
                parent_conn.close()
            except Exception:
                pass


def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%H:%M:%S")
