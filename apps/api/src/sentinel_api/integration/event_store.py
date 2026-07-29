"""In-memory implementation of the durable journal contract for local integration."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sentinel_api.domain import utc_now
from sentinel_api.persistence.models import (
    EventDraft,
    NewRun,
    OutboxMessage,
    RunSummary,
    StoredEvent,
    SubagentProjection,
    WorkItemProjection,
)


class InMemoryEventStore:
    """Append-only, idempotent journal with deterministic operator projections."""

    finite_streams = True

    def __init__(self) -> None:
        self._runs: dict[UUID, NewRun] = {}
        self._events: dict[UUID, list[StoredEvent]] = {}
        self._run_created: dict[UUID, datetime] = {}
        self._work: dict[tuple[UUID, UUID], WorkItemProjection] = {}
        self._subagents: dict[tuple[UUID, UUID], SubagentProjection] = {}

    async def create_run(self, run: NewRun) -> StoredEvent:
        existing = self._runs.get(run.run_id)
        if existing is not None:
            if existing != run:
                raise ValueError("run ID was reused with different inputs")
            return self._events[run.run_id][0]
        if not run.title.strip():
            raise ValueError("run title must not be blank")
        self._runs[run.run_id] = run
        self._events[run.run_id] = []
        self._run_created[run.run_id] = utc_now()
        return await self.append_event(
            run.run_id,
            EventDraft(
                event_type="run.created",
                status=run.status,
                summary=f"Created run: {run.title}",
                payload={
                    "title": run.title,
                    "status": run.status,
                    "summary": run.summary,
                    "request_revision_id": (
                        str(run.request_revision_id) if run.request_revision_id else None
                    ),
                    "policy_revision": run.policy_revision,
                },
                idempotency_key="run.created",
            ),
        )

    async def append_event(self, run_id: UUID, draft: EventDraft) -> StoredEvent:
        if run_id not in self._runs:
            raise LookupError(str(run_id))
        events = self._events[run_id]
        if draft.idempotency_key is not None:
            existing = next(
                (event for event in events if event.idempotency_key == draft.idempotency_key),
                None,
            )
            if existing is not None:
                return existing
        run = self._runs[run_id]
        event = StoredEvent(
            event_id=draft.event_id,
            run_id=run_id,
            sequence=len(events) + 1,
            parent_run_id=run.parent_run_id,
            work_item_id=draft.work_item_id,
            actor_id=draft.actor_id,
            event_type=draft.event_type,
            status=draft.status,
            causation_id=draft.causation_id,
            correlation_id=draft.correlation_id,
            idempotency_key=draft.idempotency_key,
            summary=draft.summary,
            payload=dict(draft.payload),
            payload_ref=draft.payload_ref,
            created_at=utc_now(),
        )
        events.append(event)
        self._apply_projection(event)
        return event

    def _apply_projection(self, event: StoredEvent) -> None:
        if event.event_type.startswith("work."):
            self._apply_work(event)
        if event.event_type.startswith("subagent."):
            self._apply_subagent(event)

    def _apply_work(self, event: StoredEvent) -> None:
        if event.work_item_id is None:
            raise ValueError("work event requires work_item_id")
        key = (event.run_id, event.work_item_id)
        previous = self._work.get(key)
        payload = event.payload

        def value(name: str, default: object = None) -> object:
            if name in payload:
                return payload[name]
            return getattr(previous, name) if previous is not None else default

        created_at = previous.created_at if previous is not None else event.created_at
        self._work[key] = WorkItemProjection(
            run_id=event.run_id,
            work_item_id=event.work_item_id,
            parent_work_item_id=_optional_uuid(value("parent_work_item_id")),
            subagent_id=_optional_uuid(value("subagent_id")),
            phase=str(value("phase", "integration")),
            kind=str(value("kind", "work")),
            label=str(value("label", event.summary)),
            status=str(value("status", event.status)),
            position=int(str(value("position", 0))),
            completed_units=_optional_int(value("completed_units")),
            total_units=_optional_int(value("total_units")),
            blocker=_optional_str(value("blocker")),
            last_sequence=event.sequence,
            created_at=created_at,
            updated_at=event.created_at,
        )

    def _apply_subagent(self, event: StoredEvent) -> None:
        raw_id = event.payload.get("subagent_id")
        if raw_id is None:
            raise ValueError("subagent event requires payload.subagent_id")
        subagent_id = UUID(str(raw_id))
        key = (event.run_id, subagent_id)
        previous = self._subagents.get(key)

        def value(name: str, default: object = None) -> object:
            if name in event.payload:
                return event.payload[name]
            return getattr(previous, name) if previous is not None else default

        scope = value("tool_scope", ())
        if not isinstance(scope, (list, tuple)):
            raise ValueError("tool_scope must be an array")
        created_at = previous.created_at if previous is not None else event.created_at
        self._subagents[key] = SubagentProjection(
            run_id=event.run_id,
            subagent_id=subagent_id,
            parent_subagent_id=_optional_uuid(value("parent_subagent_id")),
            child_run_id=_optional_uuid(value("child_run_id")),
            label=str(value("label", event.summary)),
            goal=str(value("goal", event.summary)),
            status=str(value("status", event.status)),
            tool_scope=tuple(str(item) for item in scope),
            last_sequence=event.sequence,
            started_at=_optional_datetime(value("started_at")),
            completed_at=_optional_datetime(value("completed_at")),
            created_at=created_at,
            updated_at=event.created_at,
        )

    async def get_run(self, run_id: UUID) -> RunSummary | None:
        run = self._runs.get(run_id)
        if run is None:
            return None
        events = self._events[run_id]
        payloads = [event.payload for event in events if event.event_type.startswith("run.")]
        latest = {
            key: payload[key]
            for payload in payloads
            for key in (
                "title",
                "status",
                "summary",
                "active_phase",
                "request_revision_id",
                "policy_revision",
                "started_at",
                "completed_at",
            )
            if key in payload
        }
        work = [item for (owner, _), item in self._work.items() if owner == run_id]
        subagents = [item for (owner, _), item in self._subagents.items() if owner == run_id]
        created_at = self._run_created[run_id]
        updated_at = events[-1].created_at if events else created_at
        status = str(latest.get("status", run.status))
        return RunSummary(
            run_id=run_id,
            parent_run_id=run.parent_run_id,
            title=str(latest.get("title", run.title)),
            status=status,
            summary=_optional_str(latest.get("summary", run.summary)),
            active_phase=_optional_str(latest.get("active_phase")),
            request_revision_id=_optional_uuid(
                latest.get("request_revision_id", run.request_revision_id)
            ),
            policy_revision=_optional_int(latest.get("policy_revision", run.policy_revision)),
            completed_work_items=sum(item.status == "completed" for item in work),
            total_work_items=len(work),
            active_subagents=sum(item.status == "running" for item in subagents),
            blocker_count=sum(item.blocker is not None for item in work),
            event_count=len(events),
            last_sequence=len(events),
            started_at=_optional_datetime(latest.get("started_at")),
            completed_at=_optional_datetime(latest.get("completed_at")),
            created_at=created_at,
            updated_at=updated_at,
        )

    async def list_sessions(
        self,
        *,
        limit: int = 50,
        before: datetime | None = None,
    ) -> Sequence[RunSummary]:
        summaries = [
            summary
            for run_id in self._runs
            if (summary := await self.get_run(run_id)) is not None
            and (before is None or summary.updated_at < before)
        ]
        return tuple(
            sorted(summaries, key=lambda summary: summary.updated_at, reverse=True)[:limit]
        )

    async def list_events(
        self,
        run_id: UUID,
        *,
        after_sequence: int = 0,
        limit: int = 500,
    ) -> Sequence[StoredEvent]:
        return tuple(
            event for event in self._events.get(run_id, ()) if event.sequence > after_sequence
        )[:limit]

    async def list_work_items(self, run_id: UUID) -> Sequence[WorkItemProjection]:
        return tuple(
            sorted(
                (item for (owner_id, _), item in self._work.items() if owner_id == run_id),
                key=lambda item: (item.position, str(item.work_item_id)),
            )
        )

    async def list_subagents(self, run_id: UUID) -> Sequence[SubagentProjection]:
        return tuple(
            sorted(
                (item for (owner_id, _), item in self._subagents.items() if owner_id == run_id),
                key=lambda item: (item.created_at, str(item.subagent_id)),
            )
        )

    async def rebuild_projections(self, run_id: UUID) -> RunSummary:
        if run_id not in self._runs:
            raise LookupError(str(run_id))
        self._work = {key: value for key, value in self._work.items() if key[0] != run_id}
        self._subagents = {key: value for key, value in self._subagents.items() if key[0] != run_id}
        for event in self._events[run_id]:
            self._apply_projection(event)
        summary = await self.get_run(run_id)
        assert summary is not None
        return summary

    async def claim_outbox(
        self,
        *,
        consumer_id: str,
        limit: int = 100,
        lease_seconds: int = 30,
    ) -> Sequence[OutboxMessage]:
        del consumer_id, limit, lease_seconds
        return ()

    async def mark_outbox_published(self, *, outbox_id: int, consumer_id: str) -> bool:
        del outbox_id, consumer_id
        return False

    async def release_outbox(
        self,
        *,
        outbox_id: int,
        consumer_id: str,
        error: str,
    ) -> bool:
        del outbox_id, consumer_id, error
        return False


def _optional_uuid(value: object) -> UUID | None:
    return None if value is None else UUID(str(value))


def _optional_int(value: object) -> int | None:
    return None if value is None else int(str(value))


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
