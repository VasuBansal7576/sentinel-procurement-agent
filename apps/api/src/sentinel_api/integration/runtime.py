"""Launchers connecting typed intake to the merged parent/child runtime."""

from __future__ import annotations

import asyncio
from typing import Protocol
from uuid import UUID

from temporalio.client import Client

from sentinel_api.domain import utc_now
from sentinel_api.persistence.models import EventDraft
from sentinel_api.persistence.protocols import EventStore
from sentinel_api.workflows.activities import RuntimeActivities
from sentinel_api.workflows.models import (
    ChildActivityInput,
    PauseCommand,
    ProcurementRunInput,
    QueueMessageCommand,
    RedirectCommand,
    ResumeCommand,
    RetryWorkCommand,
)
from sentinel_api.workflows.parent import ProcurementParentWorkflow
from sentinel_api.workflows.runtime import parent_workflow_id, start_procurement_run


class RuntimeLauncher(Protocol):
    async def start(self, request: ProcurementRunInput) -> None: ...

    async def pause(self, run_id: UUID, command: PauseCommand) -> object: ...

    async def resume(self, run_id: UUID, command: ResumeCommand) -> object: ...

    async def queue_message(
        self,
        run_id: UUID,
        command: QueueMessageCommand,
    ) -> object: ...

    async def redirect(self, run_id: UUID, command: RedirectCommand) -> object: ...

    async def retry(self, run_id: UUID, command: RetryWorkCommand) -> object: ...


class InlineRuntimeLauncher:
    """Credential-free adapter using the real production activity boundary locally."""

    def __init__(
        self,
        *,
        event_store: EventStore,
        activities: RuntimeActivities,
    ) -> None:
        self._event_store = event_store
        self._activities = activities

    async def start(self, request: ProcurementRunInput) -> None:
        run_id = UUID(request.run_id)
        item = request.work_items[0]
        work_item_id = UUID(item.work_item_id)
        started_at = utc_now()
        await self._event_store.append_event(
            run_id,
            EventDraft(
                event_type="run.status_changed",
                status="running",
                summary="Credential-free procurement runtime started",
                payload={
                    "status": "running",
                    "active_phase": item.phase,
                    "started_at": started_at.isoformat(),
                },
                idempotency_key="workflow.started",
            ),
        )
        await self._activities.ensure_child_run(request=self._child_run_request(request))
        await self._event_store.append_event(
            run_id,
            EventDraft(
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
                work_item_id=work_item_id,
                idempotency_key=f"work:{item.work_item_id}:attempt:1:started",
            ),
        )
        await self._event_store.append_event(
            run_id,
            EventDraft(
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
                    "started_at": started_at.isoformat(),
                },
                idempotency_key=f"subagent:{item.subagent_id}:attempt:1:started",
            ),
        )
        output = await self._activities.execute_work(
            ChildActivityInput(
                parent_run_id=request.run_id,
                child_run_id=item.child_run_id,
                request_revision_id=request.request_revision_id,
                request_revision_number=request.request_revision_number,
                policy_revision=request.policy_revision,
                attempt=1,
                work_item=item,
                messages=(),
            )
        )
        completed_at = utc_now()
        await self._event_store.append_event(
            run_id,
            EventDraft(
                event_type="work.completed",
                status="completed",
                summary=output.summary,
                payload={
                    "status": "completed",
                    "completed_units": 1,
                    "total_units": 1,
                    "output_ref": output.output_ref,
                },
                work_item_id=work_item_id,
                idempotency_key=f"work:{item.work_item_id}:attempt:1:completed",
            ),
        )
        await self._event_store.append_event(
            run_id,
            EventDraft(
                event_type="subagent.completed",
                status="completed",
                summary=output.summary,
                payload={
                    "subagent_id": item.subagent_id,
                    "status": "completed",
                    "completed_at": completed_at.isoformat(),
                },
                idempotency_key=f"subagent:{item.subagent_id}:attempt:1:completed",
            ),
        )
        await self._event_store.append_event(
            run_id,
            EventDraft(
                event_type="run.status_changed",
                status="completed",
                summary="All child workflows completed",
                payload={
                    "status": "completed",
                    "active_phase": "complete",
                    "completed_at": completed_at.isoformat(),
                },
                idempotency_key="workflow.completed",
            ),
        )

    @staticmethod
    def _child_run_request(request: ProcurementRunInput):
        from sentinel_api.workflows.models import EnsureChildRun

        item = request.work_items[0]
        return EnsureChildRun(
            run_id=item.child_run_id,
            parent_run_id=request.run_id,
            request_revision_id=request.request_revision_id,
            policy_revision=request.policy_revision,
            title=item.label,
        )

    async def pause(self, run_id: UUID, command: PauseCommand) -> object:
        return await self._record_control(run_id, command.command_id, "paused", command.reason)

    async def resume(self, run_id: UUID, command: ResumeCommand) -> object:
        return await self._record_control(run_id, command.command_id, "running", command.reason)

    async def _record_control(
        self,
        run_id: UUID,
        command_id: str,
        status: str,
        reason: str,
    ) -> dict[str, object]:
        event = await self._event_store.append_event(
            run_id,
            EventDraft(
                event_type="run.status_changed",
                status=status,
                summary=reason,
                payload={"status": status, "summary": reason},
                actor_id="operator",
                idempotency_key=f"command:{command_id}:applied",
            ),
        )
        return {
            "command_id": command_id,
            "accepted": True,
            "sequence": event.sequence,
            "detail": f"{status} applied",
        }

    async def queue_message(
        self,
        run_id: UUID,
        command: QueueMessageCommand,
    ) -> object:
        event = await self._event_store.append_event(
            run_id,
            EventDraft(
                event_type="operator.message_applied",
                status="applied",
                summary="Applied queued operator message",
                payload={
                    "command_id": command.command_id,
                    "message_id": command.message_id,
                    "body": command.body,
                    "mode": "queue",
                },
                actor_id="operator",
                idempotency_key=f"message:{command.message_id}:applied",
            ),
        )
        return {
            "command_id": command.command_id,
            "accepted": True,
            "sequence": event.sequence,
            "detail": "queued message applied",
        }

    async def redirect(self, run_id: UUID, command: RedirectCommand) -> object:
        event = await self._event_store.append_event(
            run_id,
            EventDraft(
                event_type="run.redirected",
                status="running",
                summary=command.reason,
                payload={
                    "command_id": command.command_id,
                    "mode": "redirect",
                    "body": command.reason,
                    "request_revision_id": command.request_revision_id,
                    "request_revision_number": command.request_revision_number,
                    "changed_dependencies": list(command.changed_dependencies),
                    "retained_product_ids": [],
                    "invalidated_product_ids": [],
                },
                actor_id="operator",
                idempotency_key=f"redirect:{command.request_revision_number}",
            ),
        )
        return {
            "command_id": command.command_id,
            "accepted": True,
            "sequence": event.sequence,
            "detail": "redirect applied",
        }

    async def retry(self, run_id: UUID, command: RetryWorkCommand) -> object:
        del run_id, command
        raise ValueError("recoverable retry requires the durable Temporal runtime")


class TemporalRuntimeLauncher:
    """Thin client adapter; workflow code and sandbox remain centrally owned."""

    def __init__(self, client: Client, *, task_queue: str) -> None:
        self._client = client
        self._task_queue = task_queue

    async def start(self, request: ProcurementRunInput) -> None:
        await start_procurement_run(self._client, request, task_queue=self._task_queue)

    def _handle(self, run_id: UUID):
        return self._client.get_workflow_handle(parent_workflow_id(str(run_id)))

    async def pause(self, run_id: UUID, command: PauseCommand) -> object:
        return await self._handle(run_id).execute_update(
            ProcurementParentWorkflow.pause,
            command,
        )

    async def resume(self, run_id: UUID, command: ResumeCommand) -> object:
        return await self._handle(run_id).execute_update(
            ProcurementParentWorkflow.resume,
            command,
        )

    async def queue_message(
        self,
        run_id: UUID,
        command: QueueMessageCommand,
    ) -> object:
        return await self._handle(run_id).execute_update(
            ProcurementParentWorkflow.queue_message,
            command,
        )

    async def redirect(self, run_id: UUID, command: RedirectCommand) -> object:
        return await self._handle(run_id).execute_update(
            ProcurementParentWorkflow.redirect,
            command,
        )

    async def retry(self, run_id: UUID, command: RetryWorkCommand) -> object:
        return await self._handle(run_id).execute_update(
            ProcurementParentWorkflow.retry_work,
            command,
        )


class LazyTemporalRuntimeLauncher:
    """Connect on the first operator command so unrelated API paths stay healthy."""

    def __init__(
        self,
        *,
        address: str,
        namespace: str,
        task_queue: str,
    ) -> None:
        self._address = address
        self._namespace = namespace
        self._task_queue = task_queue
        self._launcher: TemporalRuntimeLauncher | None = None
        self._lock = asyncio.Lock()

    async def _runtime(self) -> TemporalRuntimeLauncher:
        if self._launcher is not None:
            return self._launcher
        async with self._lock:
            if self._launcher is None:
                client = await Client.connect(
                    self._address,
                    namespace=self._namespace,
                )
                self._launcher = TemporalRuntimeLauncher(
                    client,
                    task_queue=self._task_queue,
                )
        return self._launcher

    async def start(self, request: ProcurementRunInput) -> None:
        await (await self._runtime()).start(request)

    async def pause(self, run_id: UUID, command: PauseCommand) -> object:
        return await (await self._runtime()).pause(run_id, command)

    async def resume(self, run_id: UUID, command: ResumeCommand) -> object:
        return await (await self._runtime()).resume(run_id, command)

    async def queue_message(
        self,
        run_id: UUID,
        command: QueueMessageCommand,
    ) -> object:
        return await (await self._runtime()).queue_message(run_id, command)

    async def redirect(self, run_id: UUID, command: RedirectCommand) -> object:
        return await (await self._runtime()).redirect(run_id, command)

    async def retry(self, run_id: UUID, command: RetryWorkCommand) -> object:
        return await (await self._runtime()).retry(run_id, command)
