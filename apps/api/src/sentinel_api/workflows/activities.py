"""Activity boundaries for work execution, journal persistence, and invalidation."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from temporalio import activity

from sentinel_api.domain import WorkProduct, WorkProductKind, plan_invalidation
from sentinel_api.persistence.models import EventDraft, NewRun
from sentinel_api.persistence.protocols import EventStore
from sentinel_api.workflows.models import (
    ChildActivityInput,
    EnsureChildRun,
    InvalidationRequest,
    InvalidationResult,
    JournalEvent,
    WorkExecution,
)

EXECUTE_WORK_ACTIVITY = "sentinel.runtime.execute_work"
ENSURE_CHILD_RUN_ACTIVITY = "sentinel.runtime.ensure_child_run"
APPEND_JOURNAL_EVENT_ACTIVITY = "sentinel.runtime.append_journal_event"
PLAN_INVALIDATION_ACTIVITY = "sentinel.runtime.plan_invalidation"

WorkExecutor = Callable[[ChildActivityInput], Awaitable[WorkExecution]]


class RuntimeActivities:
    """Production activity adapter over centrally owned executor and journal contracts."""

    def __init__(self, event_store: EventStore, execute_work: WorkExecutor) -> None:
        self._event_store = event_store
        self._execute_work = execute_work

    @activity.defn(name=EXECUTE_WORK_ACTIVITY)
    async def execute_work(self, request: ChildActivityInput) -> WorkExecution:
        return await self._execute_work(request)

    @activity.defn(name=ENSURE_CHILD_RUN_ACTIVITY)
    async def ensure_child_run(self, request: EnsureChildRun) -> None:
        run_id = UUID(request.run_id)
        if await self._event_store.get_run(run_id) is not None:
            return
        await self._event_store.create_run(
            NewRun(
                run_id=run_id,
                parent_run_id=UUID(request.parent_run_id),
                request_revision_id=UUID(request.request_revision_id),
                policy_revision=request.policy_revision,
                title=request.title,
                status="queued",
            )
        )

    @activity.defn(name=APPEND_JOURNAL_EVENT_ACTIVITY)
    async def append_journal_event(self, event: JournalEvent) -> None:
        await self._event_store.append_event(
            UUID(event.run_id),
            EventDraft(
                event_type=event.event_type,
                status=event.status,
                summary=event.summary,
                payload=event.payload,
                work_item_id=UUID(event.work_item_id) if event.work_item_id else None,
                actor_id=event.actor_id,
                idempotency_key=event.idempotency_key,
            ),
        )

    @activity.defn(name=PLAN_INVALIDATION_ACTIVITY)
    async def plan_invalidation(self, request: InvalidationRequest) -> InvalidationResult:
        products = tuple(
            WorkProduct(
                id=UUID(product.product_id),
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
            retained_product_ids=tuple(str(product_id) for product_id in plan.retained_product_ids),
            invalidated_product_ids=invalidated_ids,
            invalidated_output_keys=tuple(by_id[product_id] for product_id in invalidated_ids),
        )

    def registered(self) -> list[Callable[..., Awaitable[object]]]:
        """Return bound activities suitable for ``temporalio.worker.Worker``."""

        return [
            self.execute_work,
            self.ensure_child_run,
            self.append_journal_event,
            self.plan_invalidation,
        ]
