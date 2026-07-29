"""Deterministic platform, organization, and request policy precedence."""

from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from sentinel_api.domain.common import ContractModel


class ProtectedAction(StrEnum):
    EMAIL_SEND = "email_send"
    FILE_UPLOAD = "file_upload"
    SPEND = "spend"
    DELETE = "delete"


class PlatformInvariants(ContractModel):
    research_agents_can_execute_protected_actions: bool = False
    exact_payload_approval_required: bool = True
    commit_time_authorization_required: bool = True
    reconcile_unknown_outcomes_before_retry: bool = True

    @model_validator(mode="after")
    def prevent_unsafe_platform_configuration(self) -> Self:
        required = (
            not self.research_agents_can_execute_protected_actions
            and self.exact_payload_approval_required
            and self.commit_time_authorization_required
            and self.reconcile_unknown_outcomes_before_retry
        )
        if not required:
            raise ValueError("platform security invariants cannot be weakened")
        return self


class OrganizationPolicy(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    organization_id: UUID
    revision: int = Field(default=1, ge=1)
    allowed_country_codes: frozenset[str] = frozenset()
    restricted_categories: frozenset[str] = frozenset()
    required_evidence_types: frozenset[str] = frozenset()
    protected_actions: frozenset[ProtectedAction] = frozenset({ProtectedAction.EMAIL_SEND})
    controlled_recipient: str | None = None


class RequestPolicyOverlay(ContractModel):
    allowed_country_codes: frozenset[str] | None = None
    additional_restricted_categories: frozenset[str] = frozenset()
    additional_required_evidence_types: frozenset[str] = frozenset()
    allowed_actions: frozenset[ProtectedAction] = frozenset()
    controlled_recipient: str | None = None


class EffectivePolicy(ContractModel):
    platform: PlatformInvariants
    organization_policy_id: UUID
    organization_revision: int
    allowed_country_codes: frozenset[str]
    restricted_categories: frozenset[str]
    required_evidence_types: frozenset[str]
    protected_actions: frozenset[ProtectedAction]
    allowed_actions: frozenset[ProtectedAction]
    controlled_recipient: str | None


def resolve_policy(
    organization: OrganizationPolicy,
    overlay: RequestPolicyOverlay,
    platform: PlatformInvariants | None = None,
) -> EffectivePolicy:
    """Merge policy layers while refusing request-level privilege expansion."""

    invariants = platform or PlatformInvariants()
    organization_countries = organization.allowed_country_codes
    requested_countries = overlay.allowed_country_codes
    if requested_countries is None:
        effective_countries = organization_countries
    elif organization_countries and not requested_countries <= organization_countries:
        raise ValueError("request policy cannot expand organization country access")
    else:
        effective_countries = requested_countries

    if not overlay.allowed_actions <= organization.protected_actions:
        raise ValueError("request policy cannot authorize an organization-disabled action")

    controlled_recipient = overlay.controlled_recipient or organization.controlled_recipient
    if (
        organization.controlled_recipient
        and overlay.controlled_recipient
        and overlay.controlled_recipient != organization.controlled_recipient
    ):
        raise ValueError("request policy cannot replace the controlled recipient")

    return EffectivePolicy(
        platform=invariants,
        organization_policy_id=organization.id,
        organization_revision=organization.revision,
        allowed_country_codes=effective_countries,
        restricted_categories=(
            organization.restricted_categories | overlay.additional_restricted_categories
        ),
        required_evidence_types=(
            organization.required_evidence_types | overlay.additional_required_evidence_types
        ),
        protected_actions=organization.protected_actions,
        allowed_actions=overlay.allowed_actions,
        controlled_recipient=controlled_recipient,
    )
