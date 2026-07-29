"""Fake-only protected email execution proof for the integration boundary."""

from uuid import UUID

from sentinel_api.domain import (
    EffectivePolicy,
    OrganizationPolicy,
    RequestPolicyOverlay,
    resolve_policy,
)
from sentinel_api.domain.policy import ProtectedAction
from sentinel_api.email import (
    DeterministicFakeEmailProvider,
    EmailExecutionRecord,
    EmailExecutionService,
    EmailExecutionStore,
)
from sentinel_api.integration.brokers import ApprovalBrokerAdapter, await_result
from sentinel_api.integration.planner import deterministic_id
from sentinel_api.protected_actions import CommitContext


def controlled_policy(run_id: UUID) -> EffectivePolicy:
    organization = OrganizationPolicy(
        id=deterministic_id(run_id, "organization-policy"),
        organization_id=deterministic_id(run_id, "organization"),
        protected_actions=frozenset({ProtectedAction.EMAIL_SEND}),
        controlled_recipient="procurement-demo@example.test",
    )
    return resolve_policy(
        organization,
        RequestPolicyOverlay(allowed_actions=frozenset({ProtectedAction.EMAIL_SEND})),
    )


class FakeProtectedEmailBoundary:
    """Consumes exact approval and dispatches only to the deterministic fake."""

    def __init__(
        self,
        *,
        broker: ApprovalBrokerAdapter,
        store: EmailExecutionStore,
        provider: DeterministicFakeEmailProvider | None = None,
    ) -> None:
        self.provider = provider or DeterministicFakeEmailProvider()
        self._broker = broker
        self._service = EmailExecutionService(
            provider=self.provider,
            store=store,
            sender="sentinel@example.test",
        )

    async def execute(
        self,
        *,
        run_id: UUID,
        permit_id: UUID,
        proposal_id: UUID,
    ) -> EmailExecutionRecord:
        policy = controlled_policy(run_id)
        proposal = await await_result(self._broker.get_proposal(proposal_id))
        version = await await_result(
            self._broker.get_version(proposal_id, proposal.current_version)
        )
        authorized = await await_result(
            self._broker.authorize_and_consume(
                permit_id=permit_id,
                effective_policy=policy,
                context=CommitContext(
                    executor_id=deterministic_id(run_id, "fake-email-executor"),
                    capabilities=frozenset({"protected_action.execute"}),
                    organization_policy_id=policy.organization_policy_id,
                    organization_revision=policy.organization_revision,
                    proposal_version=version.version,
                    canonical_payload_sha256=version.canonical_payload_sha256,
                    attachment_sha256=version.attachment_sha256,
                ),
            )
        )
        assert policy.controlled_recipient is not None
        return await self._service.execute(
            authorized,
            controlled_recipient=policy.controlled_recipient,
        )
