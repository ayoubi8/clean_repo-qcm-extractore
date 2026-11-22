"""Fake step cores for tests/test_step_process.py — importable by the spawned
child (tests/ is on sys.path, which multiprocessing passes to children)."""
import os
import time


def ok_core(spec, tracker, context, cancel_check, emit):
    emit({"type": "log", "line": {"text": "line 1"}})
    emit({"type": "log", "line": {"text": "line 2"}})
    if tracker is not None:
        tracker.log_api_call("step2_batch_p1-3", "m", {"prompt": 10, "completion": 5}, 0.25)
        tracker.log_api_call("cc_checker", "m", {"prompt": 1, "completion": 1}, 0.05)
    emit({"type": "step_ok"})


def env_core(spec, tracker, context, cancel_check, emit):
    from modules.utils import run_env
    emit({"type": "log", "line": {"text": f"key={run_env.getenv('OPENROUTER_API_KEY')}|{os.environ.get('OPENROUTER_API_KEY')}"}})
    emit({"type": "step_ok"})


def stop_core(spec, tracker, context, cancel_check, emit):
    for _ in range(200):
        if cancel_check():
            emit({"type": "stopped"})
            return
        time.sleep(0.05)
    emit({"type": "step_ok"})


def stubborn_core(spec, tracker, context, cancel_check, emit):
    emit({"type": "log", "line": {"text": "ignoring stop"}})
    time.sleep(60)


def raise_core(spec, tracker, context, cancel_check, emit):
    raise RuntimeError("boom")


def crash_core(spec, tracker, context, cancel_check, emit):
    emit({"type": "log", "line": {"text": "about to crash"}})
    os._exit(3)


def import_api_core(spec, tracker, context, cancel_check, emit):
    import time as _t
    t0 = _t.monotonic()
    from real_api import _call_step, _cascade_with_telemetry  # noqa: F401
    emit({"type": "log", "line": {"text": f"real_api imported in {(_t.monotonic() - t0):.1f}s"}})
    emit({"type": "step_ok"})


def _square(x):
    return x * x


def pool_core(spec, tracker, context, cancel_check, emit):
    from multiprocessing import Pool
    with Pool(2) as pool:
        total = sum(pool.map(_square, [1, 2, 3]))
    emit({"type": "log", "line": {"text": f"pool total {total}"}})
    emit({"type": "step_ok"})
