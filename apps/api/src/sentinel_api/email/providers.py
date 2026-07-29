"""Email provider protocol and deterministic credential-free fake."""

from __future__ import annotations

from collections import deque
from enum import StrEnum
from typing import Protocol

from sentinel_api.email.models import (
    DispatchDisposition,
    EmailDispatchRequest,
    ProviderDispatchResult,
    ProviderReceipt,
    ProviderReconciliationResult,
    ReconciliationDisposition,
)


class EmailProvider(Protocol):
    async def dispatch(self, request: EmailDispatchRequest) -> ProviderDispatchResult:
        """Attempt one payload-bound provider dispatch."""

    async def reconcile(
        self,
        request: EmailDispatchRequest,
        provider_reference: str | None,
    ) -> ProviderReconciliationResult:
        """Resolve an ambiguous dispatch before any retry."""


class FakeProviderBehavior(StrEnum):
    CONFIRM = "confirm"
    FAIL_BEFORE_EFFECT = "fail_before_effect"
    TIMEOUT_BEFORE_EFFECT = "timeout_before_effect"
    AMBIGUOUS_CONFIRMED = "ambiguous_confirmed"
    AMBIGUOUS_NOT_SENT = "ambiguous_not_sent"
    AMBIGUOUS_UNRESOLVED = "ambiguous_unresolved"


class DeterministicFakeEmailProvider:
    """Scriptable provider that never performs I/O and deduplicates by request key."""

    def __init__(
        self,
        behaviors: tuple[FakeProviderBehavior, ...] = (FakeProviderBehavior.CONFIRM,),
    ) -> None:
        if not behaviors:
            raise ValueError("fake provider requires at least one behavior")
        self._behaviors = deque(behaviors)
        self._receipts: dict[str, ProviderReceipt] = {}
        self._unknown_behavior: dict[str, FakeProviderBehavior] = {}
        self.dispatch_calls: list[EmailDispatchRequest] = []
        self.reconciliation_calls: list[tuple[EmailDispatchRequest, str | None]] = []

    async def dispatch(self, request: EmailDispatchRequest) -> ProviderDispatchResult:
        self.dispatch_calls.append(request)
        existing = self._receipts.get(request.idempotency_key)
        if existing is not None:
            return ProviderDispatchResult(
                provider="fake",
                disposition=DispatchDisposition.CONFIRMED,
                receipt=existing,
                detail="Fake provider returned the existing idempotent receipt",
            )

        behavior = self._behaviors[0]
        if len(self._behaviors) > 1:
            behavior = self._behaviors.popleft()
        if behavior is FakeProviderBehavior.CONFIRM:
            receipt = self._receipt(request)
            self._receipts[request.idempotency_key] = receipt
            return ProviderDispatchResult(
                provider="fake",
                disposition=DispatchDisposition.CONFIRMED,
                receipt=receipt,
                detail="Fake provider accepted the message",
            )
        if behavior in {
            FakeProviderBehavior.FAIL_BEFORE_EFFECT,
            FakeProviderBehavior.TIMEOUT_BEFORE_EFFECT,
        }:
            return ProviderDispatchResult(
                provider="fake",
                disposition=DispatchDisposition.FAILED_BEFORE_EFFECT,
                detail="Fake provider failed before accepting the message",
            )

        self._unknown_behavior[request.idempotency_key] = behavior
        provider_reference = None
        if behavior is FakeProviderBehavior.AMBIGUOUS_CONFIRMED:
            receipt = self._receipt(request)
            self._receipts[request.idempotency_key] = receipt
            provider_reference = receipt.message_id
        return ProviderDispatchResult(
            provider="fake",
            disposition=DispatchDisposition.OUTCOME_UNKNOWN,
            provider_reference=provider_reference,
            detail="Fake provider outcome is ambiguous",
        )

    async def reconcile(
        self,
        request: EmailDispatchRequest,
        provider_reference: str | None,
    ) -> ProviderReconciliationResult:
        self.reconciliation_calls.append((request, provider_reference))
        receipt = self._receipts.get(request.idempotency_key)
        if receipt is not None:
            return ProviderReconciliationResult(
                provider="fake",
                disposition=ReconciliationDisposition.CONFIRMED,
                receipt=receipt,
                detail="Fake provider found the accepted message",
            )
        behavior = self._unknown_behavior.get(request.idempotency_key)
        if behavior is FakeProviderBehavior.AMBIGUOUS_NOT_SENT:
            return ProviderReconciliationResult(
                provider="fake",
                disposition=ReconciliationDisposition.SAFE_TO_RETRY,
                detail="Fake provider confirmed that no message was accepted",
            )
        return ProviderReconciliationResult(
            provider="fake",
            disposition=ReconciliationDisposition.NEEDS_OPERATOR,
            detail="Fake provider could not resolve the ambiguous outcome",
        )

    @staticmethod
    def _receipt(request: EmailDispatchRequest) -> ProviderReceipt:
        reference = f"fake-{request.idempotency_key[:24]}"
        return ProviderReceipt(
            provider="fake",
            message_id=reference,
            accepted_at=request.authorized_at,
            status="accepted",
        )
