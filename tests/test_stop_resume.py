import asyncio

from api.job_manager import JobManager


def test_stop_request_marks_running_job_and_preserves_stop_mode():
    async def running_job():
        await asyncio.sleep(10)

    async def scenario():
        manager = JobManager()
        task = asyncio.create_task(running_job())
        manager.set_running("project", "1", task)

        assert manager.request_stop("project", "1", "stopped") is True
        assert manager.should_stop("project", "1") is True
        assert manager.get_stop_mode("project", "1") == "stopped"
        assert manager.get_status("project", "1") == "stopping"

        manager.set_stopped("project", "1", "stopped")
        assert manager.get_status("project", "1") == "stopped"
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_cancel_request_uses_cancelled_terminal_status():
    async def scenario():
        manager = JobManager()
        task = asyncio.create_task(asyncio.sleep(10))
        manager.set_running("project", "6", task)

        assert manager.request_stop("project", "6", "cancelled") is True
        manager.set_stopped("project", "6", manager.get_stop_mode("project", "6"))
        assert manager.get_status("project", "6") == "cancelled"
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
