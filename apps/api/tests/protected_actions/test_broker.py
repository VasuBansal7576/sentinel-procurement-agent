from datetime import timedelta
from uuid import uuid4

import pytest

from sentinel_api.domain import OrganizationPolicy, RequestPolicyOverlay, utc_now
from sentinel_api.domain.actions import ProposalStatus
from sentinel_api.domain.policy import ProtectedAction, resolve_policy
from sentinel_api.protected_actions import (
    ApprovalBroker,
    AuthorizationError,
    CommitContext,
    PolicyDecision,
)


def policy(recipient: str = "demo@example.test"):
    organization = OrganizationPolicy(
        organization_id=uuid4(),
        protected_actions=frozenset({ProtectedAction.EMAIL_SEND}),
        controlled_recipient=recipient,
    )
    overlay = RequestPolicyOverlay(allowed_actions=frozenset({ProtectedAction.EMAIL_SEND}))
    return resolve_policy(organization, overlay)


def decision(effective_policy, *, allowed: bool = True) -> PolicyDecision:
    return PolicyDecision(
        action=ProtectedAction.EMAIL_SEND,
        allowed=allowed,
        reason="Controlled RFQ send is permitted" if allowed else "Denied by policy",
        organization_policy_id=effective_policy.organization_policy_id,
        organization_revision=effective_policy.organization_revision,
    )


def proposal(broker: ApprovalBroker, recipient: str = "demo@example.test"):
    return broker.create_proposal(
        run_id=uuid4(),
        request_revision_id=uuid4(),
        action_type="email.send",
        payload={
            "to": recipient,
            "subject": "Request for quotation",
            "body": "Please review the attached controlled demonstration RFQ.",
        },
        attachment_artifact_ids=(uuid4(),),
        attachment_sha256=("a" * 64,),
    )


def approve(broker: ApprovalBroker, effective_policy):
    created, version = proposal(broker)
    permit = broker.issue_permit(
        proposal_id=created.id,
        proposal_version=version.version,
        expected_payload_sha256=version.canonical_payload_sha256,
        expected_attachment_sha256=version.attachment_sha256,
        policy_decision=decision(effective_policy),
        effective_policy=effective_policy,
        approver_id=uuid4(),
    )
    return created, version, permit


def commit_context(effective_policy, version) -> CommitContext:
    return CommitContext(
        executor_id=uuid4(),
        capabilities=frozenset({"protected_action.execute"}),
        organization_policy_id=effective_policy.organization_policy_id,
        organization_revision=effective_policy.organization_revision,
        proposal_version=version.version,
        canonical_payload_sha256=version.canonical_payload_sha256,
        attachment_sha256=version.attachment_sha256,
    )


def test_exact_current_version_can_be_approved_and_consumed_once() -> None:
    broker = ApprovalBroker()
    effective_policy = policy()
    _, version, permit = approve(broker, effective_policy)

    authorized = broker.authorize_and_consume(
        permit_id=permit.id,
        effective_policy=effective_policy,
        context=commit_context(effective_policy, version),
    )

    assert authorized.intent.payload_fingerprint == version.canonical_payload_sha256
    assert broker.get_proposal(permit.proposal_id).status is ProposalStatus.AUTHORIZED
    with pytest.raises(AuthorizationError, match="already been consumed"):
        broker.authorize_and_consume(
            permit_id=permit.id,
            effective_policy=effective_policy,
            context=commit_context(effective_policy, version),
        )


def test_edit_after_approval_invalidates_old_permit() -> None:
    broker = ApprovalBroker()
    effective_policy = policy()
    created, version, permit = approve(broker, effective_policy)

    _, edited, diff = broker.edit_proposal(
        created.id,
        payload={
            "to": "demo@example.test",
            "subject": "Updated request for quotation",
            "body": "Updated exact bytes",
        },
    )

    assert edited.version == 2
    assert diff.changed_fields == ("body", "subject")
    with pytest.raises(AuthorizationError, match="edited after approval"):
        broker.authorize_and_consume(
            permit_id=permit.id,
            effective_policy=effective_policy,
            context=commit_context(effective_policy, version),
        )


def test_preview_digest_mismatch_is_rejected() -> None:
    broker = ApprovalBroker()
    effective_policy = policy()
    created, version = proposal(broker)

    with pytest.raises(AuthorizationError, match="preview"):
        broker.issue_permit(
            proposal_id=created.id,
            proposal_version=1,
            expected_payload_sha256="f" * 64,
            expected_attachment_sha256=version.attachment_sha256,
            policy_decision=decision(effective_policy),
            effective_policy=effective_policy,
            approver_id=uuid4(),
        )


def test_recipient_outside_controlled_allowlist_is_rejected() -> None:
    broker = ApprovalBroker()
    effective_policy = policy()
    created, version = proposal(broker, "supplier@example.com")

    with pytest.raises(AuthorizationError, match="controlled allowlist"):
        broker.issue_permit(
            proposal_id=created.id,
            proposal_version=1,
            expected_payload_sha256=version.canonical_payload_sha256,
            expected_attachment_sha256=version.attachment_sha256,
            policy_decision=decision(effective_policy),
            effective_policy=effective_policy,
            approver_id=uuid4(),
        )


def test_expired_permit_is_rejected_at_commit_time() -> None:
    broker = ApprovalBroker()
    effective_policy = policy()
    created, version = proposal(broker)
    issued_at = utc_now()
    permit = broker.issue_permit(
        proposal_id=created.id,
        proposal_version=1,
        expected_payload_sha256=version.canonical_payload_sha256,
        expected_attachment_sha256=version.attachment_sha256,
        policy_decision=decision(effective_policy),
        effective_policy=effective_policy,
        approver_id=uuid4(),
        ttl=timedelta(seconds=1),
        now=issued_at,
    )

    with pytest.raises(AuthorizationError, match="expired"):
        broker.authorize_and_consume(
            permit_id=permit.id,
            effective_policy=effective_policy,
            context=commit_context(effective_policy, version),
            now=issued_at + timedelta(seconds=2),
        )


def test_executor_capability_is_rechecked_at_commit_time() -> None:
    broker = ApprovalBroker()
    effective_policy = policy()
    _, version, permit = approve(broker, effective_policy)
    context = commit_context(effective_policy, version).model_copy(
        update={"capabilities": frozenset({"research"})}
    )

    with pytest.raises(AuthorizationError, match="lacks protected-action"):
        broker.authorize_and_consume(
            permit_id=permit.id,
            effective_policy=effective_policy,
            context=context,
        )


def test_policy_decision_must_match_the_proposed_action() -> None:
    broker = ApprovalBroker()
    organization = OrganizationPolicy(
        organization_id=uuid4(),
        protected_actions=frozenset(
            {
                ProtectedAction.EMAIL_SEND,
                ProtectedAction.FILE_UPLOAD,
            }
        ),
        controlled_recipient="demo@example.test",
    )
    effective_policy = resolve_policy(
        organization,
        RequestPolicyOverlay(
            allowed_actions=frozenset(
                {
                    ProtectedAction.EMAIL_SEND,
                    ProtectedAction.FILE_UPLOAD,
                }
            )
        ),
    )
    created, version = proposal(broker)
    wrong_decision = PolicyDecision(
        action=ProtectedAction.FILE_UPLOAD,
        allowed=True,
        reason="File uploads are allowed",
        organization_policy_id=effective_policy.organization_policy_id,
        organization_revision=effective_policy.organization_revision,
    )

    with pytest.raises(AuthorizationError, match="does not authorize"):
        broker.issue_permit(
            proposal_id=created.id,
            proposal_version=version.version,
            expected_payload_sha256=version.canonical_payload_sha256,
            expected_attachment_sha256=version.attachment_sha256,
            policy_decision=wrong_decision,
            effective_policy=effective_policy,
            approver_id=uuid4(),
        )


def test_policy_revision_change_invalidates_an_existing_permit() -> None:
    broker = ApprovalBroker()
    effective_policy = policy()
    _, version, permit = approve(broker, effective_policy)
    revised_policy = effective_policy.model_copy(
        update={"organization_revision": effective_policy.organization_revision + 1}
    )
    revised_context = commit_context(revised_policy, version)

    with pytest.raises(AuthorizationError, match="stale policy revision"):
        broker.authorize_and_consume(
            permit_id=permit.id,
            effective_policy=revised_policy,
            context=revised_context,
        )
