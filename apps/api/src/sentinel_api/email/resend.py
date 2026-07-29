"""Resend-compatible provider adapter with an injected authenticated transport."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from pydantic import Field

from sentinel_api.domain import ContractModel, utc_now
from sentinel_api.email.models import (
    DispatchDisposition,
    EmailDispatchRequest,
    ProviderDispatchResult,
    ProviderReceipt,
    ProviderReconciliationResult,
    ReconciliationDisposition,
    validate_provider_message_id,
)


class TransportEffect(StrEnum):
    NOT_APPLIED = "not_applied"
    UNKNOWN = "unknown"


class ResendTransportError(RuntimeError):
    """Sanitized transport failure classified by whether an effect was possible."""

    def __init__(self, message: str, *, effect: TransportEffect) -> None:
        super().__init__(message)
        self.effect = effect


class ResendTransportResponse(ContractModel):
    status_code: int = Field(ge=100, le=599)
    body: dict[str, object] = Field(default_factory=dict)


class ResendTransport(Protocol):
    async def request(
        self,
        *,
        method: str,
        path: str,
        headers: Mapping[str, str],
        json_body: Mapping[str, object] | None,
    ) -> ResendTransportResponse:
        """Perform authenticated I/O outside this adapter without exposing credentials."""


class ResendEmailProvider:
    """Translate neutral requests to Resend's HTTP shape without owning secrets."""

    def __init__(
        self,
        transport: ResendTransport,
        *,
        clock: Callable[[], datetime] = utc_now,
        idempotency_window: timedelta = timedelta(hours=24),
    ) -> None:
        if idempotency_window <= timedelta(0):
            raise ValueError("idempotency window must be positive")
        self._transport = transport
        self._clock = clock
        self._idempotency_window = idempotency_window

    async def dispatch(self, request: EmailDispatchRequest) -> ProviderDispatchResult:
        try:
            response = await self._transport.request(
                method="POST",
                path="/emails",
                headers={"Idempotency-Key": request.idempotency_key},
                json_body={
                    "from": request.message.sender,
                    "to": [request.message.recipient],
                    "subject": request.message.subject,
                    "text": request.message.text_body,
                },
            )
        except ResendTransportError as error:
            disposition = (
                DispatchDisposition.FAILED_BEFORE_EFFECT
                if error.effect is TransportEffect.NOT_APPLIED
                else DispatchDisposition.OUTCOME_UNKNOWN
            )
            return ProviderDispatchResult(
                provider="resend",
                disposition=disposition,
                detail="Resend transport failed before effect"
                if disposition is DispatchDisposition.FAILED_BEFORE_EFFECT
                else "Resend transport outcome is unknown",
            )

        if 200 <= response.status_code < 300:
            message_id = response.body.get("id")
            if not isinstance(message_id, str):
                return ProviderDispatchResult(
                    provider="resend",
                    disposition=DispatchDisposition.OUTCOME_UNKNOWN,
                    detail="Resend accepted the request without a usable message reference",
                )
            try:
                message_id = validate_provider_message_id(message_id)
            except ValueError:
                return ProviderDispatchResult(
                    provider="resend",
                    disposition=DispatchDisposition.OUTCOME_UNKNOWN,
                    detail="Resend accepted the request with an unsafe message reference",
                )
            receipt = ProviderReceipt(
                provider="resend",
                message_id=message_id,
                accepted_at=self._clock(),
                status="accepted",
            )
            return ProviderDispatchResult(
                provider="resend",
                disposition=DispatchDisposition.CONFIRMED,
                receipt=receipt,
                detail="Resend accepted the email",
            )
        if 400 <= response.status_code < 500:
            return ProviderDispatchResult(
                provider="resend",
                disposition=DispatchDisposition.FAILED_BEFORE_EFFECT,
                detail=f"Resend rejected the request with status {response.status_code}",
            )
        return ProviderDispatchResult(
            provider="resend",
            disposition=DispatchDisposition.OUTCOME_UNKNOWN,
            detail=f"Resend returned ambiguous status {response.status_code}",
        )

    async def reconcile(
        self,
        request: EmailDispatchRequest,
        provider_reference: str | None,
    ) -> ProviderReconciliationResult:
        if provider_reference is None:
            if self._clock() - request.authorized_at < self._idempotency_window:
                return ProviderReconciliationResult(
                    provider="resend",
                    disposition=ReconciliationDisposition.SAFE_TO_RETRY,
                    detail="Resend idempotency window permits replay with the same request key",
                )
            return ProviderReconciliationResult(
                provider="resend",
                disposition=ReconciliationDisposition.NEEDS_OPERATOR,
                detail="Resend idempotency window elapsed before reconciliation",
            )
        try:
            provider_reference = validate_provider_message_id(provider_reference)
        except ValueError:
            return ProviderReconciliationResult(
                provider="resend",
                disposition=ReconciliationDisposition.NEEDS_OPERATOR,
                detail="Resend provider reference is unsafe for receipt lookup",
            )

        try:
            response = await self._transport.request(
                method="GET",
                path=f"/emails/{provider_reference}",
                headers={},
                json_body=None,
            )
        except ResendTransportError:
            return ProviderReconciliationResult(
                provider="resend",
                disposition=ReconciliationDisposition.NEEDS_OPERATOR,
                provider_reference=provider_reference,
                detail="Resend receipt lookup did not produce a definitive result",
            )
        if response.status_code == 200:
            message_id = response.body.get("id")
            if message_id != provider_reference:
                return ProviderReconciliationResult(
                    provider="resend",
                    disposition=ReconciliationDisposition.NEEDS_OPERATOR,
                    provider_reference=provider_reference,
                    detail="Resend receipt lookup returned a mismatched reference",
                )
            status = response.body.get("last_event", "accepted")
            if not isinstance(status, str) or status not in {
                "accepted",
                "bounced",
                "cancelled",
                "clicked",
                "complained",
                "delivered",
                "delivery_delayed",
                "failed",
                "opened",
                "queued",
                "scheduled",
                "sent",
            }:
                status = "accepted"
            receipt = ProviderReceipt(
                provider="resend",
                message_id=provider_reference,
                accepted_at=self._clock(),
                status=status,
            )
            return ProviderReconciliationResult(
                provider="resend",
                disposition=ReconciliationDisposition.CONFIRMED,
                receipt=receipt,
                detail="Resend confirmed the provider receipt",
            )
        return ProviderReconciliationResult(
            provider="resend",
            disposition=ReconciliationDisposition.NEEDS_OPERATOR,
            provider_reference=provider_reference,
            detail=f"Resend receipt lookup returned status {response.status_code}",
        )
