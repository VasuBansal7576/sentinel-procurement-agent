"""Real PostgreSQL proofs for protected email execution and deduplication."""

import asyncio
import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection

from sentinel_api.domain import OrganizationPolicy, RequestPolicyOverlay
from sentinel_api.domain.policy import ProtectedAction, resolve_policy
from sentinel_api.email import (
    DeterministicFakeEmailProvider,
    EmailExecutionService,
    PostgresEmailExecutionStore,
)
from sentinel_api.persistence import NewRun, PostgresEventStore
from sentinel_api.protected_actions import (
    CommitContext,
    PolicyDecision,
    PostgresApprovalBroker,
)

pytestmark = pytest.mark.asyncio


def _test_database_url() -> str:
    value = os.getenv("SENTINEL_TEST_DATABASE_URL")
    if value is None:
        pytest.skip("set SENTINEL_TEST_DATABASE_URL to run PostgreSQL integration tests")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest_asyncio.fixture
async def event_store() -> AsyncIterator[PostgresEventStore]:
    database_url = _test_database_url()
    connection = await AsyncConnection.connect(database_url)
    await connection.execute("DROP SCHEMA IF EXISTS sentinel CASCADE")
    await connection.commit()
    await connection.close()

    store = PostgresEventStore.from_url(database_url, max_size=10)
    await store.open()
    assert await store.migrate() == ("0001", "0002", "0003", "0004", "0005")
    try:
        yield store
    finally:
        await store.close()


async def _authorized_email(event_store: PostgresEventStore):
    broker = PostgresApprovalBroker(event_store.connection_pool)
    run = NewRun(title="Controlled durable email")
    await event_store.create_run(run)
    organization = OrganizationPolicy(
        organization_id=uuid4(),
        protected_actions=frozenset({ProtectedAction.EMAIL_SEND}),
        controlled_recipient="demo@example.test",
    )
    effective_policy = resolve_policy(
        organization,
        RequestPolicyOverlay(allowed_actions=frozenset({ProtectedAction.EMAIL_SEND})),
    )
    proposal, version = await broker.create_proposal(
        run_id=run.run_id,
        request_revision_id=uuid4(),
        action_type="email.send",
        payload={
            "to": "demo@example.test",
            "subject": "Controlled RFQ",
            "body": "Please review the attached request.",
        },
    )
    permit = await broker.issue_permit(
        proposal_id=proposal.id,
        proposal_version=version.version,
        expected_payload_sha256=version.canonical_payload_sha256,
        expected_attachment_sha256=version.attachment_sha256,
        policy_decision=PolicyDecision(
            action=ProtectedAction.EMAIL_SEND,
            allowed=True,
            reason="Controlled demonstration send",
            organization_policy_id=effective_policy.organization_policy_id,
            organization_revision=effective_policy.organization_revision,
        ),
        effective_policy=effective_policy,
        approver_id=uuid4(),
    )
    authorized = await broker.authorize_and_consume(
        permit_id=permit.id,
        effective_policy=effective_policy,
        context=CommitContext(
            executor_id=uuid4(),
            capabilities=frozenset({"protected_action.execute"}),
            organization_policy_id=effective_policy.organization_policy_id,
            organization_revision=effective_policy.organization_revision,
            proposal_version=version.version,
            canonical_payload_sha256=version.canonical_payload_sha256,
            attachment_sha256=version.attachment_sha256,
        ),
    )
    return authorized


async def test_concurrent_dispatch_is_persisted_exactly_once_across_store_instances(
    event_store: PostgresEventStore,
) -> None:
    authorized = await _authorized_email(event_store)
    provider = DeterministicFakeEmailProvider()
    first_store = PostgresEmailExecutionStore(event_store.connection_pool)
    second_store = PostgresEmailExecutionStore(event_store.connection_pool)
    first_service = EmailExecutionService(
        provider=provider,
        store=first_store,
        sender="sentinel@example.test",
    )
    second_service = EmailExecutionService(
        provider=provider,
        store=second_store,
        sender="sentinel@example.test",
    )

    await asyncio.gather(
        first_service.execute(
            authorized,
            controlled_recipient="demo@example.test",
        ),
        second_service.execute(
            authorized,
            controlled_recipient="demo@example.test",
        ),
    )

    persisted = await PostgresEmailExecutionStore(event_store.connection_pool).get(
        authorized.intent.id
    )
    assert persisted.state.value == "confirmed"
    assert persisted.attempts == 1
    assert persisted.receipt is not None
    assert len(provider.dispatch_calls) == 1
    serialized_audit = repr(persisted.audit_events)
    assert "Please review the attached request" not in serialized_audit
    assert authorized.intent.idempotency_key not in serialized_audit
