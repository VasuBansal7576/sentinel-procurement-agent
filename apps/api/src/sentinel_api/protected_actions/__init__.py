"""Exact approval and protected external-action authorization."""

from sentinel_api.protected_actions.broker import (
    ApprovalBroker,
    AuthorizationError,
    AuthorizedAction,
    CommitContext,
    PolicyDecision,
    ProposalDiff,
)
from sentinel_api.protected_actions.canonical import (
    CanonicalizationError,
    canonical_json,
    payload_digest,
)
from sentinel_api.protected_actions.outcomes import (
    InvalidOutcomeTransition,
    OutcomeMachine,
)
from sentinel_api.protected_actions.postgres import PostgresApprovalBroker

__all__ = [
    "ApprovalBroker",
    "AuthorizationError",
    "AuthorizedAction",
    "CanonicalizationError",
    "CommitContext",
    "InvalidOutcomeTransition",
    "OutcomeMachine",
    "PolicyDecision",
    "PostgresApprovalBroker",
    "ProposalDiff",
    "canonical_json",
    "payload_digest",
]
