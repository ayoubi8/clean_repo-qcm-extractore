"""Concurrent runs must not see each other's config, logs, input answers or
job state (previously all four were process-global)."""
import asyncio
import builtins
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

from modules.utils import run_env  # noqa: E402
from log_capture import LogCapture  # noqa: E402
from job_manager import JobManager, job_project  # noqa: E402


def _fake_run(name: str, key: str, model: str, logs: list, barrier: threading.Barrier, out: dict):
    """Mimics _run_step_task: overlay + log sink + input handler, then a
    nested ThreadPoolExecutor worker (like Step 1's page pool)."""
    async def task():
        run_env.enter_run({"OPENROUTER_API_KEY": key})
        loop = asyncio.get_event_loop()

        def worker():
            with LogCapture(logs.append):
                run_env.setenv("STEP2_MODEL", model)
                run_env.set_input_handler(lambda prompt="": f"answer-{name}")
                barrier.wait(timeout=5)          # both runs active at once
                print(f"hello from {name}")

                def page():
                    print(f"page log {name}")
                    return (run_env.getenv("OPENROUTER_API_KEY"),
                            run_env.getenv("STEP2_MODEL"), input("ocr guidance?"))

                with ThreadPoolExecutor(max_workers=2) as ex:
                    out[name] = ex.submit(run_env.bind(page)).result()

        await loop.run_in_executor(None, run_env.bind(worker))

    asyncio.run(task())


def test_concurrent_runs_are_isolated():
    os.environ["OPENROUTER_API_KEY"] = "server-key"
    barrier = threading.Barrier(2)
    logs_a, logs_b, out = [], [], {}
    ta = threading.Thread(target=_fake_run, args=("A", "key-A", "model-A", logs_a, barrier, out))
    tb = threading.Thread(target=_fake_run, args=("B", "key-B", "model-B", logs_b, barrier, out))
    ta.start(); tb.start(); ta.join(10); tb.join(10)

    assert out["A"] == ("key-A", "model-A", "answer-A")
    assert out["B"] == ("key-B", "model-B", "answer-B")
    texts_a = [l["text"] for l in logs_a]
    texts_b = [l["text"] for l in logs_b]
    assert texts_a == ["hello from A", "page log A"]
    assert texts_b == ["hello from B", "page log B"]
    # Nothing leaked into the process environment / outside a run.
    assert os.environ["OPENROUTER_API_KEY"] == "server-key"
    assert "STEP2_MODEL" not in os.environ or os.environ["STEP2_MODEL"] not in ("model-A", "model-B")
    assert run_env.getenv("OPENROUTER_API_KEY") == "server-key"
    assert builtins.input is run_env._routed_input  # router installed once, no per-run swap


def test_outside_run_scope_keeps_legacy_env_behaviour(monkeypatch):
    monkeypatch.delenv("RUN_ENV_TEST_KEY", raising=False)
    run_env.setenv("RUN_ENV_TEST_KEY", "x")        # CLI path: writes os.environ
    assert os.environ["RUN_ENV_TEST_KEY"] == "x"
    with run_env.run_scope({"RUN_ENV_TEST_KEY": "y"}):
        assert run_env.getenv("RUN_ENV_TEST_KEY") == "y"
    assert run_env.getenv("RUN_ENV_TEST_KEY") == "x"


def test_job_keys_are_user_scoped():
    jm = JobManager()

    async def scenario():
        t = asyncio.ensure_future(asyncio.sleep(0.05))
        jm.set_running(job_project("user-1", "immuno"), "2", t)
        jm.append_log(job_project("user-1", "immuno"), "2", {"text": "secret"})
        assert jm.is_running(job_project("user-1", "immuno"), "2")
        assert not jm.is_running(job_project("user-2", "immuno"), "2")
        assert jm.get_logs(job_project("user-2", "immuno"), "2") == []
        assert jm.get_status(job_project("user-2", "immuno"), "2") == "idle"
        await t

    asyncio.run(scenario())
