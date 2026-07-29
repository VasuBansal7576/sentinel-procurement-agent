"""Contract tests for the credential-free Resend-compatible adapter."""

import hashlib
from collections import deque
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from sentinel_api.email import (
    DispatchDisposition,
    EmailDispatchRequest,
    EmailMessage,
    ReconciliationDisposition,
    ResendEmailProvider,
    ResendTransportError,
    ResendTransportResponse,
    TransportEffect,
)

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


class FakeTransport:
    def __init__(
        self,
        outcomes: tuple[ResendTransportResponse | ResendTransportError, ...],
    ) -> None:
        self.outcomes = deque(outcomes)
        self.calls: list[dict[str, object]] = []

    async def request(
        self,
        *,
        method: str,
        path: str,
        headers: Mapping[str, str],
        json_body: Mapping[str, object] | None,
    ) -> ResendTransportResponse:
        self.calls.append(
            {
                "method": method,
                "path": path,
                "headers": dict(headers),
                "json_body": None if json_body is None else dict(json_body),
            }
        )
        outcome = self.outcomes.popleft()
        if isinstance(outcome, ResendTransportError):
            raise outcome
        return outcome


def _request(*, authorized_at: datetime = NOW) -> EmailDispatchRequest:
    return EmailDispatchRequest(
        action_intent_id=uuid4(),
        idempotency_key=hashlib.sha256(b"stable authorized action").hexdigest(),
        payload_fingerprint=hashlib.sha256(b"approved payload").hexdigest(),
        authorized_at=authorized_at,
        message=EmailMessage(
            sender="sentinel@example.test",
            recipient="demo@example.test",
            subject="Controlled request",
            text_body="Approved exact body",
        ),
    )


@pytest.mark.asyncio
async def test_resend_maps_request_and_confirmed_receipt_without_credentials() -> None:
    transport = FakeTransport((ResendTransportResponse(status_code=200, body={"id": "msg_123"}),))
    provider = ResendEmailProvider(transport, clock=lambda: NOW)
    request = _request()

    result = await provider.dispatch(request)

    assert result.disposition is DispatchDisposition.CONFIRMED
    assert result.receipt is not None
    assert result.receipt.message_id == "msg_123"
    assert transport.calls == [
        {
            "method": "POST",
            "path": "/emails",
            "headers": {"Idempotency-Key": request.idempotency_key},
            "json_body": {
                "from": "sentinel@example.test",
                "to": ["demo@example.test"],
                "subject": "Controlled request",
                "text": "Approved exact body",
            },
        }
    ]
    assert "Authorization" not in transport.calls[0]["headers"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (422, DispatchDisposition.FAILED_BEFORE_EFFECT),
        (429, DispatchDisposition.FAILED_BEFORE_EFFECT),
        (500, DispatchDisposition.OUTCOME_UNKNOWN),
        (503, DispatchDisposition.OUTCOME_UNKNOWN),
    ],
)
async def test_resend_classifies_provider_errors_conservatively(
    status: int,
    expected: DispatchDisposition,
) -> None:
    provider = ResendEmailProvider(
        FakeTransport((ResendTransportResponse(status_code=status),)),
        clock=lambda: NOW,
    )

    result = await provider.dispatch(_request())

    assert result.disposition is expected
    assert str(status) in result.detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("effect", "expected"),
    [
        (TransportEffect.NOT_APPLIED, DispatchDisposition.FAILED_BEFORE_EFFECT),
        (TransportEffect.UNKNOWN, DispatchDisposition.OUTCOME_UNKNOWN),
    ],
)
async def test_transport_timeout_declares_whether_effect_was_possible(
    effect: TransportEffect,
    expected: DispatchDisposition,
) -> None:
    provider = ResendEmailProvider(
        FakeTransport((ResendTransportError("socket timeout", effect=effect),)),
        clock=lambda: NOW,
    )

    result = await provider.dispatch(_request())

    assert result.disposition is expected
    assert "socket timeout" not in result.detail


@pytest.mark.asyncio
async def test_missing_receipt_reference_is_an_unknown_outcome() -> None:
    provider = ResendEmailProvider(
        FakeTransport((ResendTransportResponse(status_code=202, body={}),)),
        clock=lambda: NOW,
    )

    result = await provider.dispatch(_request())

    assert result.disposition is DispatchDisposition.OUTCOME_UNKNOWN
    assert result.receipt is None


@pytest.mark.asyncio
async def test_reconciliation_maps_confirmed_provider_receipt() -> None:
    transport = FakeTransport(
        (
            ResendTransportResponse(
                status_code=200,
                body={"id": "msg_123", "last_event": "delivered"},
            ),
        )
    )
    provider = ResendEmailProvider(transport, clock=lambda: NOW)

    result = await provider.reconcile(_request(), "msg_123")

    assert result.disposition is ReconciliationDisposition.CONFIRMED
    assert result.receipt is not None
    assert result.receipt.status == "delivered"
    assert transport.calls[0]["method"] == "GET"
    assert transport.calls[0]["path"] == "/emails/msg_123"
    assert transport.calls[0]["headers"] == {}


@pytest.mark.asyncio
async def test_idempotent_replay_is_safe_only_within_configured_window() -> None:
    recent_transport = FakeTransport(())
    recent = ResendEmailProvider(
        recent_transport,
        clock=lambda: NOW,
        idempotency_window=timedelta(hours=24),
    )
    stale_transport = FakeTransport(())
    stale = ResendEmailProvider(
        stale_transport,
        clock=lambda: NOW,
        idempotency_window=timedelta(hours=24),
    )

    safe = await recent.reconcile(_request(authorized_at=NOW - timedelta(hours=1)), None)
    operator = await stale.reconcile(_request(authorized_at=NOW - timedelta(hours=25)), None)

    assert safe.disposition is ReconciliationDisposition.SAFE_TO_RETRY
    assert operator.disposition is ReconciliationDisposition.NEEDS_OPERATOR
    assert recent_transport.calls == []
    assert stale_transport.calls == []


@pytest.mark.asyncio
async def test_failed_or_mismatched_receipt_lookup_never_allows_retry() -> None:
    for response in (
        ResendTransportResponse(status_code=404),
        ResendTransportResponse(status_code=200, body={"id": "different"}),
    ):
        provider = ResendEmailProvider(FakeTransport((response,)), clock=lambda: NOW)

        result = await provider.reconcile(_request(), "msg_123")

        assert result.disposition is ReconciliationDisposition.NEEDS_OPERATOR


@pytest.mark.asyncio
async def test_unsafe_provider_reference_never_reaches_transport_path() -> None:
    transport = FakeTransport(())
    provider = ResendEmailProvider(transport, clock=lambda: NOW)

    result = await provider.reconcile(_request(), "../secrets")

    assert result.disposition is ReconciliationDisposition.NEEDS_OPERATOR
    assert transport.calls == []
