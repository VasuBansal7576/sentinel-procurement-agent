"""Production worker bootstrap for the generic credential-free runtime."""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Awaitable
from contextlib import suppress
from typing import Protocol

from temporalio.client import Client
from temporalio.worker import Worker

from sentinel_api.config import get_settings
from sentinel_api.integration.demo import DemoProfile
from sentinel_api.integration.executor import CredentialFreeWorkExecutor
from sentinel_api.integration.repository import PostgresIntegrationRepository
from sentinel_api.persistence.runtime import event_store_runtime
from sentinel_api.protected_actions import PostgresApprovalBroker
from sentinel_api.workflows.activities import RuntimeActivities
from sentinel_api.workflows.child import ProcurementChildWorkflow
from sentinel_api.workflows.parent import ProcurementParentWorkflow

TASK_QUEUE = "sentinel-procurement"


class StoppableWorker(Protocol):
    async def run(self) -> None: ...

    def shutdown(self) -> Awaitable[None]: ...


async def run_until_stopped(
    worker: StoppableWorker,
    stop_event: asyncio.Event,
) -> None:
    """Run until the worker exits or an operator requests graceful shutdown."""

    worker_task = asyncio.create_task(worker.run())
    stop_task = asyncio.create_task(stop_event.wait())
    done, _ = await asyncio.wait(
        {worker_task, stop_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if stop_task in done and not worker_task.done():
        await worker.shutdown()
    stop_task.cancel()
    await asyncio.gather(stop_task, return_exceptions=True)
    await worker_task


async def run_worker() -> None:
    """Run the credential-free worker without model or provider credentials."""

    settings = get_settings()
    demo_profile = DemoProfile.from_settings(settings)
    async with event_store_runtime(
        settings.database_url,
        migrate=settings.auto_migrate,
    ) as event_store:
        records = PostgresIntegrationRepository(event_store.connection_pool)
        broker = PostgresApprovalBroker(event_store.connection_pool)
        executor = CredentialFreeWorkExecutor(
            records=records,
            event_store=event_store,
            proposal_broker=broker,
            demo_profile=demo_profile,
        )
        activities = RuntimeActivities(event_store, executor)
        client = await Client.connect(
            settings.temporal_address,
            namespace=settings.temporal_namespace,
        )
        worker = Worker(
            client,
            task_queue=TASK_QUEUE,
            workflows=[ProcurementParentWorkflow, ProcurementChildWorkflow],
            activities=activities.registered(),
        )
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        installed_signals: list[signal.Signals] = []
        for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(shutdown_signal, stop_event.set)
            except (NotImplementedError, RuntimeError):
                continue
            installed_signals.append(shutdown_signal)
        try:
            await run_until_stopped(worker, stop_event)
        finally:
            for shutdown_signal in installed_signals:
                loop.remove_signal_handler(shutdown_signal)


def main() -> None:
    with suppress(KeyboardInterrupt):
        asyncio.run(run_worker())


if __name__ == "__main__":
    main()
