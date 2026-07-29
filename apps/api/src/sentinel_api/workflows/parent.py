"""Deterministic parent workflow coordinating durable procurement children."""

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.workflow import ChildWorkflowCancellationType

with workflow.unsafe.imports_passed_through():
    from .activities import (
        APPEND_JOURNAL_EVENT_ACTIVITY,
        ENSURE_CHILD_RUN_ACTIVITY,
        PLAN_INVALIDATION_ACTIVITY,
    )
    from .child import ProcurementChildWorkflow
    from .models import (
        ChildActivityInput,
        ChildResult,
        ChildResultStatus,
        ChildWorkflowInput,
        CommandAck,
        CommandKind,
        EnsureChildRun,
        InvalidationRequest,
        InvalidationResult,
        JournalEvent,
        MessageStatus,
        PauseCommand,
        ProcurementRunInput,
        ProcurementRunResult,
        QueuedMessage,
        QueueMessageCommand,
        RedirectCommand,
        ResumeCommand,
        RunResultStatus,
        WorkflowSnapshot,
        WorkState,
        WorkStatus,
    )


@dataclass(frozen=True)
class _AcceptedCommand:
    sequence: int
    command_id: str
    kind: CommandKind
    value: PauseCommand | ResumeCommand | RedirectCommand | QueueMessageCommand


_JOURNAL_RETRY = RetryPolicy(
    maximum_attempts=10,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=30),
)


@workflow.defn(name="sentinel.procurement.parent")
class ProcurementParentWorkflow:
    """One durable parent per procurement run, with acknowledged operator control."""

    @workflow.init
    def __init__(self, request: ProcurementRunInput) -> None:
        if not request.work_items:
            raise ValueError("a procurement run requires at least one work item")
        if request.max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self._request = request
        self._request_revision_id = request.request_revision_id
        self._request_revision_number = request.request_revision_number
        self._accepted_revision_number = request.request_revision_number
        self._paused = False
        self._command_sequence = 0
        self._processed_command_sequence = 0
        self._commands: list[_AcceptedCommand] = []
        self._acks: dict[str, CommandAck] = {}
        self._messages: list[QueuedMessage] = []
        self._states = {
            item.work_item_id: WorkState(
                work_item_id=item.work_item_id,
                status=WorkStatus.PENDING,
                attempt=0,
                request_revision_number=request.request_revision_number,
            )
            for item in request.work_items
        }
        if len(self._states) != len(request.work_items):
            raise ValueError("work_item_id values must be unique")
        self._items = {item.work_item_id: item for item in request.work_items}
        self._results: dict[str, ChildResult] = {}
        self._active: dict[str, asyncio.Task[ChildResult]] = {}
        self._cancel_reasons: dict[str, str] = {}

    @workflow.run
    async def run(self, request: ProcurementRunInput) -> ProcurementRunResult:
        del request
        await self._journal(
            JournalEvent(
                run_id=self._request.run_id,
                event_type="run.status_changed",
                status="running",
                summary="Temporal procurement workflow started",
                payload={
                    "status": "running",
                    "active_phase": "research",
                    "started_at": workflow.now().isoformat(),
                },
                idempotency_key="workflow.started",
            )
        )
        try:
            while True:
                await self._drain_commands()
                if self._active:
                    done, _ = await workflow.wait(
                        tuple(self._active.values()),
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for handle in done:
                        await self._finish_child(handle)
                    continue
                if self._paused:
                    await workflow.wait_condition(
                        lambda: not self._paused or self._has_unprocessed_commands()
                    )
                    continue
                pending = [
                    item_id
                    for item_id, state in self._states.items()
                    if state.status is WorkStatus.PENDING
                ]
                if not pending:
                    break
                for item_id in pending[: self._request.max_concurrency]:
                    if self._paused or self._has_unprocessed_commands():
                        break
                    await self._start_child(item_id)
        except asyncio.CancelledError:
            for item_id, handle in tuple(self._active.items()):
                self._cancel_reasons[item_id] = "parent_cancelled"
                handle.cancel()
            if self._active:
                await asyncio.gather(*self._active.values(), return_exceptions=True)
            raise

        failures = tuple(
            result for result in self._results.values() if result.status is ChildResultStatus.FAILED
        )
        status = RunResultStatus.COMPLETED_WITH_FAILURES if failures else RunResultStatus.COMPLETED
        await self._journal(
            JournalEvent(
                run_id=self._request.run_id,
                event_type="run.status_changed",
                status=status.value,
                summary=(
                    f"Completed with {len(failures)} failed child workflows"
                    if failures
                    else "All child workflows completed"
                ),
                payload={
                    "status": status.value,
                    "active_phase": "complete",
                    "completed_at": workflow.now().isoformat(),
                },
                idempotency_key="workflow.completed",
            )
        )
        await workflow.wait_condition(workflow.all_handlers_finished)
        return ProcurementRunResult(
            run_id=self._request.run_id,
            status=status,
            request_revision_id=self._request_revision_id,
            request_revision_number=self._request_revision_number,
            children=tuple(
                self._results[item.work_item_id]
                for item in self._request.work_items
                if item.work_item_id in self._results
            ),
            messages=tuple(self._messages),
        )

    @workflow.update
    def pause(self, command: PauseCommand) -> CommandAck:
        existing = self._acks.get(command.command_id)
        if existing is not None:
            return existing
        ack = self._accept(command.command_id, CommandKind.PAUSE, command)
        self._paused = True
        self._cancel_active("pause", cancellable_only=True)
        return ack

    @pause.validator
    def validate_pause(self, command: PauseCommand) -> None:
        self._validate_command_id(command.command_id)
        if self._is_duplicate(command.command_id, CommandKind.PAUSE, command):
            return
        if not command.reason.strip():
            raise ValueError("pause reason must not be blank")

    @workflow.update
    def resume(self, command: ResumeCommand) -> CommandAck:
        existing = self._acks.get(command.command_id)
        if existing is not None:
            return existing
        ack = self._accept(command.command_id, CommandKind.RESUME, command)
        self._paused = False
        return ack

    @resume.validator
    def validate_resume(self, command: ResumeCommand) -> None:
        self._validate_command_id(command.command_id)
        if self._is_duplicate(command.command_id, CommandKind.RESUME, command):
            return
        if not command.reason.strip():
            raise ValueError("resume reason must not be blank")

    @workflow.update
    def redirect(self, command: RedirectCommand) -> CommandAck:
        existing = self._acks.get(command.command_id)
        if existing is not None:
            return existing
        ack = self._accept(command.command_id, CommandKind.REDIRECT, command)
        self._accepted_revision_number = command.request_revision_number
        self._cancel_active("redirect", cancellable_only=True)
        return ack

    @redirect.validator
    def validate_redirect(self, command: RedirectCommand) -> None:
        self._validate_command_id(command.command_id)
        if self._is_duplicate(command.command_id, CommandKind.REDIRECT, command):
            return
        if command.request_revision_number <= self._accepted_revision_number:
            raise ValueError("redirect revision must increase monotonically")
        if not command.request_revision_id.strip():
            raise ValueError("redirect request_revision_id must not be blank")
        if not command.changed_dependencies:
            raise ValueError("redirect must name at least one changed dependency")
        if not command.reason.strip():
            raise ValueError("redirect reason must not be blank")

    @workflow.update
    def queue_message(self, command: QueueMessageCommand) -> CommandAck:
        existing = self._acks.get(command.command_id)
        if existing is not None:
            return existing
        ack = self._accept(command.command_id, CommandKind.QUEUE_MESSAGE, command)
        self._messages.append(
            QueuedMessage(
                message_id=command.message_id,
                sequence=ack.sequence,
                body=command.body,
                status=MessageStatus.QUEUED,
            )
        )
        return ack

    @queue_message.validator
    def validate_queue_message(self, command: QueueMessageCommand) -> None:
        self._validate_command_id(command.command_id)
        if self._is_duplicate(command.command_id, CommandKind.QUEUE_MESSAGE, command):
            return
        if not command.message_id.strip():
            raise ValueError("message_id must not be blank")
        if not command.body.strip():
            raise ValueError("message body must not be blank")
        if any(message.message_id == command.message_id for message in self._messages):
            raise ValueError("message_id must be unique")

    @workflow.query
    def state(self) -> WorkflowSnapshot:
        return WorkflowSnapshot(
            run_id=self._request.run_id,
            paused=self._paused,
            request_revision_id=self._request_revision_id,
            request_revision_number=self._request_revision_number,
            command_sequence=self._command_sequence,
            work=tuple(self._states[item.work_item_id] for item in self._request.work_items),
            messages=tuple(self._messages),
            acknowledgements=tuple(
                sorted(self._acks.values(), key=lambda acknowledgement: acknowledgement.sequence)
            ),
        )

    @staticmethod
    def _validate_command_id(command_id: str) -> None:
        if not command_id.strip():
            raise ValueError("command_id must not be blank")

    def _is_duplicate(
        self,
        command_id: str,
        kind: CommandKind,
        value: PauseCommand | ResumeCommand | RedirectCommand | QueueMessageCommand,
    ) -> bool:
        existing = self._acks.get(command_id)
        if existing is None:
            return False
        if existing.kind is not kind:
            raise ValueError("command_id cannot be reused for another command kind")
        accepted = next(command for command in self._commands if command.command_id == command_id)
        if accepted.value != value:
            raise ValueError("command_id cannot be reused with a different payload")
        return True

    def _accept(
        self,
        command_id: str,
        kind: CommandKind,
        value: PauseCommand | ResumeCommand | RedirectCommand | QueueMessageCommand,
    ) -> CommandAck:
        self._command_sequence += 1
        ack = CommandAck(
            command_id=command_id,
            kind=kind,
            sequence=self._command_sequence,
            accepted=True,
            detail=f"{kind.value} accepted for durable application",
        )
        self._acks[command_id] = ack
        self._commands.append(
            _AcceptedCommand(
                sequence=ack.sequence,
                command_id=command_id,
                kind=kind,
                value=value,
            )
        )
        return ack

    def _cancel_active(self, reason: str, *, cancellable_only: bool) -> None:
        for item_id, handle in tuple(self._active.items()):
            if cancellable_only and not self._items[item_id].cancellable:
                continue
            self._cancel_reasons[item_id] = reason
            handle.cancel()

    def _has_unprocessed_commands(self) -> bool:
        return self._processed_command_sequence < self._command_sequence

    async def _drain_commands(self) -> None:
        for command in self._commands:
            if command.sequence <= self._processed_command_sequence:
                continue
            await self._journal(
                JournalEvent(
                    run_id=self._request.run_id,
                    event_type="operator.command_accepted",
                    status="acknowledged",
                    summary=f"Accepted operator command: {command.kind.value}",
                    payload={
                        "command_id": command.command_id,
                        "command": command.kind.value,
                        "sequence": command.sequence,
                    },
                    actor_id="operator",
                    idempotency_key=f"command:{command.command_id}:accepted",
                )
            )
            if command.kind is CommandKind.PAUSE:
                pause = command.value
                assert isinstance(pause, PauseCommand)
                await self._record_run_control(
                    command,
                    status="paused",
                    summary=pause.reason,
                )
            elif command.kind is CommandKind.RESUME:
                resume = command.value
                assert isinstance(resume, ResumeCommand)
                await self._record_run_control(
                    command,
                    status="running",
                    summary=resume.reason,
                )
            elif command.kind is CommandKind.QUEUE_MESSAGE:
                queued = command.value
                assert isinstance(queued, QueueMessageCommand)
                await self._apply_message(queued, command.sequence)
            elif command.kind is CommandKind.REDIRECT:
                redirect = command.value
                assert isinstance(redirect, RedirectCommand)
                await self._apply_redirect(redirect)
            self._processed_command_sequence = command.sequence

    async def _record_run_control(
        self,
        command: _AcceptedCommand,
        *,
        status: str,
        summary: str,
    ) -> None:
        await self._journal(
            JournalEvent(
                run_id=self._request.run_id,
                event_type="run.status_changed",
                status=status,
                summary=summary,
                payload={"status": status, "summary": summary},
                actor_id="operator",
                idempotency_key=f"command:{command.command_id}:applied",
            )
        )

    async def _apply_message(self, command: QueueMessageCommand, sequence: int) -> None:
        self._messages = [
            QueuedMessage(
                message_id=message.message_id,
                sequence=message.sequence,
                body=message.body,
                status=(
                    MessageStatus.APPLIED
                    if message.message_id == command.message_id
                    else message.status
                ),
            )
            for message in self._messages
        ]
        await self._journal(
            JournalEvent(
                run_id=self._request.run_id,
                event_type="operator.message_applied",
                status="applied",
                summary="Applied queued operator message",
                payload={
                    "message_id": command.message_id,
                    "sequence": sequence,
                    "body": command.body,
                },
                actor_id="operator",
                idempotency_key=f"message:{command.message_id}:applied",
            )
        )

    async def _apply_redirect(self, command: RedirectCommand) -> None:
        products = tuple(
            product for result in self._results.values() for product in result.products
        )
        invalidation = await workflow.execute_activity(
            PLAN_INVALIDATION_ACTIVITY,
            InvalidationRequest(
                products=products,
                changed_dependencies=command.changed_dependencies,
            ),
            result_type=InvalidationResult,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_JOURNAL_RETRY,
        )
        invalidated_ids = set(invalidation.invalidated_product_ids)
        for item_id, result in tuple(self._results.items()):
            if any(product.product_id in invalidated_ids for product in result.products):
                previous = self._states[item_id]
                self._states[item_id] = WorkState(
                    work_item_id=item_id,
                    status=WorkStatus.PENDING,
                    attempt=previous.attempt,
                    request_revision_number=command.request_revision_number,
                )
                del self._results[item_id]
                await self._journal(
                    JournalEvent(
                        run_id=self._request.run_id,
                        event_type="work.invalidated",
                        status="queued",
                        summary=f"Invalidated {self._items[item_id].label}",
                        payload={
                            "status": "queued",
                            "invalidated_output_keys": list(invalidation.invalidated_output_keys),
                        },
                        work_item_id=item_id,
                        idempotency_key=(
                            f"redirect:{command.request_revision_number}:work:{item_id}"
                        ),
                    )
                )
        self._request_revision_id = command.request_revision_id
        self._request_revision_number = command.request_revision_number
        await self._journal(
            JournalEvent(
                run_id=self._request.run_id,
                event_type="run.redirected",
                status="running",
                summary=command.reason,
                payload={
                    "request_revision_id": command.request_revision_id,
                    "request_revision_number": command.request_revision_number,
                    "changed_dependencies": list(command.changed_dependencies),
                    "retained_product_ids": list(invalidation.retained_product_ids),
                    "invalidated_product_ids": list(invalidation.invalidated_product_ids),
                },
                actor_id="operator",
                idempotency_key=f"redirect:{command.request_revision_number}",
            )
        )

    async def _start_child(self, item_id: str) -> None:
        item = self._items[item_id]
        state = self._states[item_id]
        await workflow.execute_activity(
            ENSURE_CHILD_RUN_ACTIVITY,
            EnsureChildRun(
                run_id=item.child_run_id,
                parent_run_id=self._request.run_id,
                request_revision_id=self._request_revision_id,
                policy_revision=self._request.policy_revision,
                title=item.label,
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_JOURNAL_RETRY,
        )
        if self._paused or self._has_unprocessed_commands():
            return
        attempt = state.attempt + 1
        started_at = workflow.now().isoformat()
        await self._journal(
            JournalEvent(
                run_id=self._request.run_id,
                event_type="work.started",
                status="running",
                summary=f"Started {item.label}",
                payload={
                    "phase": item.phase,
                    "kind": item.kind,
                    "label": item.label,
                    "status": "running",
                    "position": item.position,
                    "subagent_id": item.subagent_id,
                },
                work_item_id=item.work_item_id,
                idempotency_key=f"work:{item.work_item_id}:attempt:{attempt}:started",
            )
        )
        await self._journal(
            JournalEvent(
                run_id=self._request.run_id,
                event_type="subagent.started",
                status="running",
                summary=f"Started child workflow for {item.label}",
                payload={
                    "subagent_id": item.subagent_id,
                    "child_run_id": item.child_run_id,
                    "label": item.label,
                    "goal": item.goal,
                    "status": "running",
                    "tool_scope": list(item.tool_scope),
                    "started_at": started_at,
                },
                idempotency_key=f"subagent:{item.subagent_id}:attempt:{attempt}:started",
            )
        )
        await self._journal(
            JournalEvent(
                run_id=item.child_run_id,
                event_type="run.status_changed",
                status="running",
                summary=f"Executing {item.label}",
                payload={"status": "running", "started_at": started_at},
                idempotency_key=f"attempt:{attempt}:started",
            )
        )
        self._states[item_id] = WorkState(
            work_item_id=item_id,
            status=WorkStatus.RUNNING,
            attempt=attempt,
            request_revision_number=self._request_revision_number,
        )
        handle = await workflow.start_child_workflow(
            ProcurementChildWorkflow.run,
            ChildWorkflowInput(
                execution=ChildActivityInput(
                    parent_run_id=self._request.run_id,
                    child_run_id=item.child_run_id,
                    request_revision_id=self._request_revision_id,
                    request_revision_number=self._request_revision_number,
                    policy_revision=self._request.policy_revision,
                    attempt=attempt,
                    work_item=item,
                    messages=tuple(self._messages),
                )
            ),
            id=(f"{workflow.info().workflow_id}:child:{item.work_item_id}:attempt:{attempt}"),
            cancellation_type=ChildWorkflowCancellationType.WAIT_CANCELLATION_COMPLETED,
        )
        self._active[item_id] = handle
        if self._paused or self._has_unprocessed_commands():
            self._cancel_reasons[item_id] = "control_command"
            handle.cancel()

    async def _finish_child(self, handle: asyncio.Task[ChildResult]) -> None:
        item_id = next(
            item_id for item_id, active_handle in self._active.items() if active_handle is handle
        )
        del self._active[item_id]
        state = self._states[item_id]
        try:
            result = handle.result()
        except asyncio.CancelledError:
            self._states[item_id] = WorkState(
                work_item_id=item_id,
                status=WorkStatus.PENDING,
                attempt=state.attempt,
                request_revision_number=self._request_revision_number,
            )
            self._cancel_reasons.pop(item_id, None)
            return

        if result.status is ChildResultStatus.CANCELLED:
            self._states[item_id] = WorkState(
                work_item_id=item_id,
                status=WorkStatus.PENDING,
                attempt=state.attempt,
                request_revision_number=self._request_revision_number,
            )
            self._cancel_reasons.pop(item_id, None)
            return

        self._results[item_id] = result
        item = self._items[item_id]
        completed_at = workflow.now().isoformat()
        if result.status is ChildResultStatus.COMPLETED:
            self._states[item_id] = WorkState(
                work_item_id=item_id,
                status=WorkStatus.COMPLETED,
                attempt=result.attempt,
                request_revision_number=self._request_revision_number,
                output_ref=result.output_ref,
            )
            event_status = "completed"
            blocker = None
        else:
            self._states[item_id] = WorkState(
                work_item_id=item_id,
                status=WorkStatus.FAILED,
                attempt=result.attempt,
                request_revision_number=self._request_revision_number,
                failure=result.failure,
            )
            event_status = "failed"
            blocker = result.failure.classification.value if result.failure else "unknown"
        await self._journal(
            JournalEvent(
                run_id=self._request.run_id,
                event_type=f"work.{event_status}",
                status=event_status,
                summary=result.summary,
                payload={
                    "status": event_status,
                    "completed_units": 1 if event_status == "completed" else 0,
                    "total_units": 1,
                    "blocker": blocker,
                    "output_ref": result.output_ref,
                },
                work_item_id=item_id,
                idempotency_key=f"work:{item_id}:attempt:{result.attempt}:{event_status}",
            )
        )
        await self._journal(
            JournalEvent(
                run_id=self._request.run_id,
                event_type=f"subagent.{event_status}",
                status=event_status,
                summary=result.summary,
                payload={
                    "subagent_id": item.subagent_id,
                    "status": event_status,
                    "completed_at": completed_at,
                },
                idempotency_key=(
                    f"subagent:{item.subagent_id}:attempt:{result.attempt}:{event_status}"
                ),
            )
        )
        await self._journal(
            JournalEvent(
                run_id=item.child_run_id,
                event_type="run.status_changed",
                status=event_status,
                summary=result.summary,
                payload={"status": event_status, "completed_at": completed_at},
                idempotency_key=f"attempt:{result.attempt}:{event_status}",
            )
        )

    async def _journal(self, event: JournalEvent) -> None:
        await workflow.execute_activity(
            APPEND_JOURNAL_EVENT_ACTIVITY,
            event,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_JOURNAL_RETRY,
        )
