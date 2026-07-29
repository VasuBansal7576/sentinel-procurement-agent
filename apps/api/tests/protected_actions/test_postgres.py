"""Real PostgreSQL proofs for durable, atomic protected-action authorization."""

import asyncio
import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection

from sentinel_api.domain import OrganizationPolicy, RequestPolicyOverlay
from sentinel_api.domain.actions import ProposalStatus
from sentinel_api.domain.policy import ProtectedAction, resolve_policy
from sentinel_api.persistence import NewRun, PostgresEventStore
from sentinel_api.protected_actions import (
    AuthorizationError,
    AuthorizedAction,
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
async def durable_broker() -> AsyncIterator[tuple[PostgresEventStore, PostgresApprovalBroker]]:
    database_url = _test_database_url()
    connection = await AsyncConnection.connect(database_url)
    await connection.execute("DROP SCHEMA IF EXISTS sentinel CASCADE")
    await connection.commit()
    await connection.close()

    event_store = PostgresEventStore.from_url(database_url, max_size=10)
    await event_store.open()
    assert await event_store.migrate() == ("0001", "0002", "0003", "0004")
    try:
        yield event_store, PostgresApprovalBroker(event_store.connection_pool)
    finally:
        await event_store.close()


def _policy():
    organization = OrganizationPolicy(
        organization_id=uuid4(),
        protected_actions=frozenset({ProtectedAction.EMAIL_SEND}),
        controlled_recipient="demo@example.test",
    )
    return resolve_policy(
        organization,
        RequestPolicyOverlay(allowed_actions=frozenset({ProtectedAction.EMAIL_SEND})),
    )


async def _approved(
    event_store: PostgresEventStore,
    broker: PostgresApprovalBroker,
):
    run = NewRun(title="Durable protected action")
    await event_store.create_run(run)
    effective_policy = _policy()
    proposal, version = await broker.create_proposal(
        run_id=run.run_id,
        request_revision_id=uuid4(),
        action_type="email.send",
        payload={
            "to": "demo@example.test",
            "subject": "Controlled RFQ",
            "body": "Please review the attached request.",
        },
        attachment_artifact_ids=(uuid4(),),
        attachment_sha256=("a" * 64,),
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
    context = CommitContext(
        executor_id=uuid4(),
        capabilities=frozenset({"protected_action.execute"}),
        organization_policy_id=effective_policy.organization_policy_id,
        organization_revision=effective_policy.organization_revision,
        proposal_version=version.version,
        canonical_payload_sha256=version.canonical_payload_sha256,
        attachment_sha256=version.attachment_sha256,
    )
    return proposal, version, permit, effective_policy, context


async def test_concurrent_commit_consumes_a_durable_permit_exactly_once(
    durable_broker: tuple[PostgresEventStore, PostgresApprovalBroker],
) -> None:
    event_store, broker = durable_broker
    _, _, permit, effective_policy, context = await _approved(event_store, broker)

    results = await asyncio.gather(
        *(
            broker.authorize_and_consume(
                permit_id=permit.id,
                effective_policy=effective_policy,
                context=context,
            )
            for _ in range(2)
        ),
        return_exceptions=True,
    )

    assert sum(isinstance(result, AuthorizedAction) for result in results) == 1
    errors = [result for result in results if isinstance(result, AuthorizationError)]
    assert len(errors) == 1
    assert "already been consumed" in str(errors[0])
    async with event_store.connection_pool.connection() as connection:
        cursor = await connection.execute("SELECT count(*) AS count FROM sentinel.action_intents")
        row = await cursor.fetchone()
        outcome_cursor = await connection.execute("SELECT state FROM sentinel.action_outcomes")
        outcome = await outcome_cursor.fetchone()
    assert row == {"count": 1}
    assert outcome == {"state": "approved"}
    assert (await broker.get_proposal(permit.proposal_id)).status is ProposalStatus.AUTHORIZED


async def test_proposal_and_permit_survive_pool_restart(
    durable_broker: tuple[PostgresEventStore, PostgresApprovalBroker],
) -> None:
    event_store, broker = durable_broker
    proposal, version, permit, effective_policy, context = await _approved(event_store, broker)
    database_url = _test_database_url()

    reopened_broker = PostgresApprovalBroker.from_url(database_url)
    await reopened_broker.open()
    try:
        assert await reopened_broker.get_proposal(proposal.id) == proposal.model_copy(
            update={"status": ProposalStatus.APPROVED}
        )
        assert await reopened_broker.get_version(proposal.id, version.version) == version
        authorized = await reopened_broker.authorize_and_consume(
            permit_id=permit.id,
            effective_policy=effective_policy,
            context=context,
        )
        assert authorized.intent.permit_id == permit.id
    finally:
        await reopened_broker.close()
