import asyncio
from collections import Counter
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from temporalio import activity
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from sentinel_api.domain import WorkProduct, WorkProductKind, plan_invalidation
from sentinel_api.workflows.activities import (
    APPEND_JOURNAL_EVENT_ACTIVITY,
    ENSURE_CHILD_RUN_ACTIVITY,
    EXECUTE_WORK_ACTIVITY,
    PLAN_INVALIDATION_ACTIVITY,
)
from sentinel_api.workflows.child import ProcurementChildWorkflow
from sentinel_api.workflows.models import (
    ActivityRetry,
    ChildActivityInput,
    ChildResultStatus,
    CommandKind,
    EnsureChildRun,
    InvalidationRequest,
    InvalidationResult,
    JournalEvent,
    MessageStatus,
    PauseCommand,
    ProcurementRunInput,
    ProducedWork,
    QueueMessageCommand,
    RedirectCommand,
    ResumeCommand,
    RetryWorkCommand,
    RunResultStatus,
    WorkExecution,
    WorkflowSnapshot,
    WorkItem,
    WorkStatus,
)
from sentinel_api.workflows.parent import ProcurementParentWorkflow
from sentinel_api.workflows.runtime import parent_workflow_id, start_procurement_run


class FakeRuntimeActivities:
    """Credential-free activities with gates for control and recovery semantics."""

    def __init__(self) -> None:
        self.events: list[JournalEvent] = []
        self.child_runs: set[str] = set()
        self.executions: list[ChildActivityInput] = []
        self.attempts: Counter[str] = Counter()
        self.block_started = asyncio.Event()
        self.cancelled = asyncio.Event()

    @activity.defn(name=EXECUTE_WORK_ACTIVITY)
    async def execute_work(self, request: ChildActivityInput) -> WorkExecution:
        input_ref = request.work_item.input_ref
        self.attempts[input_ref] += 1
        execution_count = self.attempts[input_ref]
        self.executions.append(request)
        if input_ref == "transient-once" and execution_count == 1:
            raise ApplicationError("temporary supplier outage", type="transient")
        if input_ref == "recoverable-exhausted" and request.attempt == 1:
            raise ApplicationError("supplier source is temporarily unavailable", type="transient")
        if input_ref == "terminal":
            raise ApplicationError(
                "supplier source is permanently unavailable",
                type="terminal",
                non_retryable=True,
            )
        if input_ref in {"block-once", "block-always"} and (
            input_ref == "block-always" or execution_count == 1
        ):
            self.block_started.set()
            try:
                while True:
                    activity.heartbeat("waiting for credential-free test gate")
                    await asyncio.sleep(0.02)
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
        products = tuple(
            ProducedWork(
                product_id=str(
                    uuid5(
                        NAMESPACE_URL,
                        (
                            f"{request.work_item.work_item_id}:"
                            f"{output_key}:{request.request_revision_number}"
                        ),
                    )
                ),
                output_key=output_key,
                kind=WorkProductKind.EVALUATION.value,
                request_revision_number=request.request_revision_number,
                policy_revision=request.policy_revision,
                depends_on=request.work_item.depends_on,
            )
            for output_key in request.work_item.output_keys
        )
        return WorkExecution(
            summary=f"Completed {request.work_item.label}",
            output_ref=f"memory://{request.work_item.work_item_id}/{request.attempt}",
            products=products,
        )

    @activity.defn(name=ENSURE_CHILD_RUN_ACTIVITY)
    async def ensure_child_run(self, request: EnsureChildRun) -> None:
        self.child_runs.add(request.run_id)

    @activity.defn(name=APPEND_JOURNAL_EVENT_ACTIVITY)
    async def append_journal_event(self, event: JournalEvent) -> None:
        self.events.append(event)

    @activity.defn(name=PLAN_INVALIDATION_ACTIVITY)
    async def compute_invalidation(
        self,
        request: InvalidationRequest,
    ) -> InvalidationResult:
        products = tuple(
            WorkProduct(
                id=product.product_id,
                kind=WorkProductKind(product.kind),
                output_key=product.output_key,
                request_revision_number=product.request_revision_number,
                policy_revision=product.policy_revision,
                depends_on=frozenset(product.depends_on),
            )
            for product in request.products
        )
        plan = plan_invalidation(products, frozenset(request.changed_dependencies))
        by_id = {str(product.id): product.output_key for product in products}
        invalidated_ids = tuple(str(item.product_id) for item in plan.invalidated)
        return InvalidationResult(
            retained_product_ids=tuple(str(item) for item in plan.retained_product_ids),
            invalidated_product_ids=invalidated_ids,
            invalidated_output_keys=tuple(by_id[item] for item in invalidated_ids),
        )

    def registered(self) -> list[object]:
        return [
            self.execute_work,
            self.ensure_child_run,
            self.append_journal_event,
            self.compute_invalidation,
        ]


def make_item(
    label: str,
    input_ref: str,
    output_key: str,
    *,
    depends_on: tuple[str, ...] = (),
    position: int = 0,
) -> WorkItem:
    return WorkItem(
        work_item_id=str(uuid4()),
        child_run_id=str(uuid4()),
        subagent_id=str(uuid4()),
        phase="research",
        kind="supplier_research",
        label=label,
        goal=f"Research {label}",
        input_ref=input_ref,
        output_keys=(output_key,),
        depends_on=depends_on,
        tool_scope=("search.query", "browser.read"),
        position=position,
        timeout_seconds=30,
        retry=ActivityRetry(
            maximum_attempts=3,
            initial_interval_seconds=0.01,
            maximum_interval_seconds=0.05,
        ),
    )


def make_run(*items: WorkItem, max_concurrency: int = 3) -> ProcurementRunInput:
    return ProcurementRunInput(
        run_id=str(uuid4()),
        request_revision_id=str(uuid4()),
        request_revision_number=1,
        policy_revision=1,
        title="Credential-free procurement runtime test",
        work_items=items,
        max_concurrency=max_concurrency,
    )


def make_worker(
    environment: WorkflowEnvironment,
    task_queue: str,
    fake: FakeRuntimeActivities,
) -> Worker:
    return Worker(
        environment.client,
        task_queue=task_queue,
        workflows=[ProcurementParentWorkflow, ProcurementChildWorkflow],
        activities=fake.registered(),  # type: ignore[arg-type]
        max_cached_workflows=0,
    )


async def wait_for_state(
    handle: object,
    predicate: object,
    *,
    timeout: float = 10,
) -> WorkflowSnapshot:
    snapshot: WorkflowSnapshot | None = None
    try:
        async with asyncio.timeout(timeout):
            while True:
                snapshot = await handle.query(  # type: ignore[attr-defined]
                    ProcurementParentWorkflow.state,
                    result_type=WorkflowSnapshot,
                )
                if predicate(snapshot):  # type: ignore[operator]
                    return snapshot
                await asyncio.sleep(0.02)
    except TimeoutError as error:
        detail = f"workflow state did not converge; last state: {snapshot!r}"
        raise AssertionError(detail) from error


@pytest.mark.asyncio
async def test_children_retry_fail_independently_and_replay() -> None:
    async with await WorkflowEnvironment.start_time_skipping(
        download_dest_dir="/tmp/sentinel-temporal-test-server"
    ) as environment:
        fake = FakeRuntimeActivities()
        task_queue = f"runtime-{uuid4()}"
        transient = make_item("Transient source", "transient-once", "evaluation:transient")
        terminal = make_item("Terminal source", "terminal", "evaluation:terminal")
        request = make_run(transient, terminal)
        workflow_id = parent_workflow_id(request.run_id)

        async with make_worker(environment, task_queue, fake):
            handle = await start_procurement_run(
                environment.client,
                request,
                task_queue=task_queue,
            )
            result = await handle.result()
            with pytest.raises(WorkflowAlreadyStartedError):
                await start_procurement_run(
                    environment.client,
                    request,
                    task_queue=task_queue,
                )
            parent_history = await handle.fetch_history()
            child_histories = [
                await environment.client.get_workflow_handle(
                    f"{workflow_id}:child:{item.work_item_id}:attempt:1"
                ).fetch_history()
                for item in request.work_items
            ]

        assert result.status is RunResultStatus.COMPLETED_WITH_FAILURES
        assert fake.attempts["transient-once"] == 2
        assert fake.attempts["terminal"] == 1
        assert result.children[0].output_ref is not None
        assert result.children[1].failure is not None
        assert result.children[1].failure.classification.value == "terminal"
        assert len(fake.child_runs) == 2
        assert (
            sum(
                event.event_type == EventType.EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED
                for event in parent_history.events
            )
            == 2
        )

        replayer = Replayer(workflows=[ProcurementParentWorkflow, ProcurementChildWorkflow])
        await replayer.replay_workflow(parent_history)
        for history in child_histories:
            await replayer.replay_workflow(history)


@pytest.mark.asyncio
async def test_exhausted_retryable_child_waits_for_targeted_operator_retry() -> None:
    async with await WorkflowEnvironment.start_time_skipping(
        download_dest_dir="/tmp/sentinel-temporal-test-server"
    ) as environment:
        fake = FakeRuntimeActivities()
        task_queue = f"recoverable-{uuid4()}"
        recoverable = make_item(
            "Recoverable supplier source",
            "recoverable-exhausted",
            "evidence:recoverable",
        )
        request = make_run(recoverable, max_concurrency=1)
        workflow_id = parent_workflow_id(request.run_id)

        async with make_worker(environment, task_queue, fake):
            handle = await start_procurement_run(
                environment.client,
                request,
                task_queue=task_queue,
            )
            blocked = await wait_for_state(
                handle,
                lambda state: (
                    state.work[0].status is WorkStatus.FAILED
                    and state.work[0].failure is not None
                    and state.work[0].failure.retryable
                ),
            )
            async with asyncio.timeout(10):
                while not any(
                    event.event_type == "run.recovery_available" for event in fake.events
                ):
                    await asyncio.sleep(0.02)
            retry = RetryWorkCommand(
                command_id="command-retry-1",
                work_item_id=recoverable.work_item_id,
                expected_attempt=blocked.work[0].attempt,
                reason="Operator retried from the failed supplier checkpoint",
            )
            retry_ack = await handle.execute_update(
                ProcurementParentWorkflow.retry_work,
                retry,
            )
            duplicate_ack = await handle.execute_update(
                ProcurementParentWorkflow.retry_work,
                retry,
            )
            result = await handle.result()
            history = await handle.fetch_history()
            child_histories = [
                await environment.client.get_workflow_handle(
                    f"{workflow_id}:child:{recoverable.work_item_id}:attempt:{attempt}"
                ).fetch_history()
                for attempt in (1, 2)
            ]

        assert retry_ack.kind is CommandKind.RETRY_WORK
        assert duplicate_ack == retry_ack
        assert result.status is RunResultStatus.COMPLETED
        assert result.children[0].attempt == 2
        assert fake.attempts["recoverable-exhausted"] == 4
        assert any(event.event_type == "run.recovery_available" for event in fake.events)
        assert any(event.event_type == "work.retry_requested" for event in fake.events)

        replayer = Replayer(workflows=[ProcurementParentWorkflow, ProcurementChildWorkflow])
        await replayer.replay_workflow(history)
        for child_history in child_histories:
            await replayer.replay_workflow(child_history)


@pytest.mark.asyncio
async def test_updates_selectively_invalidate_and_survive_worker_restart() -> None:
    async with await WorkflowEnvironment.start_time_skipping(
        download_dest_dir="/tmp/sentinel-temporal-test-server"
    ) as environment:
        fake = FakeRuntimeActivities()
        task_queue = f"control-{uuid4()}"
        invalidated = make_item(
            "Rank suppliers",
            "ranking",
            "ranking:shortlist",
            depends_on=("request:budget",),
            position=1,
        )
        retained = make_item(
            "Capture source",
            "source",
            "evidence:source",
            depends_on=("source:url",),
            position=2,
        )
        interrupted = make_item(
            "Verify supplier",
            "block-once",
            "evaluation:verification",
            depends_on=("source:url",),
            position=3,
        )
        request = make_run(
            invalidated,
            retained,
            interrupted,
            max_concurrency=1,
        )
        workflow_id = f"procurement-{request.run_id}"

        async with make_worker(environment, task_queue, fake):
            handle = await environment.client.start_workflow(
                ProcurementParentWorkflow.run,
                request,
                id=workflow_id,
                task_queue=task_queue,
            )
            await fake.block_started.wait()
            await wait_for_state(
                handle,
                lambda state: (
                    state.work[0].status is WorkStatus.COMPLETED
                    and state.work[1].status is WorkStatus.COMPLETED
                    and state.work[2].status is WorkStatus.RUNNING
                ),
            )
            message_ack = await handle.execute_update(
                ProcurementParentWorkflow.queue_message,
                QueueMessageCommand(
                    command_id="command-message-1",
                    message_id="message-1",
                    body="Prefer suppliers with local service coverage",
                ),
            )
            duplicate_message_ack = await handle.execute_update(
                ProcurementParentWorkflow.queue_message,
                QueueMessageCommand(
                    command_id="command-message-1",
                    message_id="message-1",
                    body="Prefer suppliers with local service coverage",
                ),
            )
            pause_ack = await handle.execute_update(
                ProcurementParentWorkflow.pause,
                PauseCommand(
                    command_id="command-pause-1",
                    reason="Operator is revising the budget",
                ),
            )
            await fake.cancelled.wait()
            await wait_for_state(
                handle,
                lambda state: (
                    state.paused
                    and state.messages[0].status is MessageStatus.APPLIED
                    and state.work[2].status is WorkStatus.PENDING
                ),
            )
            redirect_ack = await handle.execute_update(
                ProcurementParentWorkflow.redirect,
                RedirectCommand(
                    command_id="command-redirect-1",
                    request_revision_id=str(uuid4()),
                    request_revision_number=2,
                    changed_dependencies=("request:budget",),
                    reason="Budget ceiling changed",
                ),
            )
            paused = await wait_for_state(
                handle,
                lambda state: (
                    state.paused
                    and state.request_revision_number == 2
                    and state.messages[0].status is MessageStatus.APPLIED
                    and state.work[0].status is WorkStatus.PENDING
                    and state.work[1].status is WorkStatus.COMPLETED
                    and state.work[2].status is WorkStatus.PENDING
                ),
            )

        assert [message_ack.kind, pause_ack.kind, redirect_ack.kind] == [
            CommandKind.QUEUE_MESSAGE,
            CommandKind.PAUSE,
            CommandKind.REDIRECT,
        ]
        assert duplicate_message_ack == message_ack
        assert [message_ack.sequence, pause_ack.sequence, redirect_ack.sequence] == [
            1,
            2,
            3,
        ]
        assert paused.work[1].attempt == 1

        async with make_worker(environment, task_queue, fake):
            recovered = await handle.query(
                ProcurementParentWorkflow.state,
                result_type=WorkflowSnapshot,
            )
            assert recovered.paused
            assert recovered.command_sequence == 3
            resume_ack = await handle.execute_update(
                ProcurementParentWorkflow.resume,
                ResumeCommand(command_id="command-resume-1"),
            )
            result = await handle.result()
            history = await handle.fetch_history()

        assert resume_ack.sequence == 4
        assert result.status is RunResultStatus.COMPLETED
        assert fake.attempts["ranking"] == 2
        assert fake.attempts["source"] == 1
        assert fake.attempts["block-once"] == 2
        assert result.request_revision_number == 2
        assert result.messages[0].status is MessageStatus.APPLIED
        rerun_executions = [
            execution for execution in fake.executions if execution.request_revision_number == 2
        ]
        assert rerun_executions
        assert all(
            execution.messages[0].message_id == "message-1" for execution in rerun_executions
        )
        assert any(event.event_type == "work.invalidated" for event in fake.events)
        await Replayer(
            workflows=[ProcurementParentWorkflow, ProcurementChildWorkflow]
        ).replay_workflow(history)


@pytest.mark.asyncio
async def test_parent_cancellation_reaches_active_child_activity() -> None:
    async with await WorkflowEnvironment.start_time_skipping(
        download_dest_dir="/tmp/sentinel-temporal-test-server"
    ) as environment:
        fake = FakeRuntimeActivities()
        task_queue = f"cancel-{uuid4()}"
        blocked = make_item(
            "Long-running browser task",
            "block-always",
            "evidence:browser",
        )
        request = make_run(blocked, max_concurrency=1)
        workflow_id = f"procurement-{request.run_id}"
        child_workflow_id = f"{workflow_id}:child:{blocked.work_item_id}:attempt:1"

        async with make_worker(environment, task_queue, fake):
            handle = await environment.client.start_workflow(
                ProcurementParentWorkflow.run,
                request,
                id=workflow_id,
                task_queue=task_queue,
            )
            await fake.block_started.wait()
            await handle.cancel()
            with pytest.raises(WorkflowFailureError):
                await handle.result()
            parent_history = await handle.fetch_history()
            child_handle = environment.client.get_workflow_handle_for(
                ProcurementChildWorkflow.run,
                child_workflow_id,
            )
            child_history = await child_handle.fetch_history()
            child_result = await child_handle.result()

        assert fake.attempts["block-always"] == 1
        assert any(
            event.event_type == EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED
            for event in parent_history.events
        )
        assert (
            child_history.events[-1].event_type == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED
        )
        assert child_result.status is ChildResultStatus.CANCELLED
