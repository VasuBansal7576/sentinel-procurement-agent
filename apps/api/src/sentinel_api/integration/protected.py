"""Protected email execution boundary for fake and live providers."""

from __future__ import annotations

from uuid import UUID

from sentinel_api.config import Settings
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
    EmailProvider,
    ResendEmailProvider,
)
from sentinel_api.email.http_transport import HttpResendTransport
from sentinel_api.integration.brokers import ApprovalBrokerAdapter, await_result
from sentinel_api.integration.planner import deterministic_id
from sentinel_api.protected_actions import CommitContext


def controlled_policy(run_id: UUID, controlled_recipient: str) -> EffectivePolicy:
    organization = OrganizationPolicy(
        id=deterministic_id(run_id, "organization-policy"),
        organization_id=deterministic_id(run_id, "organization"),
        protected_actions=frozenset({ProtectedAction.EMAIL_SEND}),
        controlled_recipient=controlled_recipient,
    )
    return resolve_policy(
        organization,
        RequestPolicyOverlay(allowed_actions=frozenset({ProtectedAction.EMAIL_SEND})),
    )


def build_email_provider(settings: Settings) -> EmailProvider:
    if settings.email_provider == "fake":
        return DeterministicFakeEmailProvider()
    if settings.email_provider == "resend":
        assert settings.resend_api_key is not None
        return ResendEmailProvider(HttpResendTransport(api_key=settings.resend_api_key))
    raise ValueError(f"unsupported email provider: {settings.email_provider}")


class ProtectedEmailBoundary:
    """Consumes exact approval and dispatches only through EmailExecutionService."""

    def __init__(
        self,
        *,
        broker: ApprovalBrokerAdapter,
        store: EmailExecutionStore,
        provider: EmailProvider,
        sender: str,
        controlled_recipient: str,
        live_dispatch_enabled: bool,
    ) -> None:
        self.provider = provider
        self.controlled_recipient = controlled_recipient
        self.live_dispatch_enabled = live_dispatch_enabled
        self._broker = broker
        self._service = EmailExecutionService(
            provider=provider,
            store=store,
            sender=sender,
        )

    async def execute(
        self,
        *,
        run_id: UUID,
        permit_id: UUID,
        proposal_id: UUID,
    ) -> EmailExecutionRecord:
        policy = controlled_policy(run_id, self.controlled_recipient)
        proposal = await await_result(self._broker.get_proposal(proposal_id))
        version = await await_result(
            self._broker.get_version(proposal_id, proposal.current_version)
        )
        authorized = await await_result(
            self._broker.authorize_and_consume(
                permit_id=permit_id,
                effective_policy=policy,
                context=CommitContext(
                    executor_id=deterministic_id(run_id, "protected-email-executor"),
                    capabilities=frozenset({"protected_action.execute"}),
                    organization_policy_id=policy.organization_policy_id,
                    organization_revision=policy.organization_revision,
                    proposal_version=version.version,
                    canonical_payload_sha256=version.canonical_payload_sha256,
                    attachment_sha256=version.attachment_sha256,
                ),
            )
        )
        return await self._service.execute(
            authorized,
            controlled_recipient=self.controlled_recipient,
        )


# Backward-compatible name used by older tests.
class FakeProtectedEmailBoundary(ProtectedEmailBoundary):
    def __init__(
        self,
        *,
        broker: ApprovalBrokerAdapter,
        store: EmailExecutionStore,
        provider: DeterministicFakeEmailProvider | None = None,
        controlled_recipient: str = "procurement-demo@example.test",
        sender: str = "sentinel@example.test",
    ) -> None:
        super().__init__(
            broker=broker,
            store=store,
            provider=provider or DeterministicFakeEmailProvider(),
            sender=sender,
            controlled_recipient=controlled_recipient,
            live_dispatch_enabled=False,
        )
