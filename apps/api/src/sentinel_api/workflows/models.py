"""Compact, deterministic payloads crossing Temporal workflow boundaries."""

from dataclasses import dataclass, field
from enum import StrEnum


class FailureClass(StrEnum):
    TRANSIENT = "transient"
    RATE_LIMITED = "rate_limited"
    AUTH_REQUIRED = "auth_required"
    POLICY_DENIED = "policy_denied"
    INPUT_REQUIRED = "input_required"
    SOURCE_CHANGED = "source_changed"
    CONFLICT = "conflict"
    TOOL_BUG = "tool_bug"
    MODEL_INVALID_OUTPUT = "model_invalid_output"
    OUTCOME_UNKNOWN = "outcome_unknown"
    TERMINAL = "terminal"


class WorkStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ChildResultStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunResultStatus(StrEnum):
    COMPLETED = "completed"
    COMPLETED_WITH_FAILURES = "completed_with_failures"


class CommandKind(StrEnum):
    PAUSE = "pause"
    RESUME = "resume"
    REDIRECT = "redirect"
    QUEUE_MESSAGE = "queue_message"
    RETRY_WORK = "retry_work"


class MessageStatus(StrEnum):
    QUEUED = "queued"
    APPLIED = "applied"


@dataclass(frozen=True)
class ActivityRetry:
    """Retry settings translated to a Temporal activity RetryPolicy."""

    maximum_attempts: int = 3
    initial_interval_seconds: float = 0.5
    maximum_interval_seconds: float = 30.0


@dataclass(frozen=True)
class WorkItem:
    """A bounded child assignment whose large inputs live behind ``input_ref``."""

    work_item_id: str
    child_run_id: str
    subagent_id: str
    phase: str
    kind: str
    label: str
    goal: str
    input_ref: str
    output_keys: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    tool_scope: tuple[str, ...] = ()
    position: int = 0
    timeout_seconds: float = 300.0
    retry: ActivityRetry = field(default_factory=ActivityRetry)
    cancellable: bool = True


@dataclass(frozen=True)
class ProcurementRunInput:
    run_id: str
    request_revision_id: str
    request_revision_number: int
    policy_revision: int
    title: str
    work_items: tuple[WorkItem, ...]
    max_concurrency: int = 3


@dataclass(frozen=True)
class QueuedMessage:
    message_id: str
    sequence: int
    body: str
    status: MessageStatus


@dataclass(frozen=True)
class FailureRecord:
    classification: FailureClass
    message: str
    retryable: bool
    error_type: str | None = None


@dataclass(frozen=True)
class ProducedWork:
    product_id: str
    output_key: str
    kind: str
    request_revision_number: int
    policy_revision: int
    depends_on: tuple[str, ...]


@dataclass(frozen=True)
class ChildActivityInput:
    parent_run_id: str
    child_run_id: str
    request_revision_id: str
    request_revision_number: int
    policy_revision: int
    attempt: int
    work_item: WorkItem
    messages: tuple[QueuedMessage, ...]


@dataclass(frozen=True)
class WorkExecution:
    summary: str
    output_ref: str
    products: tuple[ProducedWork, ...]


@dataclass(frozen=True)
class ChildWorkflowInput:
    execution: ChildActivityInput


@dataclass(frozen=True)
class ChildResult:
    work_item_id: str
    child_run_id: str
    status: ChildResultStatus
    attempt: int
    summary: str
    output_ref: str | None = None
    products: tuple[ProducedWork, ...] = ()
    failure: FailureRecord | None = None


@dataclass(frozen=True)
class WorkState:
    work_item_id: str
    status: WorkStatus
    attempt: int
    request_revision_number: int
    output_ref: str | None = None
    failure: FailureRecord | None = None


@dataclass(frozen=True)
class CommandAck:
    command_id: str
    kind: CommandKind
    sequence: int
    accepted: bool
    detail: str


@dataclass(frozen=True)
class PauseCommand:
    command_id: str
    reason: str


@dataclass(frozen=True)
class ResumeCommand:
    command_id: str
    reason: str = "Operator resumed the run"


@dataclass(frozen=True)
class RedirectCommand:
    command_id: str
    request_revision_id: str
    request_revision_number: int
    changed_dependencies: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class QueueMessageCommand:
    command_id: str
    message_id: str
    body: str


@dataclass(frozen=True)
class RetryWorkCommand:
    command_id: str
    work_item_id: str
    expected_attempt: int
    reason: str


@dataclass(frozen=True)
class WorkflowSnapshot:
    run_id: str
    paused: bool
    request_revision_id: str
    request_revision_number: int
    command_sequence: int
    work: tuple[WorkState, ...]
    messages: tuple[QueuedMessage, ...]
    acknowledgements: tuple[CommandAck, ...]


@dataclass(frozen=True)
class ProcurementRunResult:
    run_id: str
    status: RunResultStatus
    request_revision_id: str
    request_revision_number: int
    children: tuple[ChildResult, ...]
    messages: tuple[QueuedMessage, ...]


@dataclass(frozen=True)
class JournalEvent:
    run_id: str
    event_type: str
    status: str
    summary: str
    payload: dict[
        str,
        str | int | float | bool | list[str] | list[int] | None,
    ] = field(default_factory=dict)
    work_item_id: str | None = None
    actor_id: str | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True)
class EnsureChildRun:
    run_id: str
    parent_run_id: str
    request_revision_id: str
    policy_revision: int
    title: str


@dataclass(frozen=True)
class InvalidationRequest:
    products: tuple[ProducedWork, ...]
    changed_dependencies: tuple[str, ...]


@dataclass(frozen=True)
class InvalidationResult:
    retained_product_ids: tuple[str, ...]
    invalidated_product_ids: tuple[str, ...]
    invalidated_output_keys: tuple[str, ...]
