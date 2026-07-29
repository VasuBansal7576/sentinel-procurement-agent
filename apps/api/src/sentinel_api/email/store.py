"""Atomic execution-state storage boundary and in-memory implementation."""

from __future__ import annotations

from asyncio import Lock
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sentinel_api.domain import ActionOutcomeState
from sentinel_api.email.models import (
    EmailDispatchRequest,
    EmailExecutionRecord,
    ProviderAuditEvent,
    ProviderReceipt,
)
from sentinel_api.protected_actions.outcomes import OutcomeMachine


class ExecutionStateConflict(RuntimeError):
    """Raised when another worker won an outcome transition."""


class EmailExecutionStore(Protocol):
    async def ensure_authorized(
        self,
        request: EmailDispatchRequest,
        *,
        at: datetime,
    ) -> EmailExecutionRecord:
        """Load the broker-created APPROVED outcome or create it for an in-memory broker."""

    async def get(self, action_intent_id: UUID) -> EmailExecutionRecord:
        """Return the current durable execution record."""

    async def transition(
        self,
        action_intent_id: UUID,
        *,
        expected: ActionOutcomeState,
        next_state: ActionOutcomeState,
        at: datetime,
        detail: str,
        provider: str | None = None,
        provider_reference: str | None = None,
        receipt: ProviderReceipt | None = None,
    ) -> EmailExecutionRecord:
        """Compare-and-set one valid protected-action outcome transition."""


class InMemoryEmailExecutionStore:
    """Concurrency-safe deterministic store for tests and local composition."""

    def __init__(self) -> None:
        self._records: dict[UUID, EmailExecutionRecord] = {}
        self._lock = Lock()

    async def ensure_authorized(
        self,
        request: EmailDispatchRequest,
        *,
        at: datetime,
    ) -> EmailExecutionRecord:
        async with self._lock:
            existing = self._records.get(request.action_intent_id)
            if existing is not None:
                expected = EmailExecutionRecord.approved(request, at=at)
                if (
                    existing.payload_fingerprint != expected.payload_fingerprint
                    or existing.provider_request_fingerprint
                    != expected.provider_request_fingerprint
                    or existing.idempotency_key_sha256 != expected.idempotency_key_sha256
                ):
                    raise ValueError("action intent was reused with different email request bytes")
                return existing
            record = EmailExecutionRecord.approved(request, at=at)
            self._records[request.action_intent_id] = record
            return record

    async def get(self, action_intent_id: UUID) -> EmailExecutionRecord:
        async with self._lock:
            try:
                return self._records[action_intent_id]
            except KeyError as error:
                raise KeyError(f"email execution does not exist: {action_intent_id}") from error

    async def transition(
        self,
        action_intent_id: UUID,
        *,
        expected: ActionOutcomeState,
        next_state: ActionOutcomeState,
        at: datetime,
        detail: str,
        provider: str | None = None,
        provider_reference: str | None = None,
        receipt: ProviderReceipt | None = None,
    ) -> EmailExecutionRecord:
        async with self._lock:
            current = self._records[action_intent_id]
            if current.state is not expected:
                raise ExecutionStateConflict(
                    f"expected {expected}, found {current.state} for {action_intent_id}"
                )
            OutcomeMachine(state=current.state).transition(next_state)
            reference = provider_reference or (
                receipt.message_id if receipt is not None else current.provider_reference
            )
            event = ProviderAuditEvent(
                action_intent_id=action_intent_id,
                state=next_state,
                occurred_at=at,
                provider=provider or (None if receipt is None else receipt.provider),
                provider_reference=reference,
                detail=detail,
            )
            updated = current.model_copy(
                update={
                    "state": next_state,
                    "attempts": current.attempts
                    + (1 if next_state is ActionOutcomeState.DISPATCHING else 0),
                    "provider_reference": reference,
                    "receipt": receipt or current.receipt,
                    "detail": detail,
                    "updated_at": at,
                    "audit_events": (*current.audit_events, event),
                }
            )
            self._records[action_intent_id] = updated
            return updated
