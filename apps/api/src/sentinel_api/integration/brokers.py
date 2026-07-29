"""Typing seam shared by synchronous and PostgreSQL approval brokers."""

from __future__ import annotations

from collections.abc import Awaitable
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from sentinel_api.domain import ApprovalPermit, EffectivePolicy, Proposal, ProposalVersion
from sentinel_api.protected_actions import (
    AuthorizedAction,
    CommitContext,
    PolicyDecision,
    ProposalDiff,
)


async def await_result[T](value: T | Awaitable[T]) -> T:
    if isinstance(value, Awaitable):
        return await value
    return value


class ApprovalBrokerAdapter(Protocol):
    def create_proposal(
        self,
        *,
        run_id: UUID,
        request_revision_id: UUID,
        action_type: str,
        payload: object,
        attachment_artifact_ids: tuple[UUID, ...] = (),
        attachment_sha256: tuple[str, ...] = (),
    ) -> tuple[Proposal, ProposalVersion] | Awaitable[tuple[Proposal, ProposalVersion]]: ...

    def edit_proposal(
        self,
        proposal_id: UUID,
        *,
        payload: object,
        attachment_artifact_ids: tuple[UUID, ...] = (),
        attachment_sha256: tuple[str, ...] = (),
    ) -> (
        tuple[Proposal, ProposalVersion, ProposalDiff]
        | Awaitable[tuple[Proposal, ProposalVersion, ProposalDiff]]
    ): ...

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
    ) -> ApprovalPermit | Awaitable[ApprovalPermit]: ...

    def get_proposal(
        self,
        proposal_id: UUID,
    ) -> Proposal | Awaitable[Proposal]: ...

    def get_version(
        self,
        proposal_id: UUID,
        version: int,
    ) -> ProposalVersion | Awaitable[ProposalVersion]: ...

    def authorize_and_consume(
        self,
        *,
        permit_id: UUID,
        effective_policy: EffectivePolicy,
        context: CommitContext,
        now: datetime | None = None,
    ) -> AuthorizedAction | Awaitable[AuthorizedAction]: ...
