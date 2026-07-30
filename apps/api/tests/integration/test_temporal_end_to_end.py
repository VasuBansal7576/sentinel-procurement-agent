"""Real Temporal proof using the production credential-free executor."""

from uuid import UUID, uuid4

import pytest
from temporal_support import temporal_time_skipping_env
from temporalio.worker import Worker

from sentinel_api.application.walking_skeleton import CreateRunRequest
from sentinel_api.integration.event_store import InMemoryEventStore
from sentinel_api.integration.executor import CredentialFreeWorkExecutor
from sentinel_api.integration.models import IntegrationRecord
from sentinel_api.integration.planner import deterministic_id, normalize_intake
from sentinel_api.integration.repository import InMemoryIntegrationRepository
from sentinel_api.persistence.models import NewRun
from sentinel_api.protected_actions import ApprovalBroker
from sentinel_api.workflows.activities import RuntimeActivities
from sentinel_api.workflows.child import ProcurementChildWorkflow
from sentinel_api.workflows.models import ChildActivityInput
from sentinel_api.workflows.parent import ProcurementParentWorkflow
from sentinel_api.workflows.runtime import start_procurement_run


@pytest.mark.asyncio
async def test_production_executor_crosses_real_parent_and_child_workflows() -> None:
    async with temporal_time_skipping_env() as environment:
        event_store = InMemoryEventStore()
        records = InMemoryIntegrationRepository()
        broker = ApprovalBroker()
        executor = CredentialFreeWorkExecutor(
            records=records,
            event_store=event_store,
            proposal_broker=broker,
        )
        activities = RuntimeActivities(event_store, executor)
        _, revision, runtime_input, request_record = normalize_intake(
            CreateRunRequest(
                title="Source recurring safety eyewear",
                item_name="Protective eyewear",
                description="Recurring anti-fog eye protection",
                quantity="600",
                unit="each",
            )
        )
        await event_store.create_run(
            NewRun(
                run_id=request_record.run_id,
                request_revision_id=revision.id,
                policy_revision=1,
                title=runtime_input.title,
                status="queued",
            )
        )
        await records.put(request_record)
        task_queue = f"integration-{uuid4()}"

        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[ProcurementParentWorkflow, ProcurementChildWorkflow],
            activities=activities.registered(),
        ):
            handle = await start_procurement_run(
                environment.client,
                runtime_input,
                task_queue=task_queue,
            )
            result = await handle.result()

        events = await event_store.list_events(request_record.run_id)
        tool_events = [event for event in events if event.event_type.startswith("tool.")]
        assert result.status.value == "completed"
        assert len(tool_events) == 60
        assert len(await records.list(request_record.run_id, record_kind="evidence")) == 1
        assert len(await records.list(request_record.run_id, record_kind="artifact")) == 4


@pytest.mark.asyncio
async def test_executor_loads_the_exact_redirected_request_revision() -> None:
    event_store = InMemoryEventStore()
    records = InMemoryIntegrationRepository()
    broker = ApprovalBroker()
    executor = CredentialFreeWorkExecutor(
        records=records,
        event_store=event_store,
        proposal_broker=broker,
    )
    _, revision, runtime_input, request_record = normalize_intake(
        CreateRunRequest(
            title="Revise calibration scope",
            item_name="Calibration service",
            description="Initial annual calibration scope",
            quantity="12",
            unit="instrument",
        )
    )
    await event_store.create_run(
        NewRun(
            run_id=request_record.run_id,
            request_revision_id=revision.id,
            policy_revision=1,
            title=runtime_input.title,
            status="running",
        )
    )
    await records.put(request_record)
    redirected_id = deterministic_id(request_record.run_id, "request-revision:2")
    redirected = revision.model_copy(
        update={
            "id": redirected_id,
            "revision_number": 2,
            "previous_revision_id": revision.id,
            "reason": "Require an accelerated service window",
        }
    )
    await records.put(
        IntegrationRecord(
            run_id=request_record.run_id,
            record_ref=uuid4(),
            record_kind="request_revision_prepared",
            payload={
                **request_record.payload,
                "revision": redirected.model_dump(mode="json"),
            },
            version=2,
        )
    )

    await executor(
        ChildActivityInput(
            parent_run_id=str(request_record.run_id),
            child_run_id=runtime_input.work_items[0].child_run_id,
            request_revision_id=str(redirected_id),
            request_revision_number=2,
            policy_revision=1,
            attempt=2,
            work_item=runtime_input.work_items[0],
            messages=(),
        )
    )

    proposal_refs = await records.list(
        request_record.run_id,
        record_kind="proposal_ref",
    )
    proposal = broker.get_proposal(UUID(str(proposal_refs[-1].payload["proposal_id"])))
    assert proposal.request_revision_id == redirected_id
