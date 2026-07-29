from uuid import uuid4

import pytest
from pydantic import ValidationError

from sentinel_api.domain import OrganizationPolicy, PlatformInvariants, RequestPolicyOverlay
from sentinel_api.domain.policy import ProtectedAction, resolve_policy


def test_request_policy_can_tighten_but_not_expand_country_access() -> None:
    organization = OrganizationPolicy(
        organization_id=uuid4(),
        allowed_country_codes=frozenset({"IN", "US"}),
        restricted_categories=frozenset({"weapons"}),
        required_evidence_types=frozenset({"manufacturer"}),
        protected_actions=frozenset({ProtectedAction.EMAIL_SEND}),
        controlled_recipient="demo@example.test",
    )
    overlay = RequestPolicyOverlay(
        allowed_country_codes=frozenset({"IN"}),
        additional_restricted_categories=frozenset({"alcohol"}),
        additional_required_evidence_types=frozenset({"warranty"}),
        allowed_actions=frozenset({ProtectedAction.EMAIL_SEND}),
    )

    policy = resolve_policy(organization, overlay)

    assert policy.allowed_country_codes == frozenset({"IN"})
    assert policy.restricted_categories == frozenset({"weapons", "alcohol"})
    assert policy.required_evidence_types == frozenset({"manufacturer", "warranty"})
    assert policy.controlled_recipient == "demo@example.test"


def test_request_policy_cannot_expand_country_access() -> None:
    organization = OrganizationPolicy(
        organization_id=uuid4(),
        allowed_country_codes=frozenset({"IN"}),
    )

    with pytest.raises(ValueError, match="cannot expand"):
        resolve_policy(
            organization,
            RequestPolicyOverlay(allowed_country_codes=frozenset({"IN", "US"})),
        )


def test_platform_invariants_cannot_be_weakened() -> None:
    with pytest.raises(ValidationError, match="cannot be weakened"):
        PlatformInvariants(research_agents_can_execute_protected_actions=True)
