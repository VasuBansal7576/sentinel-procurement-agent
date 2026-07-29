"""Proposal, approval permit, and external-action outcome contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from sentinel_api.domain.common import ContractModel, utc_now
from sentinel_api.domain.tools import RiskClass


class ProposalStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    EXECUTED = "executed"


class ActionOutcomeState(StrEnum):
    PREPARED = "prepared"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    DISPATCHING = "dispatching"
    CONFIRMED = "confirmed"
    FAILED_BEFORE_EFFECT = "failed_before_effect"
    OUTCOME_UNKNOWN = "outcome_unknown"
    RECONCILING = "reconciling"
    SAFE_TO_RETRY = "safe_to_retry"
    NEEDS_OPERATOR = "needs_operator"


class ProposalVersion(ContractModel):
    proposal_id: UUID
    version: int = Field(ge=1)
    action_type: str = Field(min_length=2, max_length=100)
    canonical_payload: str = Field(min_length=2, max_length=100_000)
    canonical_payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    attachment_artifact_ids: tuple[UUID, ...] = ()
    attachment_sha256: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_attachment_manifest(self) -> Self:
        if len(self.attachment_artifact_ids) != len(self.attachment_sha256):
            raise ValueError("each attachment must have an artifact ID and digest")
        return self


class Proposal(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    request_revision_id: UUID
    current_version: int = Field(default=1, ge=1)
    status: ProposalStatus = ProposalStatus.DRAFT


class ApprovalPermit(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    proposal_id: UUID
    proposal_version: int = Field(ge=1)
    action_type: str = Field(min_length=2, max_length=100)
    canonical_payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    attachment_sha256: tuple[str, ...] = ()
    policy_decision_id: UUID
    organization_policy_id: UUID
    organization_revision: int = Field(ge=1)
    risk_class: RiskClass
    approver_id: UUID
    approved_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    nonce: UUID = Field(default_factory=uuid4)
    consumed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_lifetime(self) -> Self:
        if self.expires_at <= self.approved_at:
            raise ValueError("approval permit must expire after it is issued")
        if self.consumed_at is not None and self.consumed_at < self.approved_at:
            raise ValueError("approval permit cannot be consumed before it is issued")
        return self


class ActionIntent(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    proposal_id: UUID
    proposal_version: int = Field(ge=1)
    permit_id: UUID
    idempotency_key: str = Field(min_length=8, max_length=200)
    payload_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: datetime = Field(default_factory=utc_now)


class ActionOutcome(ContractModel):
    action_intent_id: UUID
    state: ActionOutcomeState
    provider_reference: str | None = Field(default=None, max_length=500)
    detail: str | None = Field(default=None, max_length=2000)
    updated_at: datetime = Field(default_factory=utc_now)
