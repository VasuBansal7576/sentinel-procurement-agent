from uuid import uuid4

import pytest

from sentinel_api.persistence.models import EventDraft, NewRun
from sentinel_api.workflows.activities import RuntimeActivities
from sentinel_api.workflows.models import (
    EnsureChildRun,
    InvalidationRequest,
    JournalEvent,
    ProducedWork,
    WorkExecution,
)


class MemoryEventStore:
    def __init__(self) -> None:
        self.runs: dict[object, NewRun] = {}
        self.events: list[tuple[object, EventDraft]] = []

    async def get_run(self, run_id: object) -> object | None:
        return self.runs.get(run_id)

    async def create_run(self, run: NewRun) -> object:
        self.runs[run.run_id] = run
        return object()

    async def append_event(self, run_id: object, draft: EventDraft) -> object:
        self.events.append((run_id, draft))
        return object()


@pytest.mark.asyncio
async def test_runtime_activities_consume_journal_and_invalidation_contracts() -> None:
    store = MemoryEventStore()

    async def execute_work(_: object) -> WorkExecution:
        raise AssertionError("executor is not used by this test")

    activities = RuntimeActivities(store, execute_work)  # type: ignore[arg-type]
    parent_run_id = uuid4()
    child_run_id = uuid4()
    revision_id = uuid4()
    ensure = EnsureChildRun(
        run_id=str(child_run_id),
        parent_run_id=str(parent_run_id),
        request_revision_id=str(revision_id),
        policy_revision=3,
        title="Supplier verification",
    )

    await activities.ensure_child_run(ensure)
    await activities.ensure_child_run(ensure)
    await activities.append_journal_event(
        JournalEvent(
            run_id=str(child_run_id),
            event_type="run.status_changed",
            status="running",
            summary="Child started",
            payload={"status": "running"},
            idempotency_key="started",
        )
    )

    assert len(store.runs) == 1
    assert store.runs[child_run_id].parent_run_id == parent_run_id
    assert store.events[0][1].idempotency_key == "started"

    evidence = ProducedWork(
        product_id=str(uuid4()),
        output_key="evidence:supplier",
        kind="raw_evidence",
        request_revision_number=1,
        policy_revision=3,
        depends_on=("source:supplier",),
    )
    ranking = ProducedWork(
        product_id=str(uuid4()),
        output_key="ranking:shortlist",
        kind="ranking",
        request_revision_number=1,
        policy_revision=3,
        depends_on=("evidence:supplier",),
    )
    plan = await activities.plan_invalidation(
        InvalidationRequest(
            products=(ranking, evidence),
            changed_dependencies=("source:supplier",),
        )
    )

    assert plan.invalidated_product_ids == (evidence.product_id, ranking.product_id)
    assert plan.invalidated_output_keys == ("evidence:supplier", "ranking:shortlist")
    assert plan.retained_product_ids == ()
