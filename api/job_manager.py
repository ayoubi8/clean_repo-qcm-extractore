import asyncio
import threading
from typing import Dict, Optional

class JobManager:
    def __init__(self):
        self._jobs: Dict[str, asyncio.Task] = {}    # key: "{project}-{step}"
        self._status: Dict[str, str] = {}           # running | done | error | stopping | stopped | cancelled
        self._logs: Dict[str, list] = {}            # buffered log lines per job
        self._stop_events: Dict[str, threading.Event] = {}
        self._stop_modes: Dict[str, str] = {}

    def key(self, project: str, step: str) -> str:
        return f"{project}-{step}"

    def is_running(self, project: str, step: str) -> bool:
        k = self.key(project, step)
        return k in self._jobs and not self._jobs[k].done()

    def set_running(self, project: str, step: str, task: asyncio.Task):
        k = self.key(project, step)
        self._jobs[k] = task
        self._status[k] = "running"
        self._logs[k] = []
        self._stop_events[k] = threading.Event()
        self._stop_modes.pop(k, None)

    def request_stop(self, project: str, step: str, mode: str = "stopped") -> bool:
        """Request cooperative stop while preserving outputs already written."""
        k = self.key(project, step)
        task = self._jobs.get(k)
        if not task or task.done():
            return False
        if mode not in ("stopped", "cancelled"):
            raise ValueError(f"Unsupported stop mode: {mode}")
        self._stop_modes[k] = mode
        self._stop_events.setdefault(k, threading.Event()).set()
        self._status[k] = "stopping"
        if mode == "cancelled":
            # Hard-cancel: the cooperative event may never be honored if the
            # executor thread is blocked in a long call (LLM request, I/O).
            # Cancelling the asyncio task guarantees the job leaves the
            # "stopping" state immediately; the cleanup thread keeps running.
            try:
                task.cancel()
            except RuntimeError:
                pass
        return True

    def should_stop(self, project: str, step: str) -> bool:
        return self._stop_events.get(self.key(project, step), threading.Event()).is_set()

    def get_stop_mode(self, project: str, step: str) -> str:
        return self._stop_modes.get(self.key(project, step), "stopped")

    def append_log(self, project: str, step: str, line: dict):
        k = self.key(project, step)
        if k not in self._logs:
            self._logs[k] = []
        self._logs[k].append(line)

    def get_logs(self, project: str, step: str) -> list:
        return self._logs.get(self.key(project, step), [])

    def set_done(self, project: str, step: str):
        self._status[self.key(project, step)] = "done"

    def set_error(self, project: str, step: str):
        self._status[self.key(project, step)] = "error"

    def set_stopped(self, project: str, step: str, mode: str = "stopped"):
        if mode not in ("stopped", "cancelled"):
            raise ValueError(f"Unsupported stop mode: {mode}")
        self._status[self.key(project, step)] = mode

    def get_status(self, project: str, step: str) -> str:
        return self._status.get(self.key(project, step), "idle")

job_manager = JobManager()  # singleton
