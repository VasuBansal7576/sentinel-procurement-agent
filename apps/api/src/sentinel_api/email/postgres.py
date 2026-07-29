"""PostgreSQL compare-and-set storage for protected email execution."""

from datetime import datetime
from typing import cast
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from sentinel_api.domain import ActionOutcomeState
from sentinel_api.email.models import (
    EmailDispatchRequest,
    EmailExecutionRecord,
    ProviderAuditEvent,
    ProviderReceipt,
)
from sentinel_api.email.store import ExecutionStateConflict
from sentinel_api.protected_actions.outcomes import OutcomeMachine

Row = dict[str, object]


def _datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"expected datetime, got {type(value).__name__}")
    return value


def _receipt(value: object) -> ProviderReceipt | None:
    if value is None:
        return None
    return ProviderReceipt.model_validate(value)


def _audit_events(value: object) -> tuple[ProviderAuditEvent, ...]:
    if not isinstance(value, list):
        raise TypeError("email audit_events must be a JSON array")
    return tuple(ProviderAuditEvent.model_validate(item) for item in value)


def _record(row: Row) -> EmailExecutionRecord:
    provider_request_fingerprint = row["provider_request_fingerprint"]
    idempotency_key_sha256 = row["idempotency_key_sha256"]
    if provider_request_fingerprint is None or idempotency_key_sha256 is None:
        raise KeyError(f"email execution is not initialized: {row['action_intent_id']}")
    return EmailExecutionRecord(
        action_intent_id=UUID(str(row["action_intent_id"])),
        state=ActionOutcomeState(str(row["state"])),
        payload_fingerprint=str(row["payload_fingerprint"]),
        provider_request_fingerprint=str(provider_request_fingerprint),
        idempotency_key_sha256=str(idempotency_key_sha256),
        attempts=int(cast(int, row["attempts"])),
        provider_reference=cast(str | None, row["provider_reference"]),
        receipt=_receipt(row["receipt"]),
        detail=str(row["detail"]),
        updated_at=_datetime(row["updated_at"]),
        audit_events=_audit_events(row["audit_events"]),
    )


class PostgresEmailExecutionStore:
    """Atomic email outcome store sharing the protected-action connection pool."""

    def __init__(self, pool: AsyncConnectionPool[AsyncConnection[Row]]) -> None:
        self._pool = pool

    async def ensure_authorized(
        self,
        request: EmailDispatchRequest,
        *,
        at: datetime,
    ) -> EmailExecutionRecord:
        expected = EmailExecutionRecord.approved(request, at=at)
        async with self._pool.connection() as connection, connection.transaction():
            row = await self._select(connection, request.action_intent_id, lock=True)
            if str(row["idempotency_key"]) != request.idempotency_key:
                raise ValueError("action intent idempotency key does not match email request")
            if str(row["payload_fingerprint"]) != request.payload_fingerprint:
                raise ValueError("action intent payload fingerprint does not match email request")

            stored_request_fingerprint = row["provider_request_fingerprint"]
            stored_key_sha256 = row["idempotency_key_sha256"]
            if stored_request_fingerprint is None and stored_key_sha256 is None:
                if ActionOutcomeState(str(row["state"])) is not ActionOutcomeState.APPROVED:
                    raise ValueError("email execution metadata is missing after dispatch began")
                cursor = await connection.execute(
                    """
                    UPDATE sentinel.action_outcomes
                    SET provider_request_fingerprint = %s,
                        idempotency_key_sha256 = %s,
                        detail = %s,
                        updated_at = %s,
                        audit_events = %s
                    WHERE action_intent_id = %s
                    RETURNING action_intent_id
                    """,
                    (
                        expected.provider_request_fingerprint,
                        expected.idempotency_key_sha256,
                        expected.detail,
                        at,
                        Jsonb([event.model_dump(mode="json") for event in expected.audit_events]),
                        request.action_intent_id,
                    ),
                )
                if await cursor.fetchone() is None:
                    raise KeyError(f"email execution does not exist: {request.action_intent_id}")
                row = await self._select(
                    connection,
                    request.action_intent_id,
                    lock=False,
                )
            elif (
                str(stored_request_fingerprint) != expected.provider_request_fingerprint
                or str(stored_key_sha256) != expected.idempotency_key_sha256
            ):
                raise ValueError("action intent was reused with different email request bytes")
            return _record(row)

    async def get(self, action_intent_id: UUID) -> EmailExecutionRecord:
        async with self._pool.connection() as connection:
            return _record(await self._select(connection, action_intent_id, lock=False))

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
        async with self._pool.connection() as connection, connection.transaction():
            row = await self._select(connection, action_intent_id, lock=True)
            current = _record(row)
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
            audit_events = (*current.audit_events, event)
            stored_receipt = receipt if receipt is not None else current.receipt
            cursor = await connection.execute(
                """
                UPDATE sentinel.action_outcomes
                SET state = %s,
                    attempts = attempts + %s,
                    provider = %s,
                    provider_reference = %s,
                    receipt = %s,
                    detail = %s,
                    updated_at = %s,
                    audit_events = %s
                WHERE action_intent_id = %s AND state = %s
                RETURNING action_intent_id
                """,
                (
                    next_state.value,
                    1 if next_state is ActionOutcomeState.DISPATCHING else 0,
                    provider or (receipt.provider if receipt is not None else row["provider"]),
                    reference,
                    Jsonb(stored_receipt.model_dump(mode="json"))
                    if stored_receipt is not None
                    else None,
                    detail,
                    at,
                    Jsonb([audit.model_dump(mode="json") for audit in audit_events]),
                    action_intent_id,
                    expected.value,
                ),
            )
            if await cursor.fetchone() is None:
                raise ExecutionStateConflict(
                    f"another worker changed email execution {action_intent_id}"
                )
            return _record(await self._select(connection, action_intent_id, lock=False))

    @staticmethod
    async def _select(
        connection: AsyncConnection[Row],
        action_intent_id: UUID,
        *,
        lock: bool,
    ) -> Row:
        suffix = " FOR UPDATE OF outcome" if lock else ""
        cursor = await connection.execute(
            f"""
            SELECT outcome.*, intent.payload_fingerprint, intent.idempotency_key
            FROM sentinel.action_outcomes AS outcome
            JOIN sentinel.action_intents AS intent
              ON intent.action_intent_id = outcome.action_intent_id
            WHERE outcome.action_intent_id = %s{suffix}
            """,
            (action_intent_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise KeyError(f"email execution does not exist: {action_intent_id}")
        return row
