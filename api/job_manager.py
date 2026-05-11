import asyncio
from typing import Dict, Optional

class JobManager:
    def __init__(self):
        self._jobs: Dict[str, asyncio.Task] = {}    # key: "{project}-{step}"
        self._status: Dict[str, str] = {}           # "running" | "done" | "error"
        self._logs: Dict[str, list] = {}            # buffered log lines per job

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

    def get_status(self, project: str, step: str) -> str:
        return self._status.get(self.key(project, step), "idle")

job_manager = JobManager()  # singleton
