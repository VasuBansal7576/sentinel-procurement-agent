from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from sentinel_api.domain import (
    ApprovalPermit,
    RetryPolicy,
    RiskClass,
    ToolMetadata,
    ToolNamespace,
)


def test_research_actor_cannot_receive_protected_sink() -> None:
    with pytest.raises(ValidationError, match="research actors cannot"):
        ToolMetadata(
            namespace=ToolNamespace.EMAIL,
            name="send",
            version="1.0.0",
            risk_class=RiskClass.EXTERNAL_SEND,
            allowed_actor_capabilities=frozenset({"research"}),
            timeout_seconds=30,
            retry_policy=RetryPolicy(),
            idempotent=True,
            accepts_untrusted_data=False,
            protected_sink=True,
        )


def test_approval_permit_round_trips_as_json() -> None:
    now = datetime.now(UTC)
    permit = ApprovalPermit(
        proposal_id=uuid4(),
        proposal_version=2,
        action_type="email.send",
        canonical_payload_sha256="a" * 64,
        attachment_sha256=("b" * 64,),
        policy_decision_id=uuid4(),
        organization_policy_id=uuid4(),
        organization_revision=1,
        risk_class=RiskClass.EXTERNAL_SEND,
        approver_id=uuid4(),
        approved_at=now,
        expires_at=now + timedelta(minutes=10),
    )

    restored = ApprovalPermit.model_validate_json(permit.model_dump_json())

    assert restored == permit
