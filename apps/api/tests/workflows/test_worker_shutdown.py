"""Worker process lifecycle tests that do not require a Temporal server."""

import asyncio

import pytest

from sentinel_api.workflows.worker import run_until_stopped


class RecordingWorker:
    def __init__(self) -> None:
        self.running = asyncio.Event()
        self.released = asyncio.Event()
        self.shutdown_calls = 0

    async def run(self) -> None:
        self.running.set()
        await self.released.wait()

    async def shutdown(self) -> None:
        self.shutdown_calls += 1
        self.released.set()


@pytest.mark.asyncio
async def test_stop_request_gracefully_drains_worker_without_cancellation_traceback() -> None:
    worker = RecordingWorker()
    stop_event = asyncio.Event()
    task = asyncio.create_task(run_until_stopped(worker, stop_event))
    await worker.running.wait()

    stop_event.set()
    await task

    assert worker.shutdown_calls == 1
