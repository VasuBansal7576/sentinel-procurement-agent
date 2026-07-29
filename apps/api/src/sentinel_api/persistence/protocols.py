"""Protocols shared by HTTP delivery and PostgreSQL persistence."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sentinel_api.persistence.models import (
    EventDraft,
    NewRun,
    OutboxMessage,
    RunSummary,
    StoredEvent,
    SubagentProjection,
    WorkItemProjection,
)


class EventStore(Protocol):
    """Storage contract used by commands, projections, and realtime delivery."""

    async def create_run(self, run: NewRun) -> StoredEvent: ...

    async def append_event(self, run_id: UUID, draft: EventDraft) -> StoredEvent: ...

    async def get_run(self, run_id: UUID) -> RunSummary | None: ...

    async def list_sessions(
        self,
        *,
        limit: int = 50,
        before: datetime | None = None,
    ) -> Sequence[RunSummary]: ...

    async def list_events(
        self,
        run_id: UUID,
        *,
        after_sequence: int = 0,
        limit: int = 500,
    ) -> Sequence[StoredEvent]: ...

    async def list_work_items(self, run_id: UUID) -> Sequence[WorkItemProjection]: ...

    async def list_subagents(self, run_id: UUID) -> Sequence[SubagentProjection]: ...

    async def rebuild_projections(self, run_id: UUID) -> RunSummary: ...

    async def claim_outbox(
        self,
        *,
        consumer_id: str,
        limit: int = 100,
        lease_seconds: int = 30,
    ) -> Sequence[OutboxMessage]: ...

    async def mark_outbox_published(self, *, outbox_id: int, consumer_id: str) -> bool: ...

    async def release_outbox(
        self,
        *,
        outbox_id: int,
        consumer_id: str,
        error: str,
    ) -> bool: ...
