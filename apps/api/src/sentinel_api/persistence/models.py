"""Persistence-owned records at the event journal boundary."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from uuid import UUID, uuid4

JsonObject = Mapping[str, object]


def _empty_payload() -> JsonObject:
    return MappingProxyType({})


@dataclass(frozen=True, slots=True)
class NewRun:
    """State required to create a durable operator session."""

    run_id: UUID = field(default_factory=uuid4)
    title: str = ""
    status: str = "queued"
    parent_run_id: UUID | None = None
    procurement_case_id: UUID | None = None
    request_revision_id: UUID | None = None
    policy_revision: int | None = None
    summary: str | None = None


@dataclass(frozen=True, slots=True)
class EventDraft:
    """An event before PostgreSQL assigns its per-run sequence."""

    event_type: str
    status: str
    summary: str
    payload: JsonObject = field(default_factory=_empty_payload)
    payload_ref: str | None = None
    event_id: UUID = field(default_factory=uuid4)
    work_item_id: UUID | None = None
    actor_id: str | None = None
    causation_id: UUID | None = None
    correlation_id: UUID | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class StoredEvent:
    """Immutable event journal row."""

    event_id: UUID
    run_id: UUID
    sequence: int
    parent_run_id: UUID | None
    work_item_id: UUID | None
    actor_id: str | None
    event_type: str
    status: str
    causation_id: UUID | None
    correlation_id: UUID | None
    idempotency_key: str | None
    summary: str
    payload: JsonObject
    payload_ref: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RunSummary:
    """Read-optimized session history and run header projection."""

    run_id: UUID
    parent_run_id: UUID | None
    title: str
    status: str
    summary: str | None
    active_phase: str | None
    request_revision_id: UUID | None
    policy_revision: int | None
    completed_work_items: int
    total_work_items: int
    active_subagents: int
    blocker_count: int
    event_count: int
    last_sequence: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class WorkItemProjection:
    """One work-tree node reconstructed from journal events."""

    run_id: UUID
    work_item_id: UUID
    parent_work_item_id: UUID | None
    subagent_id: UUID | None
    phase: str
    kind: str
    label: str
    status: str
    position: int
    completed_units: int | None
    total_units: int | None
    blocker: str | None
    last_sequence: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SubagentProjection:
    """One independently scoped child in the operator run tree."""

    run_id: UUID
    subagent_id: UUID
    parent_subagent_id: UUID | None
    child_run_id: UUID | None
    label: str
    goal: str
    status: str
    tool_scope: tuple[str, ...]
    last_sequence: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    """A leased at-least-once message from the transactional outbox."""

    outbox_id: int
    event_id: UUID
    run_id: UUID
    sequence: int
    topic: str
    payload: JsonObject
    attempts: int
    created_at: datetime
