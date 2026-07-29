"""Execution and reconciliation proofs for the protected email sink."""

import asyncio
import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from sentinel_api.domain import (
    ActionIntent,
    ActionOutcomeState,
    RiskClass,
    ToolMetadata,
    ToolNamespace,
)
from sentinel_api.email import (
    ControlledRecipientError,
    DeterministicFakeEmailProvider,
    EmailAuthorizationError,
    EmailExecutionService,
    FakeProviderBehavior,
    InMemoryEmailExecutionStore,
)
from sentinel_api.protected_actions.broker import AuthorizedAction
from sentinel_api.protected_actions.canonical import canonical_json
from sentinel_api.research import ResearchCapability, ResearchGrant

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
CONTROLLED_RECIPIENT = "demo@example.test"


def _authorized(
    *,
    recipient: str = CONTROLLED_RECIPIENT,
    subject: str = "Controlled request",
    body: str = "Please review the approved request.",
) -> AuthorizedAction:
    canonical = canonical_json({"to": recipient, "subject": subject, "body": body})
    fingerprint = hashlib.sha256(canonical).hexdigest()
    return AuthorizedAction(
        intent=ActionIntent(
            proposal_id=uuid4(),
            proposal_version=1,
            permit_id=uuid4(),
            idempotency_key=hashlib.sha256(uuid4().bytes).hexdigest(),
            payload_fingerprint=fingerprint,
            created_at=NOW,
        ),
        canonical_payload=canonical.decode(),
        permit_nonce=uuid4(),
    )


def _service(
    provider: DeterministicFakeEmailProvider,
    store: InMemoryEmailExecutionStore | None = None,
) -> tuple[EmailExecutionService, InMemoryEmailExecutionStore]:
    execution_store = store or InMemoryEmailExecutionStore()
    return (
        EmailExecutionService(
            provider=provider,
            store=execution_store,
            sender="sentinel@example.test",
            clock=lambda: NOW,
        ),
        execution_store,
    )


@pytest.mark.asyncio
async def test_confirmed_send_maps_receipt_and_audit_without_message_content() -> None:
    provider = DeterministicFakeEmailProvider()
    service, _ = _service(provider)
    authorized = _authorized(body="Sensitive approved content")

    record = await service.execute(
        authorized,
        controlled_recipient=CONTROLLED_RECIPIENT,
    )

    assert record.state is ActionOutcomeState.CONFIRMED
    assert record.receipt is not None
    assert record.receipt.provider == "fake"
    assert record.provider_reference == record.receipt.message_id
    assert record.attempts == 1
    assert [event.state for event in record.audit_events] == [
        ActionOutcomeState.APPROVED,
        ActionOutcomeState.DISPATCHING,
        ActionOutcomeState.CONFIRMED,
    ]
    serialized_audit = repr(record.audit_events)
    assert "Sensitive approved content" not in serialized_audit
    assert authorized.intent.idempotency_key not in serialized_audit


@pytest.mark.asyncio
async def test_duplicate_execution_is_suppressed_even_when_calls_race() -> None:
    provider = DeterministicFakeEmailProvider()
    service, _ = _service(provider)
    authorized = _authorized()

    first, second = await asyncio.gather(
        service.execute(authorized, controlled_recipient=CONTROLLED_RECIPIENT),
        service.execute(authorized, controlled_recipient=CONTROLLED_RECIPIENT),
    )

    assert len(provider.dispatch_calls) == 1
    assert {first.state, second.state} <= {
        ActionOutcomeState.DISPATCHING,
        ActionOutcomeState.CONFIRMED,
    }
    final = await service.execute(
        authorized,
        controlled_recipient=CONTROLLED_RECIPIENT,
    )
    assert final.state is ActionOutcomeState.CONFIRMED
    assert len(provider.dispatch_calls) == 1


@pytest.mark.asyncio
async def test_same_intent_cannot_be_replayed_with_changed_provider_request() -> None:
    provider = DeterministicFakeEmailProvider((FakeProviderBehavior.AMBIGUOUS_NOT_SENT,))
    store = InMemoryEmailExecutionStore()
    original, _ = _service(provider, store)
    changed_sender = EmailExecutionService(
        provider=provider,
        store=store,
        sender="changed@example.test",
        clock=lambda: NOW,
    )
    authorized = _authorized()

    await original.execute(
        authorized,
        controlled_recipient=CONTROLLED_RECIPIENT,
    )
    with pytest.raises(ValueError, match="different email request bytes"):
        await changed_sender.reconcile(authorized)


@pytest.mark.asyncio
async def test_timeout_known_to_precede_effect_is_safe_failure() -> None:
    provider = DeterministicFakeEmailProvider((FakeProviderBehavior.TIMEOUT_BEFORE_EFFECT,))
    service, _ = _service(provider)

    record = await service.execute(
        _authorized(),
        controlled_recipient=CONTROLLED_RECIPIENT,
    )

    assert record.state is ActionOutcomeState.FAILED_BEFORE_EFFECT
    assert record.receipt is None


@pytest.mark.asyncio
async def test_ambiguous_timeout_cannot_dispatch_again_before_reconciliation() -> None:
    provider = DeterministicFakeEmailProvider(
        (
            FakeProviderBehavior.AMBIGUOUS_NOT_SENT,
            FakeProviderBehavior.CONFIRM,
        )
    )
    service, _ = _service(provider)
    authorized = _authorized()

    unknown = await service.execute(
        authorized,
        controlled_recipient=CONTROLLED_RECIPIENT,
    )
    suppressed = await service.execute(
        authorized,
        controlled_recipient=CONTROLLED_RECIPIENT,
    )

    assert unknown.state is ActionOutcomeState.OUTCOME_UNKNOWN
    assert suppressed.state is ActionOutcomeState.OUTCOME_UNKNOWN
    assert len(provider.dispatch_calls) == 1

    retriable = await service.reconcile(authorized)
    confirmed = await service.execute(
        authorized,
        controlled_recipient=CONTROLLED_RECIPIENT,
    )

    assert retriable.state is ActionOutcomeState.SAFE_TO_RETRY
    assert confirmed.state is ActionOutcomeState.CONFIRMED
    assert len(provider.reconciliation_calls) == 1
    assert len(provider.dispatch_calls) == 2
    assert provider.dispatch_calls[0].idempotency_key == provider.dispatch_calls[1].idempotency_key


@pytest.mark.asyncio
async def test_reconciliation_finds_receipt_after_ambiguous_acceptance() -> None:
    provider = DeterministicFakeEmailProvider((FakeProviderBehavior.AMBIGUOUS_CONFIRMED,))
    service, _ = _service(provider)
    authorized = _authorized()

    unknown = await service.execute(
        authorized,
        controlled_recipient=CONTROLLED_RECIPIENT,
    )
    reconciled = await service.reconcile(authorized)

    assert unknown.state is ActionOutcomeState.OUTCOME_UNKNOWN
    assert reconciled.state is ActionOutcomeState.CONFIRMED
    assert reconciled.receipt is not None
    assert reconciled.receipt.message_id == unknown.provider_reference
    assert len(provider.dispatch_calls) == 1


@pytest.mark.asyncio
async def test_unresolved_ambiguity_requires_operator() -> None:
    provider = DeterministicFakeEmailProvider((FakeProviderBehavior.AMBIGUOUS_UNRESOLVED,))
    service, _ = _service(provider)
    authorized = _authorized()

    await service.execute(authorized, controlled_recipient=CONTROLLED_RECIPIENT)
    record = await service.reconcile(authorized)

    assert record.state is ActionOutcomeState.NEEDS_OPERATOR
    assert (
        await service.execute(
            authorized,
            controlled_recipient=CONTROLLED_RECIPIENT,
        )
    ).state is ActionOutcomeState.NEEDS_OPERATOR
    assert len(provider.dispatch_calls) == 1


@pytest.mark.asyncio
async def test_controlled_recipient_is_rechecked_at_the_sink() -> None:
    provider = DeterministicFakeEmailProvider()
    service, store = _service(provider)
    authorized = _authorized(recipient="supplier@example.test")

    with pytest.raises(ControlledRecipientError, match="controlled recipient"):
        await service.execute(
            authorized,
            controlled_recipient=CONTROLLED_RECIPIENT,
        )

    record = await store.get(authorized.intent.id)
    assert record.state is ActionOutcomeState.FAILED_BEFORE_EFFECT
    assert provider.dispatch_calls == []


@pytest.mark.asyncio
async def test_payload_fingerprint_is_rechecked_before_provider_access() -> None:
    provider = DeterministicFakeEmailProvider()
    service, _ = _service(provider)
    authorized = _authorized().model_copy(
        update={"canonical_payload": '{"body":"changed","subject":"x","to":"demo@example.test"}'}
    )

    with pytest.raises(EmailAuthorizationError, match="fingerprint"):
        await service.execute(
            authorized,
            controlled_recipient=CONTROLLED_RECIPIENT,
        )

    assert provider.dispatch_calls == []


@pytest.mark.asyncio
async def test_research_grant_cannot_be_used_to_access_email_sink() -> None:
    provider = DeterministicFakeEmailProvider()
    service, _ = _service(provider)
    research_grant = ResearchGrant(
        run_id=uuid4(),
        actor_id=uuid4(),
        capabilities=frozenset({ResearchCapability.SEARCH}),
        allowed_domains=frozenset({"example.test"}),
    )

    with pytest.raises(EmailAuthorizationError, match="AuthorizedAction"):
        await service.execute(  # type: ignore[arg-type]
            research_grant,
            controlled_recipient=CONTROLLED_RECIPIENT,
        )

    assert provider.dispatch_calls == []


def test_research_capabilities_cannot_receive_email_sink_metadata() -> None:
    email_sink = ToolMetadata(
        namespace=ToolNamespace.EMAIL,
        name="execute_authorized_email",
        version="1.0.0",
        risk_class=RiskClass.EXTERNAL_SEND,
        allowed_actor_capabilities=frozenset({"protected_action.execute"}),
        timeout_seconds=30,
        idempotent=True,
        accepts_untrusted_data=False,
        protected_sink=True,
    )

    with pytest.raises(ValueError, match="read-only, non-protected"):
        ResearchGrant(
            run_id=uuid4(),
            actor_id=uuid4(),
            capabilities=frozenset({ResearchCapability.SEARCH}),
            allowed_domains=frozenset({"example.test"}),
            tools=(email_sink,),
        )
