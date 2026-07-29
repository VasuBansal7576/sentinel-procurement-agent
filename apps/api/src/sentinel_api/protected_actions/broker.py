"""Proposal versioning, exact approval, and commit-time authorization."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import RLock
from uuid import UUID, uuid4

from pydantic import Field

from sentinel_api.domain import (
    ActionIntent,
    ApprovalPermit,
    ContractModel,
    EffectivePolicy,
    Proposal,
    ProposalVersion,
    RiskClass,
    utc_now,
)
from sentinel_api.domain.actions import ProposalStatus
from sentinel_api.domain.policy import ProtectedAction
from sentinel_api.protected_actions.canonical import canonical_json


class AuthorizationError(RuntimeError):
    """Raised when a protected action does not match current authority."""


class PolicyDecision(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    action: ProtectedAction
    allowed: bool
    reason: str = Field(min_length=2, max_length=1000)
    organization_policy_id: UUID
    organization_revision: int = Field(ge=1)
    decided_at: datetime = Field(default_factory=utc_now)


class ProposalDiff(ContractModel):
    proposal_id: UUID
    from_version: int = Field(ge=1)
    to_version: int = Field(ge=1)
    changed_fields: tuple[str, ...]
    attachments_changed: bool


class AuthorizedAction(ContractModel):
    intent: ActionIntent
    canonical_payload: str
    permit_nonce: UUID


class CommitContext(ContractModel):
    executor_id: UUID
    capabilities: frozenset[str] = Field(min_length=1)
    organization_policy_id: UUID
    organization_revision: int = Field(ge=1)
    proposal_version: int = Field(ge=1)
    canonical_payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    attachment_sha256: tuple[str, ...] = ()


@dataclass
class _ProposalRecord:
    proposal: Proposal
    versions: dict[int, ProposalVersion]


class ApprovalBroker:
    """In-memory policy boundary; persistence is injected when PR 4 is integrated."""

    def __init__(self) -> None:
        self._proposals: dict[UUID, _ProposalRecord] = {}
        self._permits: dict[UUID, ApprovalPermit] = {}
        self._consumed_permit_ids: set[UUID] = set()
        self._lock = RLock()

    def create_proposal(
        self,
        *,
        run_id: UUID,
        request_revision_id: UUID,
        action_type: str,
        payload: object,
        attachment_artifact_ids: tuple[UUID, ...] = (),
        attachment_sha256: tuple[str, ...] = (),
    ) -> tuple[Proposal, ProposalVersion]:
        with self._lock:
            proposal = Proposal(
                run_id=run_id,
                request_revision_id=request_revision_id,
                status=ProposalStatus.PENDING_APPROVAL,
            )
            version = self._make_version(
                proposal_id=proposal.id,
                version=1,
                action_type=action_type,
                payload=payload,
                attachment_artifact_ids=attachment_artifact_ids,
                attachment_sha256=attachment_sha256,
            )
            self._proposals[proposal.id] = _ProposalRecord(
                proposal=proposal,
                versions={1: version},
            )
            return proposal, version

    def edit_proposal(
        self,
        proposal_id: UUID,
        *,
        payload: object,
        attachment_artifact_ids: tuple[UUID, ...] = (),
        attachment_sha256: tuple[str, ...] = (),
    ) -> tuple[Proposal, ProposalVersion, ProposalDiff]:
        with self._lock:
            record = self._record(proposal_id)
            previous = record.versions[record.proposal.current_version]
            next_version = record.proposal.current_version + 1
            version = self._make_version(
                proposal_id=proposal_id,
                version=next_version,
                action_type=previous.action_type,
                payload=payload,
                attachment_artifact_ids=attachment_artifact_ids,
                attachment_sha256=attachment_sha256,
            )
            record.versions[next_version] = version
            record.proposal = record.proposal.model_copy(
                update={
                    "current_version": next_version,
                    "status": ProposalStatus.PENDING_APPROVAL,
                }
            )
            diff = ProposalDiff(
                proposal_id=proposal_id,
                from_version=previous.version,
                to_version=next_version,
                changed_fields=self._changed_fields(previous, version),
                attachments_changed=(previous.attachment_sha256 != version.attachment_sha256),
            )
            return record.proposal, version, diff

    def issue_permit(
        self,
        *,
        proposal_id: UUID,
        proposal_version: int,
        expected_payload_sha256: str,
        expected_attachment_sha256: tuple[str, ...],
        policy_decision: PolicyDecision,
        effective_policy: EffectivePolicy,
        approver_id: UUID,
        ttl: timedelta = timedelta(minutes=15),
        now: datetime | None = None,
    ) -> ApprovalPermit:
        issued_at = now or utc_now()
        with self._lock:
            record = self._record(proposal_id)
            version = self._version(record, proposal_version)
            self._validate_policy_decision(
                policy_decision,
                effective_policy,
                expected_action=self._policy_action_for(version),
            )
            if record.proposal.current_version != proposal_version:
                raise AuthorizationError("only the current proposal version can be approved")
            if version.canonical_payload_sha256 != expected_payload_sha256:
                raise AuthorizationError("approval preview does not match canonical payload")
            if version.attachment_sha256 != expected_attachment_sha256:
                raise AuthorizationError("approval preview does not match attachment digests")
            self._validate_payload_policy(version, effective_policy)
            permit = ApprovalPermit(
                proposal_id=proposal_id,
                proposal_version=proposal_version,
                action_type=version.action_type,
                canonical_payload_sha256=version.canonical_payload_sha256,
                attachment_sha256=version.attachment_sha256,
                policy_decision_id=policy_decision.id,
                organization_policy_id=policy_decision.organization_policy_id,
                organization_revision=policy_decision.organization_revision,
                risk_class=RiskClass.EXTERNAL_SEND,
                approver_id=approver_id,
                approved_at=issued_at,
                expires_at=issued_at + ttl,
            )
            self._permits[permit.id] = permit
            record.proposal = record.proposal.model_copy(update={"status": ProposalStatus.APPROVED})
            return permit

    def authorize_and_consume(
        self,
        *,
        permit_id: UUID,
        effective_policy: EffectivePolicy,
        context: CommitContext,
        now: datetime | None = None,
    ) -> AuthorizedAction:
        authorized_at = now or utc_now()
        with self._lock:
            permit = self._permits.get(permit_id)
            if permit is None:
                raise AuthorizationError("approval permit does not exist")
            if permit_id in self._consumed_permit_ids:
                raise AuthorizationError("approval permit has already been consumed")
            if authorized_at >= permit.expires_at:
                raise AuthorizationError("approval permit has expired")
            if "protected_action.execute" not in context.capabilities:
                raise AuthorizationError("executor lacks protected-action capability")
            if context.organization_policy_id != effective_policy.organization_policy_id:
                raise AuthorizationError("commit context belongs to another organization policy")
            if context.organization_revision != effective_policy.organization_revision:
                raise AuthorizationError("commit context uses a stale policy revision")
            if permit.organization_policy_id != effective_policy.organization_policy_id:
                raise AuthorizationError("approval permit belongs to another organization policy")
            if permit.organization_revision != effective_policy.organization_revision:
                raise AuthorizationError("approval permit was issued under a stale policy revision")
            record = self._record(permit.proposal_id)
            if record.proposal.current_version != permit.proposal_version:
                raise AuthorizationError("proposal was edited after approval")
            if context.proposal_version != permit.proposal_version:
                raise AuthorizationError("commit context proposal version does not match permit")
            if record.proposal.status is not ProposalStatus.APPROVED:
                raise AuthorizationError("proposal is not approved")
            version = self._version(record, permit.proposal_version)
            if version.canonical_payload_sha256 != permit.canonical_payload_sha256:
                raise AuthorizationError("approved payload digest no longer matches")
            if context.canonical_payload_sha256 != permit.canonical_payload_sha256:
                raise AuthorizationError("commit context payload digest does not match permit")
            if version.attachment_sha256 != permit.attachment_sha256:
                raise AuthorizationError("approved attachment digests no longer match")
            if context.attachment_sha256 != permit.attachment_sha256:
                raise AuthorizationError("commit context attachment digests do not match permit")
            self._validate_payload_policy(version, effective_policy)
            idempotency_material = (
                f"{permit.proposal_id}:{permit.proposal_version}:{permit.nonce}"
            ).encode()
            idempotency_key = hashlib.sha256(idempotency_material).hexdigest()
            intent = ActionIntent(
                proposal_id=permit.proposal_id,
                proposal_version=permit.proposal_version,
                permit_id=permit.id,
                idempotency_key=idempotency_key,
                payload_fingerprint=version.canonical_payload_sha256,
                created_at=authorized_at,
            )
            self._consumed_permit_ids.add(permit.id)
            self._permits[permit.id] = permit.model_copy(update={"consumed_at": authorized_at})
            record.proposal = record.proposal.model_copy(update={"status": ProposalStatus.EXECUTED})
            return AuthorizedAction(
                intent=intent,
                canonical_payload=version.canonical_payload,
                permit_nonce=permit.nonce,
            )

    def get_proposal(self, proposal_id: UUID) -> Proposal:
        with self._lock:
            return self._record(proposal_id).proposal

    def get_version(self, proposal_id: UUID, version: int) -> ProposalVersion:
        with self._lock:
            return self._version(self._record(proposal_id), version)

    @staticmethod
    def _make_version(
        *,
        proposal_id: UUID,
        version: int,
        action_type: str,
        payload: object,
        attachment_artifact_ids: tuple[UUID, ...],
        attachment_sha256: tuple[str, ...],
    ) -> ProposalVersion:
        canonical = canonical_json(payload)
        return ProposalVersion(
            proposal_id=proposal_id,
            version=version,
            action_type=action_type,
            canonical_payload=canonical.decode(),
            canonical_payload_sha256=hashlib.sha256(canonical).hexdigest(),
            attachment_artifact_ids=attachment_artifact_ids,
            attachment_sha256=attachment_sha256,
        )

    @staticmethod
    def _changed_fields(
        previous: ProposalVersion,
        current: ProposalVersion,
    ) -> tuple[str, ...]:
        previous_payload = json.loads(previous.canonical_payload)
        current_payload = json.loads(current.canonical_payload)
        if not isinstance(previous_payload, dict) or not isinstance(current_payload, dict):
            return ("$",) if previous_payload != current_payload else ()
        keys = set(previous_payload) | set(current_payload)
        return tuple(
            sorted(key for key in keys if previous_payload.get(key) != current_payload.get(key))
        )

    @staticmethod
    def _validate_policy_decision(
        decision: PolicyDecision,
        policy: EffectivePolicy,
        *,
        expected_action: ProtectedAction,
    ) -> None:
        if not decision.allowed:
            raise AuthorizationError(f"policy denied action: {decision.reason}")
        if decision.organization_policy_id != policy.organization_policy_id:
            raise AuthorizationError("policy decision belongs to another organization policy")
        if decision.organization_revision != policy.organization_revision:
            raise AuthorizationError("policy decision is stale")
        if decision.action is not expected_action:
            raise AuthorizationError("policy decision does not authorize the proposed action")
        if decision.action not in policy.allowed_actions:
            raise AuthorizationError("action is not enabled by effective policy")

    @staticmethod
    def _policy_action_for(version: ProposalVersion) -> ProtectedAction:
        if version.action_type == "email.send":
            return ProtectedAction.EMAIL_SEND
        raise AuthorizationError("unsupported protected action type")

    @staticmethod
    def _validate_payload_policy(
        version: ProposalVersion,
        policy: EffectivePolicy,
    ) -> None:
        if version.action_type != "email.send":
            raise AuthorizationError("unsupported protected action type")
        if ProtectedAction.EMAIL_SEND not in policy.allowed_actions:
            raise AuthorizationError("email send is not enabled by effective policy")
        payload = json.loads(version.canonical_payload)
        if not isinstance(payload, dict):
            raise AuthorizationError("email payload must be an object")
        recipient = payload.get("to")
        if not isinstance(recipient, str):
            raise AuthorizationError("email payload requires one recipient")
        if not policy.controlled_recipient:
            raise AuthorizationError("controlled recipient is not configured")
        if recipient.casefold() != policy.controlled_recipient.casefold():
            raise AuthorizationError("recipient is outside the controlled allowlist")

    def _record(self, proposal_id: UUID) -> _ProposalRecord:
        record = self._proposals.get(proposal_id)
        if record is None:
            raise AuthorizationError("proposal does not exist")
        return record

    @staticmethod
    def _version(record: _ProposalRecord, version: int) -> ProposalVersion:
        proposal_version = record.versions.get(version)
        if proposal_version is None:
            raise AuthorizationError("proposal version does not exist")
        return proposal_version
