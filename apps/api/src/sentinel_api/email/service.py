"""Authorized email orchestration across explicit external-effect outcomes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime

from pydantic import ValidationError

from sentinel_api.domain import ActionOutcomeState, utc_now
from sentinel_api.email.models import (
    ApprovedEmailPayload,
    DispatchDisposition,
    EmailDispatchRequest,
    EmailExecutionRecord,
    EmailMessage,
    ProviderDispatchResult,
    ProviderReconciliationResult,
    ReconciliationDisposition,
    normalize_email_address,
)
from sentinel_api.email.providers import EmailProvider
from sentinel_api.email.store import (
    EmailExecutionStore,
    ExecutionStateConflict,
)
from sentinel_api.protected_actions.broker import AuthorizedAction
from sentinel_api.protected_actions.canonical import canonical_json


class EmailAuthorizationError(RuntimeError):
    """Raised when an input did not cross the protected-action broker exactly."""


class ControlledRecipientError(EmailAuthorizationError):
    """Raised when approved bytes target anything except the current controlled mailbox."""


class EmailExecutionService:
    """The only boundary allowed to invoke an injected email provider."""

    def __init__(
        self,
        *,
        provider: EmailProvider,
        store: EmailExecutionStore,
        sender: str,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._provider = provider
        self._store = store
        self._sender = normalize_email_address(sender)
        self._clock = clock

    async def execute(
        self,
        authorized: AuthorizedAction,
        *,
        controlled_recipient: str,
    ) -> EmailExecutionRecord:
        request = self._request(authorized)
        current = await self._store.ensure_authorized(request, at=self._clock())
        if current.state not in {
            ActionOutcomeState.APPROVED,
            ActionOutcomeState.FAILED_BEFORE_EFFECT,
            ActionOutcomeState.SAFE_TO_RETRY,
        }:
            return current

        try:
            dispatching = await self._store.transition(
                request.action_intent_id,
                expected=current.state,
                next_state=ActionOutcomeState.DISPATCHING,
                at=self._clock(),
                detail="Email execution claimed for provider dispatch",
            )
        except ExecutionStateConflict:
            return await self._store.get(request.action_intent_id)

        try:
            self._enforce_controlled_recipient(request, controlled_recipient)
        except ControlledRecipientError as error:
            await self._store.transition(
                request.action_intent_id,
                expected=dispatching.state,
                next_state=ActionOutcomeState.FAILED_BEFORE_EFFECT,
                at=self._clock(),
                detail=str(error),
            )
            raise

        try:
            result = await self._provider.dispatch(request)
        except Exception:
            return await self._store.transition(
                request.action_intent_id,
                expected=ActionOutcomeState.DISPATCHING,
                next_state=ActionOutcomeState.OUTCOME_UNKNOWN,
                at=self._clock(),
                detail=(
                    "Email provider failed after dispatch began; outcome requires reconciliation"
                ),
            )
        return await self._record_dispatch_result(request, result)

    async def reconcile(
        self,
        authorized: AuthorizedAction,
    ) -> EmailExecutionRecord:
        request = self._request(authorized)
        current = await self._store.ensure_authorized(request, at=self._clock())
        if current.state is not ActionOutcomeState.OUTCOME_UNKNOWN:
            return current
        try:
            reconciling = await self._store.transition(
                request.action_intent_id,
                expected=ActionOutcomeState.OUTCOME_UNKNOWN,
                next_state=ActionOutcomeState.RECONCILING,
                at=self._clock(),
                detail="Reconciling ambiguous email provider outcome before retry",
                provider_reference=current.provider_reference,
            )
        except ExecutionStateConflict:
            return await self._store.get(request.action_intent_id)
        result = await self._provider.reconcile(request, reconciling.provider_reference)
        return await self._record_reconciliation_result(request, result)

    def _request(self, authorized: AuthorizedAction) -> EmailDispatchRequest:
        if not isinstance(authorized, AuthorizedAction):
            raise EmailAuthorizationError(
                "email execution requires an AuthorizedAction from the protected-action broker"
            )
        canonical_bytes = authorized.canonical_payload.encode()
        if hashlib.sha256(canonical_bytes).hexdigest() != authorized.intent.payload_fingerprint:
            raise EmailAuthorizationError("authorized email payload fingerprint does not match")
        try:
            raw = json.loads(authorized.canonical_payload)
            if canonical_json(raw) != canonical_bytes:
                raise EmailAuthorizationError("authorized email payload is not canonical JSON")
            payload = ApprovedEmailPayload.model_validate(raw)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as error:
            if isinstance(error, EmailAuthorizationError):
                raise
            raise EmailAuthorizationError("authorized email payload is invalid") from error
        return EmailDispatchRequest(
            action_intent_id=authorized.intent.id,
            idempotency_key=authorized.intent.idempotency_key,
            payload_fingerprint=authorized.intent.payload_fingerprint,
            authorized_at=authorized.intent.created_at,
            message=EmailMessage(
                sender=self._sender,
                recipient=payload.to,
                subject=payload.subject,
                text_body=payload.body,
            ),
        )

    @staticmethod
    def _enforce_controlled_recipient(
        request: EmailDispatchRequest,
        controlled_recipient: str,
    ) -> None:
        try:
            controlled = normalize_email_address(controlled_recipient)
        except ValueError as error:
            raise ControlledRecipientError(
                "current policy does not provide a valid controlled recipient"
            ) from error
        if request.message.recipient != controlled:
            raise ControlledRecipientError(
                "approved email recipient is outside the controlled recipient policy"
            )

    async def _record_dispatch_result(
        self,
        request: EmailDispatchRequest,
        result: ProviderDispatchResult,
    ) -> EmailExecutionRecord:
        state_by_disposition = {
            DispatchDisposition.CONFIRMED: ActionOutcomeState.CONFIRMED,
            DispatchDisposition.FAILED_BEFORE_EFFECT: ActionOutcomeState.FAILED_BEFORE_EFFECT,
            DispatchDisposition.OUTCOME_UNKNOWN: ActionOutcomeState.OUTCOME_UNKNOWN,
        }
        return await self._store.transition(
            request.action_intent_id,
            expected=ActionOutcomeState.DISPATCHING,
            next_state=state_by_disposition[result.disposition],
            at=self._clock(),
            detail=result.detail,
            provider=result.provider,
            provider_reference=result.provider_reference,
            receipt=result.receipt,
        )

    async def _record_reconciliation_result(
        self,
        request: EmailDispatchRequest,
        result: ProviderReconciliationResult,
    ) -> EmailExecutionRecord:
        state_by_disposition = {
            ReconciliationDisposition.CONFIRMED: ActionOutcomeState.CONFIRMED,
            ReconciliationDisposition.SAFE_TO_RETRY: ActionOutcomeState.SAFE_TO_RETRY,
            ReconciliationDisposition.NEEDS_OPERATOR: ActionOutcomeState.NEEDS_OPERATOR,
        }
        return await self._store.transition(
            request.action_intent_id,
            expected=ActionOutcomeState.RECONCILING,
            next_state=state_by_disposition[result.disposition],
            at=self._clock(),
            detail=result.detail,
            provider=result.provider,
            provider_reference=result.provider_reference,
            receipt=result.receipt,
        )
