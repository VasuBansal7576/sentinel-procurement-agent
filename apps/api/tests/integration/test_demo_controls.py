"""Release-readiness proof for deterministic, credential-free demo controls."""

from uuid import uuid4

import pytest
from temporalio.exceptions import ApplicationError

from sentinel_api.integration.demo import DemoProfile
from sentinel_api.integration.event_store import InMemoryEventStore
from sentinel_api.integration.executor import CredentialFreeWorkExecutor
from sentinel_api.integration.repository import InMemoryIntegrationRepository
from sentinel_api.persistence.models import NewRun
from sentinel_api.protected_actions import ApprovalBroker
from sentinel_api.workflows.models import ChildActivityInput, WorkItem


@pytest.mark.asyncio
async def test_named_failure_stops_only_first_workflow_attempt_then_recovers() -> None:
    run_id = uuid4()
    work_item_id = uuid4()
    event_store = InMemoryEventStore()
    await event_store.create_run(NewRun(run_id=run_id, title="Injected failure proof"))
    executor = CredentialFreeWorkExecutor(
        records=InMemoryIntegrationRepository(),
        event_store=event_store,
        proposal_broker=ApprovalBroker(),
        demo_profile=DemoProfile(
            enabled=True,
            failure_step="browser.navigate",
        ),
    )
    item = WorkItem(
        work_item_id=str(work_item_id),
        child_run_id=str(uuid4()),
        subagent_id="research-1",
        phase="research",
        kind="end_to_end",
        label="Research suppliers",
        goal="Exercise a deterministic browser failure",
        input_ref=f"record://{uuid4()}",
        output_keys=("evidence",),
    )

    first_attempt = ChildActivityInput(
        parent_run_id=str(run_id),
        child_run_id=item.child_run_id,
        request_revision_id=str(uuid4()),
        request_revision_number=1,
        policy_revision=1,
        attempt=1,
        work_item=item,
        messages=(),
    )
    with pytest.raises(ApplicationError, match="retry from the durable checkpoint"):
        await executor._step(first_attempt, "browser.navigate", lambda: "not called")

    second_attempt = ChildActivityInput(
        **{
            **first_attempt.__dict__,
            "attempt": 2,
        }
    )
    assert (
        await executor._step(
            second_attempt,
            "browser.navigate",
            lambda: "recovered",
        )
        == "recovered"
    )
    events = await event_store.list_events(run_id)
    assert [event.event_type for event in events].count("tool.started") == 2
    assert [event.event_type for event in events].count("tool.completed") == 1
