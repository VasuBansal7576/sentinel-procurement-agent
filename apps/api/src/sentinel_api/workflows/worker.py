"""Production worker bootstrap for the generic credential-free runtime."""

from __future__ import annotations

import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from sentinel_api.config import get_settings
from sentinel_api.integration.executor import CredentialFreeWorkExecutor
from sentinel_api.integration.repository import PostgresIntegrationRepository
from sentinel_api.persistence.runtime import event_store_runtime
from sentinel_api.protected_actions import PostgresApprovalBroker
from sentinel_api.workflows.activities import RuntimeActivities
from sentinel_api.workflows.child import ProcurementChildWorkflow
from sentinel_api.workflows.parent import ProcurementParentWorkflow

TASK_QUEUE = "sentinel-procurement"


async def run_worker() -> None:
    """Run the credential-free worker without model or provider credentials."""

    settings = get_settings()
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
        await worker.run()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
