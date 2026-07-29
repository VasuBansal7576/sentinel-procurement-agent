import pytest

from sentinel_api.protected_actions import (
    CanonicalizationError,
    canonical_json,
    payload_digest,
)


def test_payload_order_does_not_change_approved_bytes() -> None:
    left = {"subject": "RFQ", "to": "demo@example.test", "attachments": ["a", "b"]}
    right = {"attachments": ["a", "b"], "to": "demo@example.test", "subject": "RFQ"}

    assert canonical_json(left) == canonical_json(right)
    assert payload_digest(left) == payload_digest(right)


def test_floats_are_rejected_at_approval_boundary() -> None:
    with pytest.raises(CanonicalizationError, match="floating-point"):
        canonical_json({"price": 12.3})
